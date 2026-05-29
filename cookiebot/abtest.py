"""Synchronized A/B test orchestrator.

Spawns two bots (separate browser windows, not headless), loads both games
fully, then starts them at the same instant so they run on identical luck from
t=0. The picker clones ONE source save into two throwaway profiles and gives
both identical settings except a single variable, so the run isolates that one
change. Drives both from one loop with a shared side-by-side dashboard and
shared hotkeys, and writes a trial log for each (compare with compare_trials.py).
"""
from __future__ import annotations

import copy
import logging
import time

from rich.columns import Columns
from rich.console import Console
from rich.live import Live

from cookiebot.config import Config
from cookiebot.hotkeys import HotkeyListener
from cookiebot.runner import CookieBot
from cookiebot.status import render as render_status

log = logging.getLogger("cookiebot.abtest")


class ABTest:
    def __init__(self, cfg_a: Config, cfg_b: Config, console: Console | None = None) -> None:
        self.cfg_a = cfg_a
        self.cfg_b = cfg_b
        self.console = console or Console()
        self._quit = False
        self._bots: list[CookieBot] = []
        self._hotkeys = HotkeyListener(self._on_key)

    def _on_key(self, key: str) -> None:
        if key in ("q", "\x03"):
            self._quit = True
        elif key == "?" or key == "h":
            # Defer printing to the main thread isn't necessary here; the Live
            # display owns the screen, so just log it.
            log.info("hotkeys: q = quit both")

    def run(self) -> None:
        # Build both bots (separate windows). Each gets its own browser session.
        bot_a = CookieBot(self.cfg_a, console=self.console)
        bot_b = CookieBot(self.cfg_b, console=self.console)
        self._bots = [bot_a, bot_b]

        log.info("A/B: preparing both games (no auto-click yet)…")
        # Prepare both WITHOUT starting the auto-clicker, so neither earns
        # cookies until both are fully loaded.
        for bot in self._bots:
            bot.setup(start_intervals=False)
            bot._schedule()

        log.info("A/B: both ready — starting simultaneously")
        # Fire both auto-clickers as close together as possible.
        for bot in self._bots:
            bot.begin_play()

        hotkeys_active = self._hotkeys.start()
        if not hotkeys_active:
            log.info("hotkeys unavailable (not a TTY); ctrl-c to stop both")

        try:
            with Live(self._render(), console=self.console, refresh_per_second=4, screen=False) as live:
                last_render = 0.0
                while not self._quit and not any(b.quit_requested for b in self._bots):
                    sleeps = [bot.tick_once() for bot in self._bots]
                    now = time.monotonic()
                    if now - last_render >= 0.25:
                        live.update(self._render())
                        last_render = now
                    sleep_for = min(sleeps) if sleeps else 0.1
                    if sleep_for > 0:
                        time.sleep(min(sleep_for, 0.1))
        except KeyboardInterrupt:
            log.info("stopping both on user request")
        finally:
            self._hotkeys.stop()
            for bot in self._bots:
                try:
                    bot.shutdown()
                except Exception:
                    log.exception("shutdown failed for %s", bot.cfg.save_profile)

    def _render(self) -> Columns:
        panels = []
        for bot in self._bots:
            p = render_status(bot.status)
            p.title = f"{bot.cfg.save_profile}"
            panels.append(p)
        return Columns(panels, equal=True, expand=True)


def ab_main() -> None:
    """Entry point: interactive A/B picker, then run both synchronized."""
    import logging as _logging
    from rich.logging import RichHandler

    from cookiebot.menu import show_ab_menu
    from cookiebot.persistence import migrate_legacy_save

    console = Console()
    _logging.basicConfig(
        level=_logging.INFO, format="%(message)s", datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )
    migrate_legacy_save()
    picked = show_ab_menu()
    if picked is None:
        return
    cfg_a, cfg_b = picked
    ABTest(cfg_a, cfg_b, console=console).run()
