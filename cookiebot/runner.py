"""Main loop: time-based scheduler driving the game."""
from __future__ import annotations

import argparse
import json
import logging
import queue
import time
from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel

from cookiebot import achievements, garden, scripts
from cookiebot.config import (
    AUTOCLICK_COOKIE_MS,
    AUTOCLICK_GOLDEN_MS,
    GOLDEN_COOKIE_UPGRADE_NAMES,
    Config,
    is_never_buy_upgrade,
    profile_backups_dir,
    profile_dir,
    profile_save_file,
    profile_trials_dir,
)
from cookiebot.driver import build_driver, open_game, start_auto_intervals
from cookiebot.heuristics import (
    Building,
    Upgrade,
    achievement_milk_bonus_cps,
    building_buy_crosses_achievement,
    building_from_js,
    is_achievement_unlock_upgrade,
    lucky_reserve_target,
    marginal_bank_value_per_s,
    mean_spawn_interval_s,
    parse_upgrade_gain,
    score_upgrade,
)
from cookiebot.hotkeys import HotkeyListener
from cookiebot.locks import ProfileInUseError, ProfileLock
from cookiebot.persistence import (
    load_global_settings,
    load_profile_settings,
    load_save,
    migrate_legacy_save,
    save_global_settings,
    write_backup,
    write_save,
)
from cookiebot.status import BotStatus, render as render_status
from cookiebot.trial import TrialLogger

log = logging.getLogger("cookiebot")


@dataclass
class _Task:
    name: str
    period_s: float
    next_due: float
    fn: Callable[[], None]


class Scheduler:
    def __init__(self) -> None:
        self._tasks: list[_Task] = []
        self.paused = False

    def every(
        self,
        period_s: float,
        fn: Callable[[], None],
        name: str | None = None,
        delay_first: bool = False,
    ) -> None:
        first_due = time.monotonic() + (period_s if delay_first else 0.0)
        self._tasks.append(_Task(name or fn.__name__, period_s, first_due, fn))

    def tick(self) -> float:
        now = time.monotonic()
        next_wake = now + 1.0
        for task in self._tasks:
            if now >= task.next_due:
                if not self.paused:
                    try:
                        task.fn()
                    except Exception:
                        log.exception("task %s raised", task.name)
                task.next_due = time.monotonic() + task.period_s
            next_wake = min(next_wake, task.next_due)
        return max(0.0, next_wake - time.monotonic())


class CookieBot:
    HOTKEYS = (
        ("q", "quit (saves first)"),
        ("p", "pause / resume Python-driven actions"),
        ("s", "save now"),
        ("w", "pop all wrinklers now"),
        ("a", "fire safe one-shot achievements"),
        ("?", "show this help"),
    )

    def __init__(self, cfg: Config, console: Console | None = None) -> None:
        self.cfg = cfg
        self.save_file = profile_save_file(cfg.save_profile)
        self.driver = build_driver(cfg)
        self.upgrades_by_id: dict[int, Upgrade] = {}
        self.golden_count: int = 0
        self._resync_golden: bool = False  # set after an ascension to re-read count
        self._sched = Scheduler()
        self._actions: queue.Queue[Callable[[], None]] = queue.Queue()
        self._quit = False
        self._dragon_aura_logged = False
        self._aura_pending_logged = False
        self._aura_warn_logged = False
        self._heavenly_warn_logged = False
        self._season_logged = False
        # Season dwell tracking for the stall-escape policy.
        self._season_cur: str | None = None
        self._season_last_owned = 0
        self._season_progress_at = 0.0
        # Idle-reason logging: distinguish "banking" from an actual stall.
        self._last_buy_at = 0.0
        self._last_idle_log_at = 0.0
        # Combo (FtHoF) observability throttles. -inf so the first event always logs.
        self._combo_warn_at = float("-inf")
        self._combo_nogrimoire_logged = False
        self._click_buff_on = False
        self._cps_combo_on = False
        # Detailed per-combo debug log (file).
        self._combo_fh = None
        self._combo_log_active = False
        self._combo_log_start_t = 0.0
        self._combo_log_start_cookies = 0.0
        self._combo_log_peak = 1.0
        self._sell_mode_logged = False
        # Cache of upgrade-id → true marginal CPS, refreshed on a slow tick in
        # payback mode (recomputing it every 50 ms purchase tick is too costly).
        self._upgrade_marginals: dict[int, float] = {}
        # Cache of building-name → true marginal CPS of one more of that building
        # (captures the cross-building synergy boost a new building gives others,
        # which the static storedCps/price heuristic misses). Same slow cadence.
        self._building_marginals: dict[str, float] = {}
        # Cache of tier-unlock bundles (buy N buildings + the upgrade they
        # unlock), refreshed on the same slow cadence.
        self._tier_bundles: list[dict] = []
        # Golden-cookie spawn timing for the dynamic reserve, refreshed slowly.
        self._golden_timing: dict = {}
        # Last garden snapshot (cheap; refreshed each garden tick when auto_garden).
        self._garden_state: dict = {}
        # Best purchase value-per-cost this tick; the dynamic reserve compares
        # the marginal banking value against it.
        self._best_purchase_score: float = 0.0
        self._trial: TrialLogger | None = None  # set in setup() when ab_log is on
        self._tick_gate_monotonic = 0.0  # A/B: hold purchases until shared start
        self._console = console or Console()
        self._hotkeys = HotkeyListener(self._enqueue_key)
        self._status = BotStatus()

    def setup(self, start_intervals: bool = True) -> None:
        """Prepare the bot. With ``start_intervals=False`` the auto-clicker is
        NOT started — the A/B orchestrator uses this to load both games fully
        and then start them at the same instant via ``begin_play()``."""
        migrate_legacy_save()
        log.info("using save profile %r (%s)", self.cfg.save_profile, self.save_file.name)
        open_game(self.driver, seed=self.cfg.ab_seed)
        if self.cfg.ab_seed:
            log.info("A/B mode: RNG seeded with %r", self.cfg.ab_seed)
        self._init_trial_log()
        self._init_combo_log()
        if self.cfg.fresh:
            log.info("hard-resetting game state (fresh start)")
            self.driver.execute_script(scripts.HARD_RESET)
        else:
            load_save(self.driver, self.save_file)
        # Headless instances render for nobody — stop drawing to cut CPU. Never
        # blank a visible window the user is watching.
        if self.cfg.disable_rendering and self.cfg.headless:
            self.driver.execute_script(scripts.DISABLE_RENDERING)
            log.info("rendering disabled (headless CPU saver)")
        # With a barrier, hold the auto-clicker until every instance is loaded —
        # we start it after the barrier wait below, not now.
        if start_intervals and not self.cfg.barrier_dir:
            start_auto_intervals(self.driver)
        self._load_upgrade_catalog()
        self.golden_count = int(self.driver.execute_script(
            scripts.COUNT_GOLDEN_COOKIE_UPGRADES, GOLDEN_COOKIE_UPGRADE_NAMES,
        ))
        self._status.update(
            golden_count=self.golden_count,
            wrinkler_strategy=self.cfg.wrinkler_strategy,
            last_action="setup complete",
        )
        self.driver.execute_script(scripts.SET_PANTHEON)
        self._refresh_achievement_count()
        if self.cfg.auto_fire_safe_achievements:
            self._fire_achievements(achievements.SAFE)
        if self.cfg.auto_fire_risky_achievements:
            self._fire_achievements(achievements.RISKY)
        if self.cfg.auto_fire_safe_achievements or self.cfg.auto_fire_risky_achievements:
            self._refresh_achievement_count()
        if self.cfg.dynamic_golden_reserve:
            self._refresh_golden_timing()  # prime before first purchase tick
            log.info("dynamic golden-cookie reserve on")
        log.info("setup complete; %d golden cookie upgrades owned, %d achievements",
                 self.golden_count, self._status.achievements_owned)
        try:
            if self.driver.execute_script(scripts.CLEAR_STUCK_SPECIAL_MENU):
                log.info("cleared a stuck dragon/Santa popup left open from a prior run")
        except Exception:
            log.exception("special-menu cleanup failed")
        try:
            check = self.driver.execute_script(scripts.SELF_CHECK) or {}
            # 'locked' = minigame not unlocked yet (expected), not a failure.
            fails = {k: v for k, v in check.items() if v not in ("ok", "locked")}
            if fails:
                log.warning("SELF-CHECK issues: %s | all: %s", fails, check)
            else:
                log.info("SELF-CHECK: all subsystems ok (%d)", len(check))
        except Exception:
            log.exception("self-check failed")
        try:
            diag = self.driver.execute_script(scripts.DIAGNOSE_DRAGON_SEASON)
            log.info("DIAG dragon/season: %s", diag)
        except Exception:
            log.exception("dragon/season diagnostic failed")
        try:
            heav = self.driver.execute_script(scripts.DIAGNOSE_HEAVENLY)
            log.info("DIAG heavenly: %s", heav)
        except Exception:
            log.exception("heavenly diagnostic failed")

        # Batch barrier: signal we're loaded, wait for the shared start moment,
        # then begin playing — so all instances start at the same instant.
        if self.cfg.barrier_dir:
            self._wait_at_barrier()

    def _wait_at_barrier(self) -> None:
        """Drop a 'ready' marker and block until the orchestrator's start signal,
        then start the auto-clicker gated on that shared wall-clock moment."""
        import os
        bdir = self.cfg.barrier_dir
        os.makedirs(bdir, exist_ok=True)
        me = os.path.basename(self.save_file.parent.name) or self.cfg.save_profile
        ready = os.path.join(bdir, f"{me}.ready")
        start_file = os.path.join(bdir, "start_at_ms")
        try:
            with open(ready, "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            log.exception("barrier: could not write ready marker")
        log.info("barrier: ready, waiting for shared start…")
        # Poll for the start timestamp the orchestrator writes once all are ready.
        deadline = time.monotonic() + 600  # safety cap (10 min)
        start_at_ms = None
        while time.monotonic() < deadline:
            try:
                with open(start_file) as f:
                    start_at_ms = float(f.read().strip())
                break
            except (OSError, ValueError):
                time.sleep(0.2)
        if start_at_ms is None:
            log.warning("barrier: no start signal; starting now")
            start_auto_intervals(self.driver)
            return
        self.begin_play(start_at_ms=start_at_ms)
        log.info("barrier: released at shared start")

    def _load_upgrade_catalog(self) -> None:
        raw = self.driver.execute_script(scripts.GET_ALL_UPGRADES)
        ach = 0
        for uid, desc, base_price, name, pool in raw:
            unlocks = is_achievement_unlock_upgrade(name or "")
            ach += int(unlocks)
            self.upgrades_by_id[int(uid)] = Upgrade(
                id=int(uid),
                gain=parse_upgrade_gain(desc or ""),
                base_price=float(base_price),
                unlocks_achievement=unlocks,
                name=name or f"upgrade #{uid}",
                pool=pool or "",
            )
        log.info("indexed %d upgrades (%d flagged as achievement-unlocks)",
                 len(self.upgrades_by_id), ach)

    # ---- periodic actions --------------------------------------------------

    def purchase_tick(self) -> None:
        snap = self.driver.execute_script(scripts.GAME_SNAPSHOT)
        cookies: float = snap["cookies"]
        cookies_ps: float = snap["cookiesPs"]
        # Reserve shown as seconds-of-CPS. Dynamic mode: the EV-driven target;
        # fixed mode: the setting, but only once all 3 holding upgrades are owned.
        if self.cfg.dynamic_golden_reserve and self._golden_timing:
            reserve_target = (self._reserve_target(cookies_ps) / cookies_ps) if cookies_ps else 0.0
        else:
            reserve_target = self.cfg.lucky_reserve_seconds if self.golden_count == 3 else 0.0
        self._status.update(
            cookies=cookies, cookies_ps=cookies_ps, reserve_target_s=reserve_target
        )
        # If the player has flipped the store to sell mode, .buy() is redirected
        # to .sell() by the game — pause purchasing so we don't dump buildings.
        if snap.get("buyMode", 1) == -1:
            if not self._sell_mode_logged:
                log.info("store in sell mode — pausing purchases")
                self._sell_mode_logged = True
            self._status.update(last_action="paused (sell mode)")
            return
        self._sell_mode_logged = False
        buildings: list[Building] = [building_from_js(b) for b in snap["buildings"]]
        # Live per-upgrade prices keyed by id (reflects active discounts).
        store_prices: dict[int, float] = {
            int(u["id"]): float(u["price"]) for u in snap["upgradesInStore"]
        }

        if not buildings:
            return

        if cookies_ps <= 0:
            # Game just started — wait for the best-heuristic building. Clicking
            # at ~40 c/s reaches 100 c (Grandma) in ~2.5 s, and Grandma's CPS
            # per cost beats Cursors at that price point. On a *loaded* save CpS
            # should never be 0, so flag it (throttled) — that's the classic
            # "loaded an established save but the bot does nothing" symptom.
            now = time.monotonic()
            if now - self._last_idle_log_at >= 15.0:
                self._last_idle_log_at = now
                log.info("CpS reads 0 with %d buildings (save still loading, or store "
                         "paused?) — buying best building if affordable", len(buildings))
            best = max(buildings, key=lambda b: b.heuristic)
            if cookies >= best.price:
                self._buy_building(best)
            return

        # Building score is value-per-cost (= 1/payback). In payback mode: use the
        # larger of the static storedCps/price heuristic and the TRUE marginal
        # (which credits the cross-building synergy a new building gives others),
        # then add the achievement-milk bonus to buys that cross a count threshold.
        def building_score(b: Building) -> float:
            score = b.heuristic
            if self.cfg.payback_mode and b.price > 0:
                marginal = self._building_marginals.get(b.name)
                if marginal is not None:
                    score = max(score, marginal / b.price)
                if building_buy_crosses_achievement(b.amount):
                    score += achievement_milk_bonus_cps(cookies_ps) / b.price
            return score

        clicks_per_sec = 1000.0 / max(AUTOCLICK_COOKIE_MS, 1)

        def upgrade_score(uid: int) -> float:
            price = store_prices[uid]
            parsed = score_upgrade(self.upgrades_by_id[uid], cookies_ps, buildings, price,
                                   clicks_per_sec=clicks_per_sec)
            # Payback mode is a HYBRID: take the larger of the parsed score and
            # the game's true marginal-CPS score. The marginal catches passive
            # multipliers (flavored cookies, kittens, tiers, synergies) the
            # parser approximates; the parser catches golden-cookie / clicking
            # upgrades whose value isn't passive CPS, so their true marginal is
            # ~0 and a pure-marginal heuristic wrongly skips them.
            if self.cfg.payback_mode and uid in self._upgrade_marginals and price > 0:
                return max(parsed, self._upgrade_marginals[uid] / price)
            return parsed

        best_building = max(buildings, key=building_score)
        scored_upgrades = [
            (uid, upgrade_score(uid))
            for uid in store_prices
            if uid in self.upgrades_by_id
            and not is_never_buy_upgrade(
                self.upgrades_by_id[uid].name, self.upgrades_by_id[uid].pool
            )
        ]
        best_upgrade = max(scored_upgrades, key=lambda x: x[1], default=(None, 0.0))

        # Best tier-unlock bundle (buy N buildings + the upgrade they unlock),
        # scored as combined gain / combined cost so it competes head-to-head.
        best_bundle = None
        best_bundle_score = 0.0
        for bd in self._tier_bundles:
            if bd["cost"] > 0 and bd["gainCps"] > 0:
                sc = bd["gainCps"] / bd["cost"]
                if sc > best_bundle_score:
                    best_bundle, best_bundle_score = bd, sc

        self._update_next_buys(cookies, buildings, scored_upgrades, store_prices)

        # Remember the best available purchase score (value-per-cost) so the
        # dynamic reserve can compare banking-for-golden-cookies against it.
        self._best_purchase_score = max(
            building_score(best_building), best_upgrade[1], best_bundle_score,
        )

        # Optional payback ceiling: skip anything slower to pay off than the cap.
        # score is value-per-cost, so the minimum acceptable score is 1/cap_seconds.
        min_score = 0.0
        if self.cfg.payback_mode and self.cfg.payback_cap_minutes > 0:
            min_score = 1.0 / (self.cfg.payback_cap_minutes * 60)

        building_best_score = building_score(best_building)
        # Pick the best action among building / upgrade / bundle. A winning bundle
        # is bought on its own (it already buys N buildings + the tier upgrade in
        # one shot). Otherwise drain every worthwhile building/upgrade affordable
        # right now in a single batched call — one item in steady state, the whole
        # post-ascension shopping list during catch-up.
        acted = False
        if (
            best_bundle is not None
            and best_bundle_score >= max(building_best_score, best_upgrade[1], min_score)
            and self._affordable_with_reserve(cookies, cookies_ps, float(best_bundle["cost"]))
        ):
            # The bundle is the best move AND affordable — take it (N buildings +
            # the tier upgrade at once).
            acted = self._maybe_buy_bundle(best_bundle, cookies, cookies_ps)
        if not acted:
            # No bundle, or it's unaffordable -> drain: buy the best AFFORDABLE
            # single (or bank per the dynamic horizon). This is what stops the bot
            # idling on an unaffordable bundle while affordable buildings sit there.
            acted = bool(self._buy_drain(
                cookies, cookies_ps, buildings, scored_upgrades,
                store_prices, building_score, min_score,
            ))

        # Visibility: on a mature save the bot often "looks idle" because the best
        # buy is unaffordable and it's banking. Say so (throttled) instead of
        # silently doing nothing, so an actual stall is distinguishable from
        # correct banking.
        now = time.monotonic()
        if acted:
            self._last_buy_at = now
        elif now - self._last_idle_log_at >= 15.0 and now - self._last_buy_at >= 10.0:
            self._last_idle_log_at = now
            self._note_idle(cookies, cookies_ps, buildings, scored_upgrades,
                            store_prices, reserve_target)

    def _note_idle(self, cookies, cookies_ps, buildings, scored_upgrades,
                   store_prices, reserve_target_s) -> None:
        """Log what the bot is actually waiting on. We report the SOONEST worthwhile
        buy (the cheapest item) — not the highest-scored one, which may be hours
        away and made the log read like a multi-hour stall when the bot is really
        about to buy a cheap building shortly."""
        cands = [(b.price, b.name) for b in buildings if b.price > 0]
        cands += [(store_prices.get(uid, float("inf")), self.upgrades_by_id[uid].name)
                  for uid, _ in scored_upgrades]
        cands = [(p, n) for p, n in cands if p > 0 and p != float("inf")]
        if not cands:
            return
        price, name = min(cands)
        reserve_cookies = cookies_ps * reserve_target_s
        short = max(0.0, price + reserve_cookies - cookies)
        eta = short / cookies_ps if cookies_ps > 0 else float("inf")
        if short > 0:
            log.info("banking: next buy %s in ~%.0fs (%.2e short, cps %.2e%s)",
                     name, eta, short, cookies_ps,
                     f", reserve {reserve_target_s:g}s" if reserve_target_s else "")
        else:
            log.info("idle: cheapest buy %s affordable but not bought — possible stall "
                     "(have %.2e, cps %.2e)", name, cookies, cookies_ps)

    def _buy_drain(
        self,
        cookies: float,
        cookies_ps: float,
        buildings: list[Building],
        scored_upgrades: list[tuple[int, float]],
        store_prices: dict[int, float],
        building_score,
        min_score: float,
    ) -> None:
        """Buy the best-scored affordable building/upgrade repeatedly, batching the
        whole run into one browser call.

        The pick + affordability logic mirrors the single-buy path exactly
        (``building_score`` / upgrade scores / ``_affordable_with_reserve``), but
        runs against a *local* model of the bank and prices so a tick with a large
        surplus drains the full no-brainer list without a Selenium round trip per
        item. Each building buy bumps that building's price ×1.15 (the game's
        growth factor) and decays its value-per-cost the same way; each upgrade is
        one-shot. The golden-cookie reserve is honoured per simulated buy, so the
        drain stops at the reserve floor just like the normal tick.

        Accuracy guard: the FIRST buy each tick runs against the live snapshot, so
        it is exactly as accurate as the old single-buy path — expensive "should I
        save up for this?" decisions are never made off the simulated model. Every
        *subsequent* buy in the same tick is only allowed when it is cheap relative
        to the remaining bank (``bulk_cheap_fraction``), where the local model's
        drift can't change the decision. The moment the best remaining item is
        pricey enough to be a real save-up tradeoff, the drain stops and hands that
        single decision back to the next tick, which re-snapshots and re-scores it
        exactly. So bulk only ever fast-paths pocket-change buys.

        With ``bulk_buy`` off the cap is 1, reproducing the old one-per-tick pace.
        """
        cap = max(1, self.cfg.bulk_max_buys) if self.cfg.bulk_buy else 1
        cheap_fraction = max(0.0, self.cfg.bulk_cheap_fraction)

        # Mutable local models. Buildings carry a live value/cost and price; the
        # achievement-milk crossing bonus (payback mode) is folded into the
        # starting score and then decayed — close enough for a catch-up burst.
        bmodel = {
            b.name: {"name": b.name, "score": building_score(b), "price": b.price}
            for b in buildings
        }
        umodel = {
            uid: {"score": sc, "price": store_prices[uid]} for uid, sc in scored_upgrades
        }

        bank = cookies
        batch: list[list] = []  # compact actions for scripts.BULK_BUY
        bought: list[tuple[str, str, float, float]] = []  # (kind, name, price, score) for logging

        def affordable(price: float) -> bool:
            return self._affordable_with_reserve(bank, cookies_ps, price)

        for i in range(cap):
            best_b = max(bmodel.values(), key=lambda d: d["score"], default=None)
            best_u_uid = max(umodel, key=lambda k: umodel[k]["score"], default=None)
            b_score = best_b["score"] if best_b is not None else float("-inf")
            u_score = umodel[best_u_uid]["score"] if best_u_uid is not None else float("-inf")

            # Highest-scored candidate overall (kind, ref, price, score).
            if u_score >= b_score and best_u_uid is not None:
                top = ("u", best_u_uid, umodel[best_u_uid]["price"], u_score)
            elif best_b is not None:
                top = ("b", best_b["name"], best_b["price"], b_score)
            else:
                break

            # Past the first (exact) buy, only fast-path pocket-change items; a
            # pricier one is a real save-up decision, deferred to the next tick.
            too_pricey = i > 0 and top[2] > bank * cheap_fraction

            if not too_pricey and affordable(top[2]):
                # The best item is affordable — buy it. (No payback-cap gate here:
                # buying any positive-CpS item beats idling, which is what the cap
                # used to cause — the "scored below threshold" stalls.)
                choice = top
            elif i > 0:
                break  # batch continuation only fast-paths cheap, affordable buys
            else:
                # First buy, top item unaffordable. Buy the best AFFORDABLE item to
                # keep compounding — UNLESS banking for the far better item is truly
                # worth it. "Worth it" = the wait is shorter than how much SOONER the
                # top recoups its cost than the best affordable buy (its payback
                # ADVANTAGE = 1/score_aff − 1/score_top, in seconds). That threshold
                # is stage-adaptive: paybacks lengthen as the game slows, so the
                # tolerated wait grows on its own — no flat constant. It also shrinks
                # to ~0 when the affordable item is nearly as efficient as the top
                # (then just buy it). bank_horizon_s only caps it as a safety ceiling.
                ab = max((d for d in bmodel.values() if affordable(d["price"])),
                         key=lambda d: d["score"], default=None)
                au = max((uid for uid in umodel if affordable(umodel[uid]["price"])),
                         key=lambda uid: umodel[uid]["score"], default=None)
                ab_score = ab["score"] if ab is not None else float("-inf")
                au_score = umodel[au]["score"] if au is not None else float("-inf")
                if au is not None and au_score >= ab_score:
                    best_aff = ("u", au, umodel[au]["price"], au_score)
                elif ab is not None:
                    best_aff = ("b", ab["name"], ab["price"], ab["score"])
                else:
                    break  # nothing affordable -> bank (reserve, or can't afford anything)

                wait_s = (top[2] - bank) / cookies_ps if cookies_ps > 0 else float("inf")
                payback_top = 1.0 / top[3] if top[3] > 0 else float("inf")
                payback_aff = 1.0 / best_aff[3] if best_aff[3] > 0 else float("inf")
                worth_waiting = min(payback_aff - payback_top, self.cfg.bank_horizon_s)
                # wait<=0 = the reserve (not price) blocks the top -> bank (golden
                # saving). Don't bank for a top below the payback cap either.
                cap_ok = min_score <= 0 or top[3] >= min_score
                if wait_s <= 0 or (cap_ok and wait_s < worth_waiting):
                    break  # bank for the clearly-better, soon-enough top item
                choice = best_aff

            kind, ref, price, sc = choice
            if kind == "u":
                up = self.upgrades_by_id[ref]
                batch.append(["u", ref])
                bought.append(("upgrade", up.name, price, sc))
                bank -= price
                del umodel[ref]
                if up.name in GOLDEN_COOKIE_UPGRADE_NAMES:
                    # Owning another holding upgrade changes the reserve rule;
                    # stop so the next tick re-evaluates with the new count.
                    break
            else:
                d = bmodel[ref]
                batch.append(["b", ref, 1])
                bought.append(("building", ref, price, d["score"]))
                bank -= price
                d["price"] *= 1.15
                d["score"] /= 1.15

        if not batch:
            return 0

        # Coalesce consecutive same-building buys into one buy(qty) call.
        coalesced: list[list] = []
        for action in batch:
            if (
                action[0] == "b"
                and coalesced
                and coalesced[-1][0] == "b"
                and coalesced[-1][1] == action[1]
            ):
                coalesced[-1][2] += action[2]
            else:
                coalesced.append(list(action))

        n = self.driver.execute_script(scripts.BULK_BUY, coalesced)
        spent = cookies - bank
        if len(bought) == 1:
            kind, name, _price, _score = bought[0]
            log.info("buy %s %s @ %.2e", kind, name, spent)
            self._status.update(last_action=f"buy {name}")
        else:
            log.info("bulk buy %d items, spent %.2e (cps=%.2f)", len(bought), spent, cookies_ps)
            self._status.update(last_action=f"bulk ×{n or len(bought)}")

        for kind, name, price, score in bought:
            if kind == "upgrade":
                if name in GOLDEN_COOKIE_UPGRADE_NAMES:
                    self.golden_count += 1
                    self._status.update(golden_count=self.golden_count)
            if self._trial is not None:
                self._trial.buy(kind, name, price, score)
        return len(bought)

    def _update_next_buys(
        self,
        cookies: float,
        buildings: list[Building],
        scored_upgrades: list[tuple[int, float]],
        store_prices: dict[int, float],
    ) -> None:
        """Push the top-3 candidates (buildings + upgrades) to the status panel."""
        candidates = [(b.name, b.heuristic, b.price) for b in buildings]
        candidates += [
            (self.upgrades_by_id[uid].name, score, store_prices[uid])
            for uid, score in scored_upgrades
        ]
        candidates.sort(key=lambda c: c[1], reverse=True)
        self._status.update(
            next_buys=[
                (name, score, cookies >= price) for name, score, price in candidates[:3]
            ]
        )

    def _reserve_target(self, cookies_ps: float) -> float:
        """Cookies to keep banked for golden-cookie payouts (display/fixed mode).
        Fixed: the setting. Dynamic: the EV target (extends to the larger Chain
        cap, ~12 h of CPS, since the Chain term keeps a little value past Lucky)."""
        if self.cfg.dynamic_golden_reserve and self._golden_timing:
            return lucky_reserve_target(cookies_ps, self._golden_timing.get("getLucky", False))
        return cookies_ps * self.cfg.lucky_reserve_seconds

    def _affordable_with_reserve(self, cookies: float, cookies_ps: float, price: float) -> bool:
        """Whether a purchase is affordable while keeping the golden-cookie reserve.

        Dynamic mode: bank a cookie only while its *marginal* golden-cookie value
        (Lucky + Chain, per second) beats the best available purchase's
        value-per-cost — a true EV comparison, so it won't hoard 12 h of CPS for
        a rare chain when buying returns more. Fixed mode: keep a flat reserve,
        engaged once all 3 holding upgrades are owned."""
        if self.cfg.dynamic_golden_reserve and self._golden_timing:
            interval = self._golden_timing.get("mean_interval_s", 0.0)
            get_lucky = self._golden_timing.get("getLucky", False)
            mv = marginal_bank_value_per_s(cookies, cookies_ps, interval, get_lucky)
            # If banking the next cookie is worth more than spending it, hold.
            if mv > self._best_purchase_score and cookies < price + cookies_ps:
                return False
            return cookies >= price

        if self.golden_count != 3:
            return cookies >= price
        reserve = self._reserve_target(cookies_ps)
        if cookies >= reserve + price:
            return True
        # Trivially cheap purchases (under 1 s of CPS) still go through if we have
        # at least 50 s of CPS banked — barely dents the reserve target.
        return cookies_ps > price and cookies_ps * 50 < cookies

    def _buy_building(self, b: Building) -> None:
        log.info("buy building %s @ %.2f", b.name, b.price)
        self.driver.execute_script(scripts.BUY_BUILDING, b.name, 1)
        self._status.update(last_action=f"buy {b.name}")
        if self._trial is not None:
            self._trial.buy("building", b.name, b.price, b.heuristic)

    def _maybe_buy_bundle(self, bundle: dict, cookies: float, cookies_ps: float) -> bool:
        cost = float(bundle["cost"])
        if not self._affordable_with_reserve(cookies, cookies_ps, cost):
            return False
        name, qty, up_id = bundle["building"], int(bundle["qty"]), int(bundle["upgradeId"])
        log.info("buy bundle: %d × %s + tier upgrade #%d (cost %.2e)", qty, name, up_id, cost)
        bought = self.driver.execute_script(scripts.BUY_TIER_BUNDLE, name, qty, up_id)
        self._status.update(last_action=f"bundle {qty}× {name} + tier")
        if self._trial is not None:
            self._trial.buy(
                "bundle", f"{qty}x {name}+tier#{up_id}", cost,
                bundle["gainCps"] / cost if cost else 0.0, float(bundle["gainCps"]),
            )
        # Force a fresh bundle eval next slow tick; this one is consumed.
        self._tier_bundles = [b for b in self._tier_bundles if b is not bundle]
        if not bought:
            log.info("bundle upgrade #%d didn't apply (locked?)", up_id)
        return True

    def lucky_tick(self) -> None:
        res = self.driver.execute_script(scripts.GET_LUCKY) or {}
        # Surface the live combo state so it's verifiable from the log/panel.
        click_mult = float(res.get("clickMult", 1.0))
        click_buffs = res.get("clickBuffs") or []
        cps_buffs = res.get("cpsBuffs") or []
        mult = float(res.get("mult", 1.0))
        self._status.update(
            combo_mult=mult,
            combo_buffs=int(res.get("n", 0)),
            combo_buff_names=cps_buffs,
            magic=res.get("magic"),
            magic_max=res.get("magicM"),
            click_mult=click_mult,
            click_buffs=click_buffs,
        )
        # Log a CpS combo when it lands (mult jumps), naming the buffs — so the
        # building-special / Dragon-Harvest boosts are visible, and it doubles as
        # proof the golden-cookie combo engine is actually firing.
        if mult >= 2.0 and not self._cps_combo_on:
            self._cps_combo_on = True
            log.info("COMBO ACTIVE: ×%.0f CpS — %s", mult, ", ".join(cps_buffs) or "buffs")
        elif mult < 1.5:
            self._cps_combo_on = False
        # Log a click buff (Dragonflight / Click frenzy) when it appears — the
        # autoclicker is cashing in on it even though it's not a CpS multiplier.
        if click_mult > 1.0 and not self._click_buff_on:
            self._click_buff_on = True
            log.info("CLICK BUFF: %s (×%.0f click) — autoclicker capitalizing",
                     ", ".join(click_buffs) or "active", click_mult)
        elif click_mult <= 1.0:
            self._click_buff_on = False
        n, mult = int(res.get("n", 0)), float(res.get("mult", 1.0))
        magic, magic_m = res.get("magic") or 0, res.get("magicM") or 0
        if res.get("cast"):
            log.info("COMBO: cast FtHoF on %d-buff stack (×%.1f CpS, magic %.0f/%.0f, %d on screen)",
                     n, mult, magic, magic_m, int(res.get("goldens", 0)))
            self._status.update(last_action=f"FtHoF combo ×{mult:.0f}")
            self._combo_warn_at = 0.0
        elif n >= 2 and res.get("hasGrimoire"):
            # Buff stack present but no cast — almost always not enough magic.
            now = time.monotonic()
            if now - self._combo_warn_at >= 20.0:
                self._combo_warn_at = now
                log.info("COMBO: %d-buff stack (×%.1f) but FtHoF NOT cast — magic %.0f/%.0f, "
                         "cost %.0f (low magic / regen-limited)", n, mult, magic, magic_m,
                         res.get("ftofCost") or 0)
        elif n >= 2 and not res.get("hasGrimoire") and not self._combo_nogrimoire_logged:
            log.info("COMBO: %d-buff stack but the Grimoire (Wizard tower minigame) isn't "
                     "unlocked yet — no FtHoF until it is", n)
            self._combo_nogrimoire_logged = True
        self._combo_log_tick(res)

    # ---- detailed combo debug log -----------------------------------------

    def _init_combo_log(self) -> None:
        if not self.cfg.combo_log:
            return
        try:
            stamp = self.driver.execute_script("return String(Date.now());")
            path = profile_dir(self.cfg.save_profile) / "combos" / f"combo_{stamp}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._combo_fh = open(path, "a", buffering=1)
            log.info("combo debug log → %s", path)
        except Exception:
            log.exception("could not open combo log")

    def _combo_write(self, record: dict) -> None:
        if self._combo_fh is None:
            return
        try:
            self._combo_fh.write(json.dumps(record) + "\n")
        except Exception:
            log.exception("combo log write failed")

    def _combo_log_tick(self, res: dict) -> None:
        """Record the full combo picture every tick a combo is active (or an
        FtHoF/sell/loan event fired), bracketed by start/end markers — so an
        overnight run leaves a complete, replayable record of every super-combo."""
        if self._combo_fh is None:
            return
        mult = float(res.get("mult", 1.0))
        click = float(res.get("clickMult", 1.0))
        events = res.get("events") or []
        active = mult >= 1.5 or click > 1.0
        now = time.monotonic()
        if active and not self._combo_log_active:
            self._combo_log_active = True
            self._combo_log_start_t = now
            self._combo_log_start_cookies = float(res.get("cookies") or 0.0)
            self._combo_log_peak = mult
            self._combo_write({"kind": "start", "t": res.get("now"),
                               "cookies": res.get("cookies"), "mult": mult,
                               "cpsBuffs": res.get("cpsBuffs"), "clickBuffs": res.get("clickBuffs")})
        if active or events:
            self._combo_log_peak = max(self._combo_log_peak, mult)
            self._combo_write({
                "kind": "tick", "t": res.get("now"), "cookies": res.get("cookies"),
                "cookiesPs": res.get("cookiesPs"), "unbuffedCps": res.get("unbuffedCps"),
                "mult": mult, "clickMult": click, "magic": res.get("magic"),
                "magicM": res.get("magicM"), "ftofCost": res.get("ftofCost"),
                "buffs": res.get("buffDetails"), "shimmers": res.get("shimmers"),
                "events": events,
            })
        if not active and self._combo_log_active:
            self._combo_log_active = False
            gained = float(res.get("cookies") or 0.0) - self._combo_log_start_cookies
            self._combo_write({"kind": "end", "t": res.get("now"),
                               "durationS": round(now - self._combo_log_start_t, 1),
                               "peakMult": round(self._combo_log_peak, 1),
                               "cookiesGained": gained, "cookies": res.get("cookies")})

    def achievement_threshold_tick(self) -> None:
        # Click the ticker only when it's genuinely useful: a fortune is showing,
        # or it's in the narrow-window "help!" state (awards Stifling the press).
        clicked = self.driver.execute_script(scripts.CLICK_TICKER_IF_USEFUL)
        if clicked == "fortune":
            log.info("clicked ticker fortune")
            self._status.update(last_action="clicked ticker fortune")
        elif clicked == "stifling":
            log.info("clicked ticker in help! state (Stifling the press)")
            self._status.update(last_action="ticker: Stifling the press")

        snap = self.driver.execute_script(scripts.GAME_SNAPSHOT)
        cookies = float(snap["cookies"])
        cookies_ps = float(snap["cookiesPs"])
        targets = self.driver.execute_script(
            scripts.EVALUATE_ACHIEVEMENT_BUILDINGS, self.cfg.achievement_max_step
        ) or []

        for t in targets:
            name, qty, cost, gain = t["name"], int(t["qty"]), float(t["cost"]), float(t["gainCps"])
            # Worth it only if the achievement's CPS gain pays back within the
            # configured window, AND we can afford it without dipping into the
            # Lucky reserve. This drops the old blanket "under 10 s of CPS" rule
            # that ignored whether the achievement was already won or valuable.
            if gain <= 0 or cost <= 0:
                continue
            payback_s = cost / gain
            if payback_s > self.cfg.achievement_payback_cap_s:
                continue
            if not self._affordable_with_reserve(cookies, cookies_ps, cost):
                continue
            log.info("buy %d × %s (achievement, payback %.0fs)", qty, name, payback_s)
            self.driver.execute_script(scripts.BUY_BUILDING, name, qty)
            self._status.update(last_action=f"buy {qty}× {name} (achiev)")
            cookies -= cost  # keep the running tally honest for the next target

    def minigame_tick(self) -> None:
        self.driver.execute_script(scripts.FARM_SUGAR_LUMPS)
        if self.cfg.auto_pledge:
            # Calms the Grandmapocalypse — off by default so wrinklers keep spawning.
            self.driver.execute_script(scripts.BUY_PLEDGE)
        self.garden_tick()
        self.driver.execute_script(scripts.CHECK_STOCK_MARKET)
        self.driver.execute_script(scripts.SET_PANTHEON)
        self._wrinkler_tick()

    def _wrinkler_tick(self) -> None:
        """Realise wrinkler value per the chosen strategy. Payout is 1.1x (3.3x
        shiny) of cookies DIGESTED, independent of CpS at pop time — so we pop to
        reclaim+reinvest and to cycle slots (shiny rolls / Halloween drops), NOT on
        Frenzy. Holding just locks the eaten cookies (≈50-70% of CpS at max slots)."""
        st = self.driver.execute_script(scripts.WRINKLER_STATE) or {}
        count, mx = int(st.get("count", 0)), int(st.get("max", 0))
        sucked, shiny = float(st.get("sucked", 0.0)), int(st.get("shiny", 0))
        self._status.update(wrinkler_count=count, wrinkler_max=mx,
                            wrinkler_sucked=sucked, wrinkler_shiny=shiny)
        if count == 0 or sucked <= 0:
            return
        halloween = st.get("season") == "halloween"
        strat = self.cfg.wrinkler_strategy
        if strat == "hold" and not halloween:
            return  # let them fatten; 'w' pops manually
        # Halloween or "always" → pop whenever anything's eaten (cycle for drops /
        # shiny). "pop-when-full" → pop the batch once every slot is occupied.
        pop = halloween or strat == "always" or (mx > 0 and count >= mx)
        if pop:
            self.driver.execute_script(scripts.POP_WRINKLERS)
            tag = " (Halloween farm)" if halloween else ""
            self._status.update(last_action=f"popped {count} wrinklers{tag}",
                                wrinkler_count=0, wrinkler_sucked=0.0, wrinkler_shiny=0)

    def garden_tick(self) -> None:
        """Play the Garden: breed the seed log up, then run the chosen layout.
        When auto_garden is off, preserve the old clover-spam behavior."""
        if not self.cfg.auto_garden:
            self.driver.execute_script(scripts.PLANT_CLOVERS)
            return
        try:
            snap = self.driver.execute_script(scripts.GET_GARDEN_STATE)
        except Exception:
            log.exception("garden snapshot failed")
            return
        if not snap or not snap.get("unlocked"):
            return  # Garden not built yet (no Farm level 1)
        self._garden_state = snap
        st = self._status
        # Don't let seed-buying dip below the golden-cookie reserve (same rule
        # the purchase logic uses: engaged once all 3 holding upgrades are owned).
        reserve = self._reserve_target(st.cookies_ps) if self.golden_count == 3 else 0.0
        actions = garden.decide_actions(
            snap, self.cfg.garden_strategy, self.cfg.garden_breed_soil,
            cookies=st.cookies, cookies_ps=st.cookies_ps, reserve_cookies=reserve,
        )
        if not actions:
            return
        try:
            res = self.driver.execute_script(scripts.GARDEN_ACTIONS, actions) or {}
        except Exception:
            log.exception("garden actions failed")
            return
        planted, harvested = int(res.get("planted", 0)), int(res.get("harvested", 0))
        if planted or harvested:
            self._status.update(
                last_action=f"garden: +{planted} planted / -{harvested} harvested"
            )
        # Persistent garden line for the side-quests panel.
        tiles = snap.get("tiles") or []
        if tiles:
            filled = sum(1 for t in tiles if t.get("id"))
            ripe = sum(1 for t in tiles if t.get("mature"))
            self._status.update(garden_summary=f"{filled}/{len(tiles)} tiles · {ripe} ripe")
        else:
            self._status.update(garden_summary="active")

    def _init_trial_log(self) -> None:
        if not self.cfg.ab_log:
            return
        # One log per run; the timestamp must come from the page (Date.now is
        # blocked in this Python env) — use the profile + a counter-free name
        # derived from the game's start. Simpler: let the OS provide it via the
        # driver's session, falling back to a fixed name the analysis can pair.
        stamp = self.driver.execute_script("return String(Date.now());")
        path = profile_trials_dir(self.cfg.save_profile) / f"trial_{stamp}.jsonl"
        self._trial = TrialLogger(path)
        # Log the FULL effective config so "what actually ran" is never
        # ambiguous (the previous 3-field meta hid that payback wasn't applied).
        from dataclasses import asdict
        self._trial.meta(profile=self.cfg.save_profile, config=asdict(self.cfg))
        log.info("A/B trial log → %s (payback=%s)", path.name, self.cfg.payback_mode)

    def trial_snapshot_tick(self) -> None:
        if self._trial is None:
            return
        try:
            snap = self.driver.execute_script(scripts.TRIAL_SNAPSHOT)
        except Exception:
            log.exception("trial snapshot failed")
            return
        self._trial.snapshot(snap)

    def marginals_tick(self) -> None:
        # Recompute true marginal CPS for in-store upgrades (payback mode only).
        # Expensive (two CalculateGains per upgrade), so this runs on its own
        # slow cadence and the purchase tick just reads the cache.
        try:
            result = self.driver.execute_script(scripts.EVALUATE_UPGRADE_MARGINALS)
        except Exception:
            log.exception("marginal evaluation failed")
            return
        deltas = result.get("deltas", {}) if result else {}
        self._upgrade_marginals = {int(k): float(v) for k, v in deltas.items()}

        # True marginal CPS for one more of each building (captures cross-building
        # synergies the static storedCps/price heuristic misses).
        try:
            bresult = self.driver.execute_script(scripts.EVALUATE_BUILDING_MARGINALS)
            bdeltas = bresult.get("deltas", {}) if bresult else {}
            self._building_marginals = {str(k): float(v) for k, v in bdeltas.items()}
        except Exception:
            log.exception("building marginal evaluation failed")
            self._building_marginals = {}

        # Refresh tier-unlock bundles on the same cadence (both use the costly
        # CalculateGains, both feed the purchase tick from a cache).
        try:
            self._tier_bundles = self.driver.execute_script(
                scripts.EVALUATE_TIER_BUNDLES, self.cfg.achievement_max_step
            ) or []
        except Exception:
            log.exception("tier-bundle evaluation failed")
            self._tier_bundles = []

    def save_tick(self) -> None:
        self.driver.execute_script(scripts.SPEND_SUGAR_LUMPS, self.cfg.sugar_lump_spread_cap)
        write_save(self.driver, self.save_file)
        self._refresh_achievement_count()
        # After an ascension, re-read the holding-upgrade count once the rebirth
        # has settled (handles permanent-upgrade carryover correctly).
        if self._resync_golden:
            self._resync_golden = False
            self._resync_golden_count()
        # Refresh golden-cookie spawn timing for the dynamic reserve. Changes
        # slowly (only when frequency upgrades are bought), so 30s is plenty.
        if self.cfg.dynamic_golden_reserve:
            self._refresh_golden_timing()

    def _refresh_golden_timing(self) -> None:
        try:
            t = self.driver.execute_script(scripts.GOLDEN_TIMING)
        except Exception:
            return
        if not t:
            return
        t["mean_interval_s"] = mean_spawn_interval_s(
            float(t.get("minFrames", 0)), float(t.get("maxFrames", 0)),
            float(t.get("fps", 30)),
        )
        self._golden_timing = t

    def backup_tick(self) -> None:
        backups_dir = profile_backups_dir(self.cfg.save_profile)
        path = write_backup(self.driver, backups_dir, self.cfg.backup_retention_days)
        if path is not None:
            self._status.update(last_action=f"backup → {path.name}")

    def dragon_tick(self) -> None:
        if self.cfg.auto_train_dragon:
            info = self.driver.execute_script(
                scripts.DRAGON_TRAIN,
                self.cfg.dragon_keep_buildings,
                self.cfg.dragon_sacrifice_bank_fraction,
            ) or {}
            if info.get("level") is not None:
                self._status.update(dragon_level=int(info["level"]),
                                    dragon_max=int(info.get("max", 0)))
            trained = info.get("trained") or []
            if trained:
                log.info("dragon leveled +%d → %s", len(trained), trained[-1])
                self._status.update(last_action=f"dragon → {trained[-1]}")
            blocked = info.get("blocked")
            if blocked and not trained:
                if blocked.get("reason") == "rebuy-too-pricey":
                    log.debug("dragon sacrifice held: rebuying it costs too much vs the bank")
                elif blocked.get("building"):
                    log.info("dragon level held: needs %s %s to sacrifice safely",
                             blocked.get("need"), blocked.get("building"))
            if info.get("needs_aura") and not self.cfg.auto_dragon_auras \
                    and not self._dragon_aura_logged:
                # Aura choice is strategic — leave it to the user and only say so once.
                log.info("dragon at an aura-training level; choose an aura manually to continue")
                self._dragon_aura_logged = True
        if self.cfg.auto_dragon_auras:
            prefs = [s.strip() for s in self.cfg.dragon_aura_combo.split(",") if s.strip()]
            if prefs:
                res = self.driver.execute_script(scripts.SET_DRAGON_AURAS, prefs) or {}
                if res.get("dragonLevel") is not None:
                    self._status.update(dragon_level=int(res["dragonLevel"]),
                                        dragon_max=int(res.get("dragonMax", 0)),
                                        dragon_auras=res.get("equipped", []))
                if res.get("changed"):
                    names = ", ".join(res["changed"])
                    log.info("dragon auras equipped: %s", names)
                    self._status.update(last_action=f"dragon auras: {names}")
                    self._aura_pending_logged = False  # re-arm for any still-locked slot
                if res.get("noSetFn") and not self._aura_warn_logged:
                    log.warning("this game build has no Game.SetDragonAura — can't auto-set auras")
                    self._aura_warn_logged = True
                if res.get("failed") and not self._aura_warn_logged:
                    log.warning("dragon aura(s) %s didn't take effect when set (API mismatch?)",
                                ", ".join(res["failed"]))
                    self._aura_warn_logged = True
                if res.get("missing") and not self._aura_warn_logged:
                    log.warning("dragon aura name(s) not found in this game: %s — check the names "
                                "in dragon_aura_combo", ", ".join(res["missing"]))
                    self._aura_warn_logged = True
                if res.get("pending") and not res.get("changed") and not self._aura_pending_logged:
                    log.info("dragon auras %s not unlocked yet (dragon level %s) — will equip as "
                             "Krumblor trains up", ", ".join(res["pending"]), res.get("dragonLevel"))
                    self._aura_pending_logged = True

    # Visit priority: fastest-to-complete / most-deterministic first. Valentine's
    # is 7 store buys (instant); Christmas is instant Santa + RNG reindeer; then the
    # RNG-only seasons, Easter (~20 eggs) last. 'fools' is skipped (no CpS upgrades).
    _SEASON_ORDER = ["valentines", "christmas", "halloween", "easter"]

    def _season_complete(self, season: str, counts: dict, santa_level: int, santa_max: int) -> bool:
        """A season is done when every collectible in its drop array is owned —
        plus, for Christmas, Santa is maxed. Unknown season (empty array) → treated
        done so a missing game array can't wedge the cycle."""
        c = counts.get(season)
        if not c or c.get("total", 0) == 0:
            return True
        if c.get("owned", 0) < c.get("total", 0):
            return False
        if season == "christmas" and 0 <= santa_level < santa_max:
            return False
        return True

    def season_tick(self) -> None:
        reserve_seconds = self.cfg.lucky_reserve_seconds if self.golden_count == 3 else 0.0
        res = self.driver.execute_script(scripts.SEASON_COLLECT, reserve_seconds) or {}
        if not res.get("hasSwitcher"):
            if not self._season_logged:
                log.info("auto-seasons on, but the 'Season switcher' heavenly upgrade "
                         "isn't owned yet — seasons can't be forced, skipping")
                self._season_logged = True
            return

        cur = res.get("season", "")
        counts = res.get("counts", {})
        santa_level = int(res.get("santaLevel", -1))
        santa_max = int(res.get("santaMax", 0))
        # Surface holiday progress in the live status panel.
        self._status.update(season=cur, season_counts=counts,
                            santa_level=santa_level, santa_max=santa_max)
        if res.get("santa"):
            log.info("Santa leveled +%d (now %s/%s)", res["santa"], santa_level, santa_max)
        if res.get("bought"):
            log.info("season %s: collected %d upgrade(s)", cur, res["bought"])
            self._status.update(last_action=f"season {cur}: +{res['bought']}")

        # Progress tracking for the dwell-cap stall escape.
        owned_total = sum(int(c.get("owned", 0)) for c in counts.values())
        now = time.monotonic()
        if cur != self._season_cur:
            self._season_cur = cur
            self._season_last_owned = owned_total
            self._season_progress_at = now
        elif owned_total > self._season_last_owned:
            self._season_last_owned = owned_total
            self._season_progress_at = now

        def done(s: str) -> bool:
            return self._season_complete(s, counts, santa_level, santa_max)

        incomplete = [s for s in self._SEASON_ORDER if not done(s)]
        target = None
        if not cur or done(cur):
            # Current season fully collected → move to the next incomplete one.
            target = incomplete[0] if incomplete else None
        elif (now - self._season_progress_at) > self.cfg.season_max_dwell_s:
            # Stalled on RNG with nothing new dropping → make progress elsewhere.
            others = [s for s in incomplete if s != cur]
            if others:
                target = others[0]
                log.info("season %s stalled (no new drops in %.0fs) — moving on to %s",
                         cur, self.cfg.season_max_dwell_s, target)

        if target and target != cur:
            ent = self.driver.execute_script(scripts.ENTER_SEASON, target, reserve_seconds) or {}
            if ent.get("ok"):
                log.info("entered season: %s", target)
                self._status.update(last_action=f"season → {target}")
            elif ent.get("reason") and ent.get("reason") != "reserve" and not self._season_logged:
                log.info("couldn't enter %s: %s", target, ent.get("reason"))

    def heavenly_tick(self) -> None:
        """Spend heavenly chips on the prestige tree (cheapest unlocked first).
        Unspent chips do nothing and heavenly upgrades are permanent, so this is
        pure upside. Self-verifying: if a buy doesn't take, it reports instead of
        spinning (tells us whether the call needs the ascend screen)."""
        res = self.driver.execute_script(scripts.BUY_HEAVENLY_UPGRADES) or {}
        self._status.update(heavenly_chips=float(res.get("chips", 0.0)),
                            heavenly_owned=int(res.get("owned", 0)),
                            heavenly_total=int(res.get("total", 0)))
        bought = res.get("bought") or []
        if bought:
            shown = ", ".join(bought[:4]) + ("…" if len(bought) > 4 else "")
            log.info("heavenly: bought %d upgrade(s) via %s — %s (chips left %.0f)",
                     len(bought), res.get("fn"), shown, float(res.get("chips", 0)))
            self._status.update(last_action=f"heavenly +{len(bought)}")
        elif res.get("failed") and not self._heavenly_warn_logged:
            log.warning("heavenly buy of '%s' didn't take effect — may need the ascend "
                        "screen or a different call; will keep trying", res.get("failed"))
            self._heavenly_warn_logged = True

    def ascend_tick(self) -> None:
        info = self.driver.execute_script(scripts.ASCEND_INFO)
        prestige = float(info["prestige"])
        potential = float(info["potential"])
        gain = potential - prestige
        if gain < 1:
            return
        # First ascension (prestige 0): go as soon as there's a chip to gain.
        # Otherwise require the configured relative jump.
        gain_pct = float("inf") if prestige <= 0 else gain / prestige * 100
        if gain_pct < self.cfg.auto_ascend_gain_pct:
            return
        log.info("auto-ascend: prestige %.0f → %.0f (+%.0f, %.1f%%)",
                 prestige, potential, gain, gain_pct)
        # Realise all wrinklers FIRST: their digested cookies count toward the
        # ascension total only once popped, otherwise they're lost on the reset.
        self.driver.execute_script(scripts.POP_WRINKLERS)
        # Save before the reset so a crash mid-ascension can't lose progress.
        write_save(self.driver, self.save_file)
        self.driver.execute_script(scripts.DO_ASCEND)
        self._status.update(last_action=f"ascended (+{gain:.0f} prestige)")
        # The holding upgrades (Lucky day / Serendipity / Get lucky) are wiped by
        # the reset unless kept as permanent upgrades, so the old golden_count is
        # stale — clear it now to drop the Lucky reserve, and re-sync from the
        # game on the next save tick once reincarnation has settled.
        self.golden_count = 0
        self._status.update(golden_count=0)
        self._resync_golden = True

    def _resync_golden_count(self) -> None:
        """Re-read how many holding upgrades are actually owned (covers the
        permanent-upgrade case where some persist across ascension)."""
        try:
            self.golden_count = int(self.driver.execute_script(
                scripts.COUNT_GOLDEN_COOKIE_UPGRADES, GOLDEN_COOKIE_UPGRADE_NAMES,
            ))
        except Exception:
            return
        self._status.update(golden_count=self.golden_count)

    # ---- achievement helpers ----------------------------------------------

    def _refresh_achievement_count(self) -> None:
        try:
            count = int(self.driver.execute_script(scripts.ACHIEVEMENTS_OWNED_COUNT) or 0)
        except Exception:
            return
        self._status.update(achievements_owned=count)

    def _fire_achievements(self, items: list[achievements.Achievement]) -> int:
        """Run each entry whose achievement isn't already unlocked. Returns count fired."""
        fired = 0
        for item in items:
            try:
                owned = self.driver.execute_script(scripts.ACHIEVEMENT_OWNED, item.name)
            except Exception:
                owned = None
            if owned:
                continue
            try:
                self.driver.execute_script(item.js)
            except Exception:
                log.exception("failed to fire '%s'", item.name)
                continue
            log.info("fired achievement: %s", item.name)
            fired += 1
        if fired:
            log.info("attempted %d achievement(s)", fired)
        return fired

    # ---- main loop --------------------------------------------------------

    # ---- hotkey plumbing ---------------------------------------------------

    def _enqueue_key(self, key: str) -> None:
        """Called on the listener thread. Defer the actual work to the main loop."""
        handler = {
            "q": self._do_quit,
            "p": self._do_toggle_pause,
            "s": self._do_save_now,
            "w": self._do_pop_wrinklers_now,
            "a": self._do_fire_safe_achievements,
            "?": self._do_print_hotkeys,
            "h": self._do_print_hotkeys,
            "\x03": self._do_quit,  # ctrl-c when cbreak swallows it
        }.get(key)
        if handler is not None:
            self._actions.put(handler)

    def _drain_actions(self) -> None:
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                return
            try:
                action()
            except Exception:
                log.exception("hotkey action failed")

    def _do_quit(self) -> None:
        log.info("quit requested")
        self._quit = True

    def _do_toggle_pause(self) -> None:
        self._sched.paused = not self._sched.paused
        self._status.update(paused=self._sched.paused)
        log.info("paused" if self._sched.paused else "resumed")

    def _do_save_now(self) -> None:
        log.info("manual save")
        write_save(self.driver, self.save_file)
        self._status.update(last_action="manual save")

    def _do_pop_wrinklers_now(self) -> None:
        log.info("popping all wrinklers")
        self.driver.execute_script(scripts.POP_WRINKLERS)
        self._status.update(last_action="popped wrinklers")

    def _do_fire_safe_achievements(self) -> None:
        fired = self._fire_achievements(achievements.SAFE)
        if fired:
            self._status.update(last_action=f"fired {fired} achievement(s)")
            self._refresh_achievement_count()

    def _do_print_hotkeys(self) -> None:
        self._print_hotkey_panel()

    def _print_hotkey_panel(self) -> None:
        lines = "\n".join(f"  [bold cyan]{k}[/]  {desc}" for k, desc in self.HOTKEYS)
        self._console.print(Panel(lines, title="Hotkeys", border_style="cyan", expand=False))

    # ---- main loop --------------------------------------------------------

    def begin_play(self, start_at_ms: float | None = None) -> None:
        """Start the in-page auto-clicker. For A/B, pass a shared wall-clock
        epoch (ms): both instances gate their first click on Date.now() reaching
        it, so they begin the same instant regardless of Selenium latency. Also
        gates this bot's Python-driven ticks (purchases) on the same moment."""
        if start_at_ms is None:
            start_auto_intervals(self.driver)
            return
        self.driver.execute_script(
            scripts.START_AUTOCLICK_GATED,
            AUTOCLICK_COOKIE_MS, AUTOCLICK_GOLDEN_MS, start_at_ms,
        )
        # Hold Python-driven ticks until the shared start, using local clock
        # offset from the page clock measured at call time.
        page_now = self.driver.execute_script("return Date.now();")
        self._tick_gate_monotonic = time.monotonic() + max(0.0, (start_at_ms - page_now) / 1000.0)

    def _schedule(self) -> None:
        """Register all periodic tasks on the scheduler."""
        self._sched.every(self.cfg.purchase_period_s, self.purchase_tick, "purchase")
        self._sched.every(self.cfg.lucky_period_s, self.lucky_tick, "lucky")
        self._sched.every(self.cfg.news_period_s, self.achievement_threshold_tick, "achievement-thresholds")
        self._sched.every(self.cfg.minigame_period_s, self.minigame_tick, "minigames")
        self._sched.every(self.cfg.save_period_s, self.save_tick, "save")
        if self._trial is not None:
            self._sched.every(self.cfg.ab_snapshot_period_s, self.trial_snapshot_tick, "trial-log")
        if self.cfg.payback_mode:
            self.marginals_tick()  # prime the cache
            self._sched.every(self.cfg.marginals_period_s, self.marginals_tick, "marginals")
            log.info("payback mode on (true marginal-CPS upgrade scoring)")
        if self.cfg.backup_interval_hours > 0:
            self._sched.every(self.cfg.backup_interval_hours * 3600, self.backup_tick,
                              "backup", delay_first=True)
        if self.cfg.auto_ascend:
            self._sched.every(self.cfg.ascend_period_s, self.ascend_tick, "ascend", delay_first=True)
        if self.cfg.auto_train_dragon or self.cfg.auto_dragon_auras:
            self._sched.every(self.cfg.dragon_period_s, self.dragon_tick, "dragon", delay_first=True)
        if self.cfg.auto_seasons:
            self._sched.every(self.cfg.season_period_s, self.season_tick, "seasons")
        if self.cfg.auto_heavenly:
            self._sched.every(self.cfg.heavenly_period_s, self.heavenly_tick, "heavenly")

    def tick_once(self) -> float:
        """Run one drain+schedule pass; returns seconds the caller may sleep.
        Lets an external loop (the A/B orchestrator) drive multiple bots."""
        self._drain_actions()
        # A/B: hold all scheduled actions until the shared start moment so
        # neither side purchases before the other.
        if self._tick_gate_monotonic:
            remaining = self._tick_gate_monotonic - time.monotonic()
            if remaining > 0:
                return min(remaining, 0.1)
            self._tick_gate_monotonic = 0.0
        return self._sched.tick()

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def quit_requested(self) -> bool:
        return self._quit

    def shutdown(self) -> None:
        if self._trial is not None:
            self._trial.close()
            self._trial = None
        try:
            write_save(self.driver, self.save_file)
        except Exception:
            log.exception("final save failed")
        self.driver.quit()

    def run(self) -> None:
        """Single-bot main loop: schedule, own the dashboard + hotkeys, tick."""
        self._schedule()
        hotkeys_active = self._hotkeys.start()
        if not hotkeys_active:
            log.info("hotkeys unavailable (not a TTY); use ctrl-c to stop")
        try:
            with Live(
                render_status(self._status),
                console=self._console,
                refresh_per_second=4,
                screen=False,
            ) as live:
                last_render = 0.0
                while not self._quit:
                    sleep_for = self.tick_once()
                    now = time.monotonic()
                    if now - last_render >= 0.25:
                        live.update(render_status(self._status))
                        last_render = now
                    if sleep_for > 0:
                        time.sleep(min(sleep_for, 0.1))
        except KeyboardInterrupt:
            log.info("stopping on user request")
        finally:
            self._hotkeys.stop()
            self.shutdown()


def _parse_args() -> tuple[Config, bool]:
    p = argparse.ArgumentParser(description="Cookie Clicker automation bot")
    # ``None`` sentinels let us tell explicit flags apart from defaults so the
    # persisted settings remain the source of truth unless overridden.
    p.add_argument("--browser", default=None, choices=("firefox", "chrome"))
    p.add_argument("--headless", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--fresh", action="store_true", help="Hard-reset the game on launch")
    p.add_argument("--profile", default=None, help="Named save profile to use")
    p.add_argument("--no-menu", action="store_true", help="Skip the interactive menu")
    p.add_argument("--ab-seed", default=None, help="Force deterministic RNG with this seed (A/B trials)")
    p.add_argument("--ab-log", action=argparse.BooleanOptionalAction, default=None,
                   help="Write a structured JSONL trial log to the profile's trials/ folder")
    p.add_argument("--barrier-dir", default=None,
                   help="Batch sync: signal ready here and wait for the shared start moment")
    args = p.parse_args()

    cfg = Config()
    # 1. global pointer → which profile is active
    load_global_settings(cfg)
    if args.profile is not None:
        cfg.save_profile = args.profile
    # 2. that profile's own strategy/browser settings
    load_profile_settings(cfg)
    # 3. CLI overrides win for this launch
    if args.browser is not None:
        cfg.browser = args.browser
    if args.headless is not None:
        cfg.headless = args.headless
    if args.ab_seed is not None:
        cfg.ab_seed = args.ab_seed
    if args.ab_log is not None:
        cfg.ab_log = args.ab_log
    cfg.fresh = args.fresh
    cfg.barrier_dir = args.barrier_dir or ""
    return cfg, args.no_menu


def main() -> None:
    console = Console()
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False, markup=True, rich_tracebacks=True)],
    )
    # Migrate old layouts (and split the old global settings) before anything
    # reads settings or lists profiles.
    migrate_legacy_save()
    cfg, no_menu = _parse_args()
    if not no_menu:
        from cookiebot.menu import show_menu
        result = show_menu(cfg)
        if result is None:
            return
        cfg = result
    # Persist the active-profile pointer; the menu already saved profile settings.
    save_global_settings(cfg)

    # Acquire an exclusive lock on the chosen profile so two instances never
    # write the same save. On conflict, resolve interactively (branch to a new
    # slot or pick another) or, with --no-menu, explain and exit.
    lock = _acquire_profile_lock(cfg, console, interactive=not no_menu)
    if lock is None:
        return
    save_global_settings(cfg)
    try:
        bot = CookieBot(cfg, console=console)
        bot.setup()
        bot.run()
    finally:
        lock.release()


def _acquire_profile_lock(cfg: Config, console: Console, interactive: bool):
    """Return a held ProfileLock for cfg.save_profile, or None to abort."""
    while True:
        lock = ProfileLock(cfg.save_profile)
        try:
            lock.acquire()
            return lock
        except ProfileInUseError as e:
            if not interactive:
                console.print(
                    f"[red]Profile '{e.profile}' is already running (pid {e.pid}).[/red]\n"
                    f"Pass [bold]--profile <other>[/bold] to run a second instance."
                )
                return None
            from cookiebot.menu import resolve_locked_profile
            if not resolve_locked_profile(cfg, e.pid):
                return None  # user cancelled
            # cfg.save_profile was updated; loop and try to lock the new choice.


if __name__ == "__main__":
    main()
