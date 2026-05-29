"""Main loop: time-based scheduler driving the game."""
from __future__ import annotations

import argparse
import logging
import queue
import time
from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel

from cookiebot import achievements, scripts
from cookiebot.config import (
    GOLDEN_COOKIE_UPGRADE_NAMES,
    Config,
    profile_backups_dir,
    profile_save_file,
)
from cookiebot.driver import build_driver, open_game, start_auto_intervals
from cookiebot.heuristics import (
    Building,
    Upgrade,
    achievement_milk_bonus_cps,
    building_buy_crosses_achievement,
    building_from_js,
    is_achievement_unlock_upgrade,
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
        self._sched = Scheduler()
        self._actions: queue.Queue[Callable[[], None]] = queue.Queue()
        self._quit = False
        self._dragon_aura_logged = False
        self._sell_mode_logged = False
        # Cache of upgrade-id → true marginal CPS, refreshed on a slow tick in
        # payback mode (recomputing it every 50 ms purchase tick is too costly).
        self._upgrade_marginals: dict[int, float] = {}
        # Cache of tier-unlock bundles (buy N buildings + the upgrade they
        # unlock), refreshed on the same slow cadence.
        self._tier_bundles: list[dict] = []
        self._console = console or Console()
        self._hotkeys = HotkeyListener(self._enqueue_key)
        self._status = BotStatus()

    def setup(self) -> None:
        migrate_legacy_save()
        log.info("using save profile %r (%s)", self.cfg.save_profile, self.save_file.name)
        open_game(self.driver)
        if self.cfg.fresh:
            log.info("hard-resetting game state (fresh start)")
            self.driver.execute_script(scripts.HARD_RESET)
        else:
            load_save(self.driver, self.save_file)
        start_auto_intervals(self.driver)
        self._load_upgrade_catalog()
        self.golden_count = int(self.driver.execute_script(
            scripts.COUNT_GOLDEN_COOKIE_UPGRADES, GOLDEN_COOKIE_UPGRADE_NAMES,
        ))
        self._status.update(
            golden_count=self.golden_count,
            wrinkler_auto_frenzy=self.cfg.auto_pop_wrinklers_in_frenzy,
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
        log.info("setup complete; %d golden cookie upgrades owned, %d achievements",
                 self.golden_count, self._status.achievements_owned)

    def _load_upgrade_catalog(self) -> None:
        raw = self.driver.execute_script(scripts.GET_ALL_UPGRADES)
        ach = 0
        for uid, desc, base_price, name in raw:
            unlocks = is_achievement_unlock_upgrade(name or "")
            ach += int(unlocks)
            self.upgrades_by_id[int(uid)] = Upgrade(
                id=int(uid),
                gain=parse_upgrade_gain(desc or ""),
                base_price=float(base_price),
                unlocks_achievement=unlocks,
                name=name or f"upgrade #{uid}",
            )
        log.info("indexed %d upgrades (%d flagged as achievement-unlocks)",
                 len(self.upgrades_by_id), ach)

    # ---- periodic actions --------------------------------------------------

    def purchase_tick(self) -> None:
        snap = self.driver.execute_script(scripts.GAME_SNAPSHOT)
        cookies: float = snap["cookies"]
        cookies_ps: float = snap["cookiesPs"]
        # The reserve only applies once all three holding upgrades are owned.
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
            # per cost beats Cursors at that price point.
            best = max(buildings, key=lambda b: b.heuristic)
            if cookies >= best.price:
                self._buy_building(best)
            return

        # Building score is value-per-cost (= 1/payback). In payback mode, credit
        # the achievement-milk bonus to buys that cross a count threshold.
        def building_score(b: Building) -> float:
            score = b.heuristic
            if (
                self.cfg.payback_mode
                and b.price > 0
                and building_buy_crosses_achievement(b.amount)
            ):
                score += achievement_milk_bonus_cps(cookies_ps) / b.price
            return score

        def upgrade_score(uid: int) -> float:
            price = store_prices[uid]
            parsed = score_upgrade(self.upgrades_by_id[uid], cookies_ps, buildings, price)
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

        # Optional payback ceiling: skip anything slower to pay off than the cap.
        # score is value-per-cost, so the minimum acceptable score is 1/cap_seconds.
        min_score = 0.0
        if self.cfg.payback_mode and self.cfg.payback_cap_minutes > 0:
            min_score = 1.0 / (self.cfg.payback_cap_minutes * 60)

        building_best_score = building_score(best_building)
        # Pick the single best action among building / upgrade / bundle.
        if best_bundle is not None and best_bundle_score >= max(
            building_best_score, best_upgrade[1], min_score
        ):
            self._maybe_buy_bundle(best_bundle, cookies, cookies_ps)
        elif best_upgrade[1] > building_best_score and best_upgrade[0] is not None:
            if best_upgrade[1] >= min_score:
                self._maybe_buy_upgrade(best_upgrade[0], cookies, cookies_ps, store_prices[best_upgrade[0]])
        elif building_best_score >= min_score:
            self._maybe_buy_building(best_building, cookies, cookies_ps)

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

    def _affordable_with_reserve(self, cookies: float, cookies_ps: float, price: float) -> bool:
        """Once all 3 holding upgrades are owned, keep a reserve so Lucky! payouts hit the cap."""
        if self.golden_count != 3:
            return cookies >= price
        reserve = cookies_ps * self.cfg.lucky_reserve_seconds
        if cookies >= reserve + price:
            return True
        # Trivially cheap purchases (under 1 s of CPS) still go through if we have
        # at least 50 s of CPS banked — barely dents the reserve target.
        return cookies_ps > price and cookies_ps * 50 < cookies

    def _maybe_buy_building(self, b: Building, cookies: float, cookies_ps: float) -> None:
        if self._affordable_with_reserve(cookies, cookies_ps, b.price):
            self._buy_building(b)

    def _maybe_buy_upgrade(self, uid: int, cookies: float, cookies_ps: float, price: float) -> None:
        up = self.upgrades_by_id[uid]
        if self._affordable_with_reserve(cookies, cookies_ps, price):
            log.info("buy upgrade id=%s reserve=%.1fs cps=%.2f", uid, cookies / cookies_ps, cookies_ps)
            self.driver.execute_script(scripts.BUY_UPGRADE, uid)
            if up.name in GOLDEN_COOKIE_UPGRADE_NAMES:
                self.golden_count += 1
                self._status.update(golden_count=self.golden_count)
            self._status.update(last_action=f"upgrade #{uid}")

    def _buy_building(self, b: Building) -> None:
        log.info("buy building %s @ %.2f", b.name, b.price)
        self.driver.execute_script(scripts.BUY_BUILDING, b.name, 1)
        self._status.update(last_action=f"buy {b.name}")

    def _maybe_buy_bundle(self, bundle: dict, cookies: float, cookies_ps: float) -> None:
        cost = float(bundle["cost"])
        if not self._affordable_with_reserve(cookies, cookies_ps, cost):
            return
        name, qty, up_id = bundle["building"], int(bundle["qty"]), int(bundle["upgradeId"])
        log.info("buy bundle: %d × %s + tier upgrade #%d (cost %.2e)", qty, name, up_id, cost)
        bought = self.driver.execute_script(scripts.BUY_TIER_BUNDLE, name, qty, up_id)
        self._status.update(last_action=f"bundle {qty}× {name} + tier")
        # Force a fresh bundle eval next slow tick; this one is consumed.
        self._tier_bundles = [b for b in self._tier_bundles if b is not bundle]
        if not bought:
            log.info("bundle upgrade #%d didn't apply (locked?)", up_id)

    def lucky_tick(self) -> None:
        self.driver.execute_script(scripts.GET_LUCKY)

    def achievement_threshold_tick(self) -> None:
        # Tap the ticker only when a fortune is showing (free upgrade / GC / cookies).
        if self.driver.execute_script(scripts.CLICK_TICKER_FORTUNE_IF_PRESENT):
            log.info("clicked ticker fortune")
            self._status.update(last_action="clicked ticker fortune")

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
        self.driver.execute_script(scripts.BUY_PLEDGE)
        self.driver.execute_script(scripts.PLANT_CLOVERS)
        self.driver.execute_script(scripts.CHECK_STOCK_MARKET)
        self.driver.execute_script(scripts.SET_PANTHEON)
        if self.cfg.auto_pop_wrinklers_in_frenzy:
            if self.driver.execute_script(scripts.POP_WRINKLERS_IF_FRENZY):
                self._status.update(last_action="popped wrinklers (frenzy)")

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
        self.driver.execute_script(scripts.SPEND_SUGAR_LUMPS)
        write_save(self.driver, self.save_file)
        self._refresh_achievement_count()

    def backup_tick(self) -> None:
        backups_dir = profile_backups_dir(self.cfg.save_profile)
        path = write_backup(self.driver, backups_dir, self.cfg.backup_retention_days)
        if path is not None:
            self._status.update(last_action=f"backup → {path.name}")

    def dragon_tick(self) -> None:
        info = self.driver.execute_script(scripts.DRAGON_TRAIN, self.cfg.dragon_keep_buildings)
        if info.get("trained"):
            log.info("dragon leveled to %s (%s)", info.get("level"), info.get("name"))
            self._status.update(last_action=f"dragon → {info.get('name')}")
        elif info.get("blocked"):
            log.info("dragon level held: needs %d %s to sacrifice safely",
                     info.get("need"), info.get("building"))
        elif info.get("needs_aura") and not self._dragon_aura_logged:
            # Aura choice is strategic — leave it to the user and only say so once.
            log.info("dragon at an aura-training level; choose an aura manually to continue")
            self._dragon_aura_logged = True

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
        # Save before the reset so a crash mid-ascension can't lose progress.
        write_save(self.driver, self.save_file)
        self.driver.execute_script(scripts.DO_ASCEND)
        self._status.update(last_action=f"ascended (+{gain:.0f} prestige)")

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

    def run(self) -> None:
        self._sched.every(self.cfg.purchase_period_s, self.purchase_tick, "purchase")
        self._sched.every(self.cfg.lucky_period_s, self.lucky_tick, "lucky")
        self._sched.every(self.cfg.news_period_s, self.achievement_threshold_tick, "achievement-thresholds")
        self._sched.every(self.cfg.minigame_period_s, self.minigame_tick, "minigames")
        self._sched.every(self.cfg.save_period_s, self.save_tick, "save")
        if self.cfg.payback_mode:
            # Prime the cache immediately so the first purchases use real
            # marginals, then refresh on its own cadence.
            self.marginals_tick()
            self._sched.every(self.cfg.marginals_period_s, self.marginals_tick, "marginals")
            log.info("payback mode on (true marginal-CPS upgrade scoring)")
        if self.cfg.backup_interval_hours > 0:
            self._sched.every(
                self.cfg.backup_interval_hours * 3600,
                self.backup_tick,
                "backup",
                delay_first=True,
            )
            log.info(
                "backups every %g h, retain %d days",
                self.cfg.backup_interval_hours,
                self.cfg.backup_retention_days,
            )
        if self.cfg.auto_ascend:
            self._sched.every(self.cfg.ascend_period_s, self.ascend_tick, "ascend", delay_first=True)
            log.info("auto-ascend on (≥%.0f%% prestige gain)", self.cfg.auto_ascend_gain_pct)
        if self.cfg.auto_train_dragon:
            self._sched.every(self.cfg.dragon_period_s, self.dragon_tick, "dragon", delay_first=True)
            log.info("auto-train dragon on (keep ≥%d of any sacrificed building)",
                     self.cfg.dragon_keep_buildings)
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
                    self._drain_actions()
                    sleep_for = self._sched.tick()
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
            try:
                write_save(self.driver, self.save_file)
            except Exception:
                log.exception("final save failed")
            self.driver.quit()


def _parse_args() -> tuple[Config, bool]:
    p = argparse.ArgumentParser(description="Cookie Clicker automation bot")
    # ``None`` sentinels let us tell explicit flags apart from defaults so the
    # persisted settings remain the source of truth unless overridden.
    p.add_argument("--browser", default=None, choices=("firefox", "chrome"))
    p.add_argument("--headless", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--fresh", action="store_true", help="Hard-reset the game on launch")
    p.add_argument("--profile", default=None, help="Named save profile to use")
    p.add_argument("--no-menu", action="store_true", help="Skip the interactive menu")
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
    cfg.fresh = args.fresh
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
