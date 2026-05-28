"""Main loop: time-based scheduler driving the game."""
from __future__ import annotations

import argparse
import logging
import queue
import time
from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from cookiebot import scripts
from cookiebot.config import (
    GOLDEN_COOKIE_UPGRADE_IDS,
    SAVE_FILE,
    Config,
)
from cookiebot.driver import build_driver, open_game, start_auto_intervals
from cookiebot.heuristics import (
    Building,
    Upgrade,
    building_from_js,
    parse_upgrade_gain,
    score_upgrade,
)
from cookiebot.hotkeys import HotkeyListener
from cookiebot.persistence import load_save, migrate_legacy_save, write_save

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

    def every(self, period_s: float, fn: Callable[[], None], name: str | None = None) -> None:
        self._tasks.append(_Task(name or fn.__name__, period_s, time.monotonic(), fn))

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
        ("?", "show this help"),
    )

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.driver = build_driver(cfg)
        self.upgrades_by_id: dict[int, Upgrade] = {}
        self.golden_count: int = 0
        self._sched = Scheduler()
        self._actions: queue.Queue[Callable[[], None]] = queue.Queue()
        self._quit = False
        self._console = Console()
        self._hotkeys = HotkeyListener(self._enqueue_key)

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
        self.driver.execute_script(scripts.SET_PANTHEON)
        log.info("setup complete; %d golden cookie upgrades owned", self.golden_count)

    def _load_upgrade_catalog(self) -> None:
        raw = self.driver.execute_script(scripts.GET_ALL_UPGRADES)
        for uid, desc, base_price in raw:
            self.upgrades_by_id[int(uid)] = Upgrade(
                id=int(uid),
                gain=parse_upgrade_gain(desc or ""),
                base_price=float(base_price),
            )
        log.info("indexed %d upgrades", len(self.upgrades_by_id))

    # ---- periodic actions --------------------------------------------------

    def purchase_tick(self) -> None:
        snap = self.driver.execute_script(scripts.GAME_SNAPSHOT)
        cookies: float = snap["cookies"]
        cookies_ps: float = snap["cookiesPs"]
        buildings: list[Building] = [building_from_js(b) for b in snap["buildings"]]
        store_ids: list[int] = [int(i) for i in snap["upgradesInStore"]]

        if not buildings:
            return

        if cookies_ps <= 0:
            # Game just started — buy the cheapest building we can afford.
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
        """Once all 3 golden-cookie upgrades are owned, keep a reserve for spell payouts."""
        if self.golden_count != 3:
            return cookies >= price
        reserve = cookies_ps * (100 * self.golden_count)
        if cookies >= reserve + price:
            return True
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

    def _buy_building(self, b: Building) -> None:
        log.info("buy building %s @ %.2f", b.name, b.price)
        self.driver.execute_script(scripts.BUY_BUILDING, b.name, 1)

    def lucky_tick(self) -> None:
        self.driver.execute_script(scripts.GET_LUCKY)

    def news_and_achievements_tick(self) -> None:
        self.driver.execute_script(scripts.CHECK_NEWS_FEED)
        targets = self.driver.execute_script(scripts.CALCULATE_ACHIEVEMENT_BUILDINGS) or []
        for name, qty in targets:
            log.info("buy %d × %s (achievement)", qty, name)
            self.driver.execute_script(scripts.BUY_BUILDING, name, qty)

    def minigame_tick(self) -> None:
        self.driver.execute_script(scripts.FARM_SUGAR_LUMPS)
        self.driver.execute_script(scripts.BUY_PLEDGE)
        self.driver.execute_script(scripts.PLANT_CLOVERS)
        self.driver.execute_script(scripts.CHECK_STOCK_MARKET)
        self.driver.execute_script(scripts.SET_PANTHEON)

    def save_tick(self) -> None:
        self.driver.execute_script(scripts.SPEND_SUGAR_LUMPS)
        write_save(self.driver, SAVE_FILE)

    # ---- main loop --------------------------------------------------------

    # ---- hotkey plumbing ---------------------------------------------------

    def _enqueue_key(self, key: str) -> None:
        """Called on the listener thread. Defer the actual work to the main loop."""
        handler = {
            "q": self._do_quit,
            "p": self._do_toggle_pause,
            "s": self._do_save_now,
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
        log.info("paused" if self._sched.paused else "resumed")

    def _do_save_now(self) -> None:
        log.info("manual save")
        write_save(self.driver, SAVE_FILE)

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
        self._print_hotkey_panel()
        hotkeys_active = self._hotkeys.start()
        if not hotkeys_active:
            log.info("hotkeys unavailable (not a TTY); use ctrl-c to stop")
        try:
            while not self._quit:
                self._drain_actions()
                sleep_for = self._sched.tick()
                if sleep_for > 0:
                    time.sleep(min(sleep_for, 0.25))
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
    p.add_argument("--browser", default="firefox", choices=("firefox", "chrome"))
    p.add_argument("--headless", action="store_true")
    p.add_argument("--fresh", action="store_true", help="Hard-reset the game on launch")
    p.add_argument("--no-menu", action="store_true", help="Skip the interactive menu")
    args = p.parse_args()
    cfg = Config(browser=args.browser, headless=args.headless, fresh=args.fresh)
    return cfg, args.no_menu


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg, no_menu = _parse_args()
    if not no_menu:
        from cookiebot.menu import show_menu
        result = show_menu(cfg)
        if result is None:
            return
        cfg = result
    bot = CookieBot(cfg)
    bot.setup()
    bot.run()


if __name__ == "__main__":
    main()
