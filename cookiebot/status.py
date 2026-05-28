"""Live status state + panel rendering for the bottom of the terminal."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


_SUFFIXES: list[tuple[float, str]] = [
    (1e3, "K"), (1e6, "M"), (1e9, "B"), (1e12, "T"),
    (1e15, "Qa"), (1e18, "Qi"), (1e21, "Sx"), (1e24, "Sp"),
    (1e27, "Oc"), (1e30, "No"), (1e33, "Dc"),
]


def format_number(n: float) -> str:
    if not n:
        return "0"
    if abs(n) < 1e6:
        return f"{n:,.0f}"
    for threshold, suffix in reversed(_SUFFIXES):
        if abs(n) >= threshold:
            return f"{n / threshold:.3f} {suffix}"
    return f"{n:.3e}"


def format_duration(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # negative or NaN
        return "--:--:--"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class BotStatus:
    started_at: float = field(default_factory=time.monotonic)
    cookies: float = 0.0
    cookies_ps: float = 0.0
    golden_count: int = 0
    paused: bool = False
    last_action: str = "(starting up)"

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


_HOTKEY_HINT = (
    "[bold cyan]q[/]uit   "
    "[bold cyan]p[/]ause   "
    "[bold cyan]s[/]ave   "
    "[bold cyan]?[/] help"
)


def render(status: BotStatus) -> Panel:
    uptime = format_duration(time.monotonic() - status.started_at)
    state = "[yellow]paused[/]" if status.paused else "[green]running[/]"
    banked_s = status.cookies / status.cookies_ps if status.cookies_ps > 0 else 0.0

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()
    grid.add_row("status", state)
    grid.add_row("uptime", uptime)
    grid.add_row("cookies", format_number(status.cookies))
    grid.add_row("per second", f"{format_number(status.cookies_ps)} /s")
    grid.add_row("banked", format_duration(banked_s))
    grid.add_row("golden upgrades", f"{status.golden_count}/3")
    grid.add_row("last action", status.last_action)

    body = Group(grid, Text(), Text.from_markup(_HOTKEY_HINT, justify="center"))
    return Panel(body, title="Cookie Clicker Bot", border_style="yellow", expand=False)
