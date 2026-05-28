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
    BACKUPS_DIR,
    GOLDEN_COOKIE_UPGRADE_IDS,
    SAVE_FILE,
    SETTINGS_FILE,
    Config,
)
from cookiebot.driver import build_driver, open_game, start_auto_intervals
from cookiebot.heuristics import (
    Building,
    Upgrade,
    building_from_js,
    is_achievement_unlock_upgrade,
    parse_upgrade_gain,
    score_upgrade,
)
from cookiebot.hotkeys import HotkeyListener
from cookiebot.persistence import (
    load_save,
    load_settings,
    migrate_legacy_save,
    save_settings,
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
        ("w", "toggle wrinkler popping (default off)"),
        ("a", "fire safe one-shot achievements"),
        ("?", "show this help"),
    )

    def __init__(self, cfg: Config, console: Console | None = None) -> None:
        self.cfg = cfg
        self.driver = build_driver(cfg)
        self.upgrades_by_id: dict[int, Upgrade] = {}
        self.golden_count: int = 0
        self._sched = Scheduler()
        self._actions: queue.Queue[Callable[[], None]] = queue.Queue()
        self._quit = False
        self._pop_wrinklers = False
        self._console = console or Console()
        self._hotkeys = HotkeyListener(self._enqueue_key)
        self._status = BotStatus()

    def setup(self) -> None:
        migrate_legacy_save()
        open_game(self.driver)
        if self.cfg.fresh:
            log.info("hard-resetting game state (fresh start)")
            self.driver.execute_script(scripts.HARD_RESET)
        else:
            load_save(self.driver, SAVE_FILE)
        start_auto_intervals(self.driver)
        self._load_upgrade_catalog()
        self.golden_count = int(self.driver.execute_script(
            scripts.COUNT_GOLDEN_COOKIE_UPGRADES, GOLDEN_COOKIE_UPGRADE_IDS,
        ))
        self._status.update(golden_count=self.golden_count, last_action="setup complete")
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
            )
        log.info("indexed %d upgrades (%d flagged as achievement-unlocks)",
                 len(self.upgrades_by_id), ach)

    # ---- periodic actions --------------------------------------------------

    def purchase_tick(self) -> None:
        snap = self.driver.execute_script(scripts.GAME_SNAPSHOT)
        cookies: float = snap["cookies"]
        cookies_ps: float = snap["cookiesPs"]
        self._status.update(cookies=cookies, cookies_ps=cookies_ps)
        buildings: list[Building] = [building_from_js(b) for b in snap["buildings"]]
        store_ids: list[int] = [int(i) for i in snap["upgradesInStore"]]

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

        best_building = max(buildings, key=lambda b: b.heuristic)
        scored_upgrades = [
            (uid, score_upgrade(self.upgrades_by_id[uid], cookies_ps, buildings))
            for uid in store_ids
            if uid in self.upgrades_by_id
        ]
        best_upgrade = max(scored_upgrades, key=lambda x: x[1], default=(None, 0.0))

        if best_upgrade[1] > best_building.heuristic and best_upgrade[0] is not None:
            self._maybe_buy_upgrade(best_upgrade[0], cookies, cookies_ps)
        else:
            self._maybe_buy_building(best_building, cookies, cookies_ps)

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

    def _maybe_buy_upgrade(self, uid: int, cookies: float, cookies_ps: float) -> None:
        up = self.upgrades_by_id[uid]
        if self._affordable_with_reserve(cookies, cookies_ps, up.base_price):
            log.info("buy upgrade id=%s reserve=%.1fs cps=%.2f", uid, cookies / cookies_ps, cookies_ps)
            self.driver.execute_script(scripts.BUY_UPGRADE, uid)
            if uid in GOLDEN_COOKIE_UPGRADE_IDS:
                self.golden_count += 1
                self._status.update(golden_count=self.golden_count)
            self._status.update(last_action=f"upgrade #{uid}")

    def _buy_building(self, b: Building) -> None:
        log.info("buy building %s @ %.2f", b.name, b.price)
        self.driver.execute_script(scripts.BUY_BUILDING, b.name, 1)
        self._status.update(last_action=f"buy {b.name}")

    def lucky_tick(self) -> None:
        self.driver.execute_script(scripts.GET_LUCKY)

    def news_and_achievements_tick(self) -> None:
        self.driver.execute_script(scripts.CHECK_NEWS_FEED)
        targets = self.driver.execute_script(scripts.CALCULATE_ACHIEVEMENT_BUILDINGS) or []
        for name, qty in targets:
            log.info("buy %d × %s (achievement)", qty, name)
            self.driver.execute_script(scripts.BUY_BUILDING, name, qty)
            self._status.update(last_action=f"buy {qty}× {name}")

    def minigame_tick(self) -> None:
        self.driver.execute_script(scripts.FARM_SUGAR_LUMPS)
        self.driver.execute_script(scripts.BUY_PLEDGE)
        self.driver.execute_script(scripts.PLANT_CLOVERS)
        self.driver.execute_script(scripts.CHECK_STOCK_MARKET)
        self.driver.execute_script(scripts.SET_PANTHEON)
        if self._pop_wrinklers:
            self.driver.execute_script(scripts.POP_WRINKLERS)

    def save_tick(self) -> None:
        self.driver.execute_script(scripts.SPEND_SUGAR_LUMPS)
        write_save(self.driver, SAVE_FILE)
        self._refresh_achievement_count()

    def backup_tick(self) -> None:
        path = write_backup(self.driver, BACKUPS_DIR, self.cfg.backup_retention_days)
        if path is not None:
            self._status.update(last_action=f"backup → {path.name}")

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
            "w": self._do_toggle_wrinklers,
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
        write_save(self.driver, SAVE_FILE)
        self._status.update(last_action="manual save")

    def _do_toggle_wrinklers(self) -> None:
        self._pop_wrinklers = not self._pop_wrinklers
        self._status.update(pop_wrinklers=self._pop_wrinklers)
        state = "ON" if self._pop_wrinklers else "OFF"
        log.info("wrinkler popping %s", state)
        if self._pop_wrinklers:
            # Make the toggle feel responsive: don't wait for the next minigame tick.
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
        self._sched.every(self.cfg.news_period_s, self.news_and_achievements_tick, "news+achievements")
        self._sched.every(self.cfg.minigame_period_s, self.minigame_tick, "minigames")
        self._sched.every(self.cfg.save_period_s, self.save_tick, "save")
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
                write_save(self.driver, SAVE_FILE)
            except Exception:
                log.exception("final save failed")
            self.driver.quit()


def _parse_args() -> tuple[Config, bool]:
    p = argparse.ArgumentParser(description="Cookie Clicker automation bot")
    # ``None`` sentinels let us tell explicit flags apart from defaults so the
    # persisted settings file remains the source of truth unless overridden.
    p.add_argument("--browser", default=None, choices=("firefox", "chrome"))
    p.add_argument("--headless", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--fresh", action="store_true", help="Hard-reset the game on launch")
    p.add_argument("--no-menu", action="store_true", help="Skip the interactive menu")
    args = p.parse_args()

    cfg = Config()
    load_settings(SETTINGS_FILE, cfg)
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
    cfg, no_menu = _parse_args()
    if not no_menu:
        from cookiebot.menu import show_menu
        result = show_menu(cfg)
        if result is None:
            return
        cfg = result
    save_settings(SETTINGS_FILE, cfg)
    bot = CookieBot(cfg, console=console)
    bot.setup()
    bot.run()


if __name__ == "__main__":
    main()
