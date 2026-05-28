"""Interactive pre-launch menu rendered with rich."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table

from cookiebot.config import SAVE_FILE, SETTINGS_FILE, Config
from cookiebot.persistence import backup_save, save_info, save_settings

_console = Console()


def show_menu(cfg: Config) -> Config | None:
    """Run the menu loop. Returns the Config to launch with, or None to quit."""
    while True:
        _render(cfg)
        choice = Prompt.ask(
            "[bold]Choose[/bold]",
            choices=["1", "2", "3", "4"],
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
    _console.print(table)
    _console.print()
    _console.print("  [bold]1[/bold])  Start")
    _console.print("  [bold]2[/bold])  New game (back up save, hard-reset in browser)")
    _console.print("  [bold]3[/bold])  Settings")
    _console.print("  [bold]4[/bold])  Quit")
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
