"""Interactive pre-launch menu rendered with rich."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table

from cookiebot import achievements
from cookiebot.config import SAVE_FILE, SETTINGS_FILE, Config
from cookiebot.persistence import backup_save, save_info, save_settings

_console = Console()


def show_menu(cfg: Config) -> Config | None:
    """Run the menu loop. Returns the Config to launch with, or None to quit."""
    while True:
        _render(cfg)
        choice = Prompt.ask(
            "[bold]Choose[/bold]",
            choices=["1", "2", "3", "4", "5"],
            default="1",
            show_choices=False,
        )
        if choice == "1":
            return cfg
        if choice == "2":
            if _confirm_new_game(cfg):
                return cfg
        elif choice == "3":
            _edit_settings(cfg)
        elif choice == "4":
            _bonus_achievements(cfg)
        elif choice == "5":
            return None


def _render(cfg: Config) -> None:
    _console.print()
    _console.print(Panel.fit("Cookie Clicker Bot", style="bold yellow"))
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Save file", save_info(SAVE_FILE))
    table.add_row("Browser", cfg.browser)
    table.add_row("Headless", "yes" if cfg.headless else "no")
    table.add_row("Start mode", "[red]fresh game[/red]" if cfg.fresh else "continue save")
    table.add_row("Backup interval", _format_interval(cfg.backup_interval_hours))
    table.add_row("Backup retention", _format_retention(cfg.backup_retention_days))
    table.add_row("Lucky reserve", f"{cfg.lucky_reserve_seconds / 60:g} min of CPS")
    table.add_row("Auto achievements", _format_auto_achievements(cfg))
    _console.print(table)
    _console.print()
    _console.print("  [bold]1[/bold])  Start")
    _console.print("  [bold]2[/bold])  New game (back up save, hard-reset in browser)")
    _console.print("  [bold]3[/bold])  Settings")
    _console.print("  [bold]4[/bold])  Bonus achievements")
    _console.print("  [bold]5[/bold])  Quit")
    _console.print()


def _confirm_new_game(cfg: Config) -> bool:
    if not Confirm.ask(
        "[red]Start a fresh game? Current save will be backed up.[/red]",
        default=False,
    ):
        return False
    backup = backup_save(SAVE_FILE)
    if backup:
        _console.print(f"  backed up save → [cyan]{backup.name}[/cyan]")
    else:
        _console.print("  no existing save to back up")
    cfg.fresh = True
    return True


def _edit_settings(cfg: Config) -> None:
    cfg.browser = Prompt.ask(
        "Browser", choices=["firefox", "chrome"], default=cfg.browser
    )
    cfg.headless = Confirm.ask("Run headless?", default=cfg.headless)
    interval = FloatPrompt.ask(
        "Backup every how many hours? (0 = disabled)",
        default=cfg.backup_interval_hours,
    )
    cfg.backup_interval_hours = max(0.0, interval)
    retention = IntPrompt.ask(
        "Keep backups for how many days? (0 = keep forever)",
        default=cfg.backup_retention_days,
    )
    cfg.backup_retention_days = max(0, retention)
    reserve_min = FloatPrompt.ask(
        "Lucky cookie reserve in minutes of CPS (100 = max Lucky, 720 = max Cookie Chain)",
        default=cfg.lucky_reserve_seconds / 60,
    )
    cfg.lucky_reserve_seconds = max(0.0, reserve_min) * 60
    cfg.auto_pop_wrinklers_in_frenzy = Confirm.ask(
        "Auto-pop wrinklers during Frenzy? (otherwise hold; 'w' pops manually)",
        default=cfg.auto_pop_wrinklers_in_frenzy,
    )
    cfg.payback_mode = Confirm.ask(
        "Use experimental payback-time purchase mode?",
        default=cfg.payback_mode,
    )
    if cfg.payback_mode:
        cap = FloatPrompt.ask(
            "Skip purchases slower to pay off than how many minutes? (0 = no cap)",
            default=cfg.payback_cap_minutes,
        )
        cfg.payback_cap_minutes = max(0.0, cap)
    cfg.auto_ascend = Confirm.ask(
        "Auto-ascend (soft reset) when worthwhile?",
        default=cfg.auto_ascend,
    )
    if cfg.auto_ascend:
        pct = FloatPrompt.ask(
            "Ascend when prestige would grow by at least what %?",
            default=cfg.auto_ascend_gain_pct,
        )
        cfg.auto_ascend_gain_pct = max(0.0, pct)
    cfg.auto_train_dragon = Confirm.ask(
        "Auto-train Krumblor? (some levels sacrifice 100 buildings)",
        default=cfg.auto_train_dragon,
    )
    if cfg.auto_train_dragon:
        keep = IntPrompt.ask(
            "Keep at least how many of a building after a sacrifice?",
            default=cfg.dragon_keep_buildings,
        )
        cfg.dragon_keep_buildings = max(0, keep)
    save_settings(SETTINGS_FILE, cfg)
    _console.print("  [dim]settings saved[/dim]")


def _format_interval(hours: float) -> str:
    if hours <= 0:
        return "[dim]disabled[/dim]"
    if hours < 1:
        return f"every {hours * 60:g} min"
    return f"every {hours:g} h"


def _format_retention(days: int) -> str:
    if days <= 0:
        return "forever"
    return f"{days} day{'s' if days != 1 else ''}"


def _format_auto_achievements(cfg: Config) -> str:
    parts = []
    if cfg.auto_fire_safe_achievements:
        parts.append("safe")
    if cfg.auto_fire_risky_achievements:
        parts.append("[red]risky[/red]")
    return ", ".join(parts) if parts else "[dim]off[/dim]"


def _bonus_achievements(cfg: Config) -> None:
    """Show the achievement catalog and toggle auto-fire flags."""
    _console.print()
    _console.print(Panel.fit("Bonus achievements", style="bold yellow"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Group", style="dim")
    table.add_column("Name")
    table.add_column("Note")
    for item in achievements.SAFE:
        table.add_row("safe", item.name, item.note)
    for item in achievements.RISKY:
        label = "[red]shadow[/red]" if item.shadow else "[red]risky[/red]"
        table.add_row(label, item.name, item.note)
    _console.print(table)
    _console.print()
    _console.print(
        "Safe entries have no in-game cost — visual changes are fine. "
        "Risky entries have a permanent CPS or save side effect."
    )
    _console.print(
        "Already-unlocked entries are skipped automatically, so "
        "enabling these is idempotent across launches."
    )
    _console.print()

    cfg.auto_fire_safe_achievements = Confirm.ask(
        "Auto-fire [green]safe[/green] achievements on next start?",
        default=cfg.auto_fire_safe_achievements,
    )
    cfg.auto_fire_risky_achievements = Confirm.ask(
        "Auto-fire [red]risky[/red] achievements on next start?",
        default=cfg.auto_fire_risky_achievements,
    )
    save_settings(SETTINGS_FILE, cfg)
    _console.print("  [dim]settings saved[/dim]")
