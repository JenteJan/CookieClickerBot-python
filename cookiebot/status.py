"""Live status state + panel rendering for the bottom of the terminal."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Tuple

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _build_short_suffixes() -> list[str]:
    """Cookie Clicker's own 'short' suffix table (main.js formatShort): index i maps
    to magnitude 10**(3*(i+1)) — M, B, T, Qa, Qi, Sx, Sp, Oc, No, Dc, then UnD, DoD …
    up through the prefix×suffix grid. Covers every magnitude the game can reach
    (~1e300) so huge CpS/cookie values abbreviate instead of printing in full."""
    short = ["k", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No"]
    prefixes = ["", "Un", "Do", "Tr", "Qa", "Qi", "Sx", "Sp", "Oc", "No"]
    suffixes = ["D", "V", "T", "Qa", "Qi", "Sx", "Sp", "O", "N"]
    for suf in suffixes:
        for pre in prefixes:
            short.append(pre + suf)
    short[10] = "Dc"  # the game overrides ' D' → 'Dc' (decillion)
    return short


_SHORT_SUFFIXES = _build_short_suffixes()


def format_number(n: float) -> str:
    """Abbreviate like Cookie Clicker's short notation: 1.234 M, 56.7 OcD, etc.
    Numbers under a million print in full; anything past the suffix table (≈1e300)
    falls back to scientific so it can never print a giant mantissa."""
    if not n:
        return "0"
    a = abs(n)
    if a < 1e6:
        return f"{n:,.0f}"
    sign = "-" if n < 0 else ""
    val = a / 1000.0
    base = 0
    while round(val) >= 1000 and base < len(_SHORT_SUFFIXES) - 1:
        val /= 1000.0
        base += 1
    if round(val) >= 1000:  # ran off the end of the (huge) table
        return f"{sign}{a:.3e}"
    return f"{sign}{val:.3f} {_SHORT_SUFFIXES[base]}"


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
    achievements_owned: int = 0
    paused: bool = False
    # Wrinkler tactic + live attached state.
    wrinkler_strategy: str = "pop-when-full"
    wrinkler_count: int = 0
    wrinkler_max: int = 0
    wrinkler_sucked: float = 0.0
    wrinkler_shiny: int = 0
    last_action: str = "(starting up)"
    # Top heuristic candidates: (label, score, affordable_now)
    next_buys: List[Tuple[str, float, bool]] = field(default_factory=list)
    # Cookie reserve we're banking toward (CPS-seconds). 0 = no reserve (buy freely).
    reserve_target_s: float = 0.0
    # ---- side quests / minigames (shown only when active) ----
    # Current holiday season ('' = none) and per-season collection progress
    # {season: {owned, total}} from the season tick, plus Santa's level.
    season: str = ""
    season_counts: dict = field(default_factory=dict)
    santa_level: int = -1
    santa_max: int = 0
    # Krumblor: current level / max and the equipped aura names.
    dragon_level: int = -1
    dragon_max: int = 0
    dragon_auras: List[str] = field(default_factory=list)
    # Garden minigame: short live summary ('' = not playing).
    garden_summary: str = ""
    # Heavenly/prestige tree progress.
    heavenly_chips: float = 0.0
    heavenly_owned: int = 0
    heavenly_total: int = 0
    # Golden-cookie combo state: live CpS multiplier, active buff count, Grimoire magic.
    combo_mult: float = 1.0
    combo_buffs: int = 0
    magic: float | None = None
    magic_max: float | None = None
    combo_buff_names: List[str] = field(default_factory=list)
    # Click buffs (Dragonflight / Click frenzy) — multiply click power, not CpS.
    click_mult: float = 1.0
    click_buffs: List[str] = field(default_factory=list)

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


_HOTKEY_HINT = (
    "[bold cyan]q[/]uit   "
    "[bold cyan]p[/]ause   "
    "[bold cyan]s[/]ave   "
    "[bold cyan]w[/]rinklers   "
    "[bold cyan]?[/] help"
)


def _format_reserve_target(status: BotStatus) -> str:
    if status.reserve_target_s <= 0:
        return "[dim]none[/]"
    minutes = status.reserve_target_s / 60
    # Highlight green once we've actually banked the target.
    banked_s = status.cookies / status.cookies_ps if status.cookies_ps > 0 else 0.0
    reached = banked_s >= status.reserve_target_s
    label = f"{minutes:g} min"
    return f"[green]{label} ✓[/]" if reached else label


def _format_next_buys(next_buys: List[Tuple[str, float, bool]]) -> str:
    if not next_buys:
        return "[dim]—[/]"
    # Normalize to the top candidate so the best buy always reads 1 and the rest
    # show as a fraction of it. Keeps the display stable under Frenzy/buff CPS
    # swings (those scale every score equally, so the ratios are unchanged).
    base = next_buys[0][1] or 1.0
    lines = []
    for i, (label, score, affordable) in enumerate(next_buys, 1):
        # #1 is the bot's actual target — highlight blue. Lower ranks: green if
        # affordable right now, dim if still saving up.
        if i == 1:
            style = "bold blue"
        else:
            style = "green" if affordable else "dim"
        ratio = score / base if base else 0.0
        # \[ escapes a literal bracket so rich doesn't read it as a markup tag.
        lines.append(f"[{style}]{i}. {label} \\[{ratio:.3g}][/]")
    return "\n".join(lines)


# Holiday display order + short labels. Christmas also shows Santa's level.
_HOLIDAYS = [
    ("christmas", "Xmas"), ("valentines", "Valentine"),
    ("halloween", "Halloween"), ("easter", "Easter"),
]


def _holiday_done(status: BotStatus, key: str, c: dict) -> bool:
    owned, total = c.get("owned", 0), c.get("total", 0)
    if total <= 0 or owned < total:
        return False
    if key == "christmas" and status.santa_max and status.santa_level < status.santa_max:
        return False
    return True


def _format_holidays(status: BotStatus) -> str:
    """One line per holiday with collection progress; current season highlighted,
    finished ones green, the rest dim."""
    lines = []
    for key, label in _HOLIDAYS:
        c = status.season_counts.get(key)
        if not c:
            continue
        seg = f"{label} {c.get('owned', 0)}/{c.get('total', 0)}"
        if key == "christmas" and status.santa_max > 0:
            seg += f"  santa {max(status.santa_level, 0)}/{status.santa_max}"
        if key == status.season:
            seg = f"[bold blue]▶ {seg}[/]  [dim](here)[/]"
        elif _holiday_done(status, key, c):
            seg = f"[green]✓ {seg}[/]"
        else:
            seg = f"[dim]  {seg}[/]"
        lines.append(seg)
    return "\n".join(lines) if lines else "[dim]—[/]"


def _format_wrinklers(status: BotStatus) -> str:
    """Strategy + attached count / max, plus stored cookies and any shiny."""
    cap = f"/{status.wrinkler_max}" if status.wrinkler_max else ""
    parts = [f"{status.wrinkler_strategy}", f"{status.wrinkler_count}{cap} attached"]
    if status.wrinkler_sucked > 0:
        parts.append(f"{format_number(status.wrinkler_sucked)} stored")
    if status.wrinkler_shiny:
        parts.append(f"[bold magenta]{status.wrinkler_shiny} shiny![/]")
    return " · ".join(parts)


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
    grid.add_row("target bank", _format_reserve_target(status))
    grid.add_row("golden upgrades", f"{status.golden_count}/3")
    grid.add_row("achievements", f"{status.achievements_owned}")
    grid.add_row("wrinklers", _format_wrinklers(status))
    grid.add_row("last action", status.last_action)
    grid.add_row("next buys", _format_next_buys(status.next_buys))

    # Side quests / minigames — only rendered when there's something to show.
    if status.season_counts:
        grid.add_row("", "")  # spacer
        grid.add_row("holidays", _format_holidays(status))
    if status.dragon_level >= 0:
        auras = ", ".join(status.dragon_auras) if status.dragon_auras else "[dim]none[/]"
        maxed = status.dragon_max and status.dragon_level >= status.dragon_max
        lvl = f"L{status.dragon_level}/{status.dragon_max}"
        lvl = f"[green]{lvl}[/]" if maxed else lvl
        grid.add_row("dragon", f"{lvl} · {auras}")
    if status.garden_summary:
        grid.add_row("garden", status.garden_summary)
    if status.heavenly_total:
        chips = f"{format_number(status.heavenly_chips)} chips" if status.heavenly_chips else "0 chips"
        grid.add_row("heavenly", f"{status.heavenly_owned}/{status.heavenly_total} upgrades · {chips}")
    if status.magic is not None or status.combo_mult > 1.01 or status.click_mult > 1.01:
        mult = f"[bold green]×{status.combo_mult:.1f}[/]" if status.combo_mult > 1.01 else "×1"
        if status.combo_buff_names:
            names = ", ".join(status.combo_buff_names)
            parts = [f"{mult} CpS ({names})"]
        else:
            parts = [f"{mult} CpS"]
        if status.click_mult > 1.01:
            label = ", ".join(status.click_buffs) or "click"
            parts.append(f"[bold magenta]×{status.click_mult:.0f} click ({label})[/]")
        if status.magic is not None:
            parts.append(f"magic {format_number(status.magic)}/{format_number(status.magic_max or 0)}")
        grid.add_row("combo", " · ".join(parts))

    body = Group(grid, Text(), Text.from_markup(_HOTKEY_HINT, justify="center"))
    return Panel(body, title="Cookie Clicker Bot", border_style="yellow", expand=False)
