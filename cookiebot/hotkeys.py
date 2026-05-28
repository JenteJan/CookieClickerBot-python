"""Non-blocking single-key input from the terminal (macOS / Linux)."""
from __future__ import annotations

import select
import sys
import termios
import threading
import tty
from typing import Callable


class HotkeyListener:
    """Background thread that delivers individual keystrokes to ``on_key``.

    Puts the terminal in cbreak mode so keys are delivered without Enter.
    ``stop()`` restores the original terminal settings; calling it from a
    ``finally:`` block is required, otherwise the user's shell is left in
    cbreak after the bot exits.
    """

    def __init__(self, on_key: Callable[[str], None]) -> None:
        self._on_key = on_key
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._original_attrs: list | None = None

    def start(self) -> bool:
        if not sys.stdin.isatty():
            return False
        try:
            self._original_attrs = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, ValueError):
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hotkeys")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._original_attrs is not None:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._original_attrs)
            except (termios.error, ValueError):
                pass
            self._original_attrs = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            except (OSError, ValueError):
                continue
            if not ready:
                continue
            try:
                ch = sys.stdin.read(1)
            except (OSError, ValueError):
                continue
            if ch:
                self._on_key(ch.lower())
