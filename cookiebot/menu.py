"""Interactive pre-launch menu rendered with rich."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table

from cookiebot import achievements
from cookiebot.config import (
    AB_TESTABLE_FIELDS,
    DEFAULT_PROFILE,
    Config,
    profile_save_file,
    sanitize_profile,
)
from cookiebot.locks import is_locked, lock_owner
from cookiebot.persistence import (
    archive_profile,
    copy_profile_settings,
    create_profile,
    delete_profile,
    list_archives,
    list_profiles,
    load_profile_settings,
    profile_exists,
    restore_archive,
    save_global_settings,
    save_info,
    save_profile_settings,
)

_console = Console()


def _activate_profile(cfg: Config, name: str) -> None:
    """Make ``name`` the active profile: switch pointer, load that profile's own
    settings onto cfg, and persist the global pointer."""
    cfg.save_profile = name
    load_profile_settings(cfg)  # adopt the target profile's strategy/browser
    save_global_settings(cfg)


def show_menu(cfg: Config) -> Config | None:
    """Run the menu loop. Returns the Config to launch with, or None to quit."""
    # Always start by choosing which save profile to play.
    if not _select_profile(cfg):
        return None
    while True:
        _render(cfg)
        choice = Prompt.ask(
            "[bold]Choose[/bold]",
            choices=["1", "2", "3", "4", "5", "6"],
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
            _save_profiles(cfg)
        elif choice == "6":
            return None


def _select_profile(cfg: Config) -> bool:
    """Startup profile picker. Lists existing profiles and lets the user pick one
    or create a new save slot. Sets cfg.save_profile. Returns False to quit."""
    # Guarantee at least the default profile exists to choose from.
    if not list_profiles():
        create_profile(DEFAULT_PROFILE)
    while True:
        profiles = list_profiles()
        _console.print()
        _console.print(Panel.fit("Select a save profile", style="bold yellow"))
        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", justify="right")
        table.add_column("Profile")
        table.add_column("Save")
        table.add_column("Status")
        for i, name in enumerate(profiles, 1):
            owner = lock_owner(name)
            status = f"[yellow]running (pid {owner})[/yellow]" if owner else "[dim]free[/dim]"
            marker = " [green]←[/green]" if name == cfg.save_profile else ""
            table.add_row(str(i), name + marker, save_info(profile_save_file(name)), status)
        _console.print(table)
        _console.print()
        _console.print("  pick a [bold]number[/bold] to play it, "
                       "[bold]n[/bold]) new save slot, [bold]q[/bold]) quit")
        choices = [str(i) for i in range(1, len(profiles) + 1)] + ["n", "q"]
        default = str(profiles.index(cfg.save_profile) + 1) if cfg.save_profile in profiles else "1"
        answer = Prompt.ask("Choose", choices=choices, default=default, show_choices=False)
        if answer == "q":
            return False
        if answer == "n":
            created = _new_profile(cfg)
            if created:
                return True  # _new_profile set cfg.save_profile and we play it
            continue
        _activate_profile(cfg, profiles[int(answer) - 1])
        return True


def _render(cfg: Config) -> None:
    _console.print()
    _console.print(Panel.fit("Cookie Clicker Bot", style="bold yellow"))
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Profile", f"{cfg.save_profile}  ({save_info(profile_save_file(cfg.save_profile))})")
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
    _console.print("  [bold]2[/bold])  New game (archive save, hard-reset in browser)")
    _console.print("  [bold]3[/bold])  Settings")
    _console.print("  [bold]4[/bold])  Bonus achievements")
    _console.print("  [bold]5[/bold])  Save profiles")
    _console.print("  [bold]6[/bold])  Quit")
    _console.print()


def _confirm_new_game(cfg: Config) -> bool:
    if not Confirm.ask(
        f"[red]Start a fresh game on profile '{cfg.save_profile}'? "
        f"Current save will be archived.[/red]",
        default=False,
    ):
        return False
    archived = archive_profile(cfg.save_profile)
    if archived:
        _console.print(f"  archived save → [cyan]{archived.name}[/cyan]")
    else:
        _console.print("  no existing save to archive")
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
    save_profile_settings(cfg)
    _console.print(f"  [dim]settings saved for profile '{cfg.save_profile}'[/dim]")


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


def _save_profiles(cfg: Config) -> None:
    """Manage named save profiles: switch, create, restore, delete."""
    # Make sure the active profile has a file so it shows in the list.
    if not profile_exists(cfg.save_profile):
        create_profile(cfg.save_profile)
    while True:
        _console.print()
        _console.print(Panel.fit("Save profiles", style="bold yellow"))
        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", justify="right")
        table.add_column("Profile")
        table.add_column("Save")
        table.add_column("Status")
        profiles = list_profiles()
        for i, name in enumerate(profiles, 1):
            active = " [green](active)[/green]" if name == cfg.save_profile else ""
            owner = lock_owner(name)
            status = f"[yellow]running (pid {owner})[/yellow]" if owner else "[dim]free[/dim]"
            table.add_row(str(i), name + active, save_info(profile_save_file(name)), status)
        _console.print(table)
        _console.print()
        _console.print("  [bold]s[/bold]) switch   [bold]n[/bold]) new   "
                       "[bold]r[/bold]) restore archive   [bold]d[/bold]) delete   "
                       "[bold]b[/bold]) back")
        action = Prompt.ask("Choose", choices=["s", "n", "r", "d", "b"], default="b")
        if action == "b":
            return
        if action == "s":
            _switch_profile(cfg, profiles)
        elif action == "n":
            _new_profile(cfg)
        elif action == "r":
            _restore_archive(cfg)
        elif action == "d":
            _delete_profile(cfg, profiles)


def _switch_profile(cfg: Config, profiles: list[str]) -> None:
    name = Prompt.ask("Switch to which profile?", choices=profiles, default=cfg.save_profile)
    _activate_profile(cfg, name)
    _console.print(f"  active profile → [green]{name}[/green]")


def _new_profile(cfg: Config) -> bool:
    """Create a new profile. Returns True if it became the active profile."""
    raw = Prompt.ask("New profile name")
    name = sanitize_profile(raw)
    if profile_exists(name):
        _console.print(f"  [red]profile '{name}' already exists[/red]")
        return False
    copy = None
    if cfg.save_profile and profile_exists(cfg.save_profile):
        if Confirm.ask(f"Copy current profile '{cfg.save_profile}' (save + settings) into '{name}'?", default=False):
            copy = cfg.save_profile
    create_profile(name, copy_from=copy)
    if copy:
        copy_profile_settings(copy, name)
    else:
        # Seed the new profile with the current in-memory config as a starting point.
        save_profile_settings(cfg, profile=name)
    _console.print(f"  created [green]{name}[/green]")
    if Confirm.ask(f"Switch to '{name}' now?", default=True):
        _activate_profile(cfg, name)
        return True
    return False


def _restore_archive(cfg: Config) -> None:
    archives = list_archives(cfg.save_profile)
    if not archives:
        _console.print(f"  [dim]no archives for '{cfg.save_profile}'[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Archive")
    table.add_column("Size")
    for i, a in enumerate(archives[:20], 1):
        table.add_row(str(i), a.name, f"{a.stat().st_size:,} B")
    _console.print(table)
    idx = IntPrompt.ask("Restore which # (0 = cancel)", default=0)
    if idx < 1 or idx > len(archives):
        return
    chosen = archives[idx - 1]
    if Confirm.ask(
        f"[red]Overwrite profile '{cfg.save_profile}' with {chosen.name}?[/red]",
        default=False,
    ):
        restore_archive(chosen, cfg.save_profile)
        _console.print(f"  restored [green]{chosen.name}[/green]")


def resolve_locked_profile(cfg: Config, pid: int) -> bool:
    """Called when cfg.save_profile is already running. Let the user branch the
    in-progress save into a new slot (so both can run / be A/B-compared) or pick
    another profile. Updates cfg.save_profile and returns True when resolved to a
    new choice; returns False to cancel the launch."""
    _console.print()
    _console.print(Panel.fit(
        f"Profile '{cfg.save_profile}' is already running (pid {pid})",
        style="bold yellow",
    ))
    _console.print(
        "  [bold]branch[/bold]) copy this save to a new slot and run that "
        "(A/B test from the same point)\n"
        "  [bold]pick[/bold])   choose a different profile\n"
        "  [bold]cancel[/bold]) don't launch"
    )
    action = Prompt.ask("Choose", choices=["branch", "pick", "cancel"], default="branch")
    if action == "cancel":
        return False
    if action == "branch":
        source = cfg.save_profile
        raw = Prompt.ask("Name for the branched profile", default=f"{source}-2")
        name = sanitize_profile(raw)
        if profile_exists(name):
            _console.print(f"  [red]'{name}' already exists; pick another name[/red]")
            return resolve_locked_profile(cfg, pid)
        create_profile(name, copy_from=source)
        copy_profile_settings(source, name)  # branch inherits the same strategy
        _activate_profile(cfg, name)
        _console.print(f"  branched [green]{source}[/green] → [green]{name}[/green]")
        return True
    # pick another existing profile
    free = [p for p in list_profiles() if not is_locked(p)]
    if not free:
        _console.print("  [dim]no free profiles; branch or create one instead[/dim]")
        return resolve_locked_profile(cfg, pid)
    name = Prompt.ask("Switch to which free profile?", choices=free, default=free[0])
    _activate_profile(cfg, name)
    return True


def _delete_profile(cfg: Config, profiles: list[str]) -> None:
    deletable = [p for p in profiles if p != DEFAULT_PROFILE]
    if not deletable:
        _console.print("  [dim]only the default profile exists[/dim]")
        return
    name = Prompt.ask("Delete which profile?", choices=deletable)
    if not Confirm.ask(f"[red]Permanently delete profile '{name}'?[/red]", default=False):
        return
    delete_profile(name)
    if cfg.save_profile == name:
        _activate_profile(cfg, DEFAULT_PROFILE)
    _console.print(f"  deleted [green]{name}[/green]")


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
    save_profile_settings(cfg)
    _console.print(f"  [dim]settings saved for profile '{cfg.save_profile}'[/dim]")


def _pick_source_profile() -> str | None:
    """Choose the single profile whose save both A/B sides will start from."""
    profiles = list_profiles()
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Profile")
    table.add_column("Save")
    for i, name in enumerate(profiles, 1):
        table.add_row(str(i), name, save_info(profile_save_file(name)))
    _console.print(table)
    choices = [str(i) for i in range(1, len(profiles) + 1)]
    ans = Prompt.ask("Source save to clone for BOTH sides", choices=choices, default="1", show_choices=False)
    return profiles[int(ans) - 1]


def _set_one_variable(cfg: Config, field: str, kind: str) -> None:
    """Prompt for a single A/B variable's value and set it on cfg."""
    cur = getattr(cfg, field)
    if kind == "bool":
        setattr(cfg, field, Confirm.ask(f"B: {field}", default=bool(cur)))
    elif kind == "int":
        setattr(cfg, field, IntPrompt.ask(f"B: {field}", default=int(cur)))
    else:
        setattr(cfg, field, FloatPrompt.ask(f"B: {field}", default=float(cur)))


def show_ab_menu() -> tuple[Config, Config] | None:
    """Fair A/B picker: clone ONE source save into two throwaway profiles
    (ab-A / ab-B) so both start byte-identical, give both the SAME settings,
    then change exactly one variable on B. Returns (cfgA, cfgB) or None."""
    from cookiebot.persistence import clone_profile_save

    _console.print()
    _console.print(Panel.fit("A/B test — fair: identical save, one variable", style="bold yellow"))
    if not list_profiles():
        create_profile(DEFAULT_PROFILE)

    source = _pick_source_profile()
    if source is None:
        return None

    seed = Prompt.ask("Shared RNG seed (same for both → identical luck)", default="ab-trial")

    # Throwaway profiles so the source is never touched. Saves cloned identical.
    name_a, name_b = "ab-A", "ab-B"
    for nm in (name_a, name_b):
        create_profile(nm)
        clone_profile_save(source, nm)

    # Base settings: copy the source's settings to BOTH so they're identical,
    # then we'll diverge only one field on B.
    base = Config()
    base.save_profile = source
    load_profile_settings(base)

    def build(name: str) -> Config:
        cfg = Config()
        # adopt the identical base strategy
        for f, _k in AB_TESTABLE_FIELDS:
            setattr(cfg, f, getattr(base, f))
        cfg.payback_mode = base.payback_mode
        cfg.save_profile = name
        cfg.ab_seed = seed
        cfg.ab_log = True
        cfg.headless = False  # the whole point is to watch them
        return cfg

    cfg_a, cfg_b = build(name_a), build(name_b)
    save_profile_settings(cfg_a)  # persist so each temp profile records its config

    # Choose the ONE variable that differs on B.
    _console.print("\nVariable to test (changed on B only; A keeps the base value):")
    for i, (f, _k) in enumerate(AB_TESTABLE_FIELDS, 1):
        _console.print(f"  [bold]{i}[/bold]) {f}  [dim](A = {getattr(cfg_a, f)})[/dim]")
    idx = IntPrompt.ask("Which variable", default=1)
    if idx < 1 or idx > len(AB_TESTABLE_FIELDS):
        return None
    field, kind = AB_TESTABLE_FIELDS[idx - 1]
    _set_one_variable(cfg_b, field, kind)
    save_profile_settings(cfg_b)

    _console.print()
    _console.print(f"source save = [green]{source}[/green] (cloned to both, untouched)")
    _console.print(f"A = ab-A   {field} = [cyan]{getattr(cfg_a, field)}[/cyan]")
    _console.print(f"B = ab-B   {field} = [cyan]{getattr(cfg_b, field)}[/cyan]   (only difference)")
    _console.print(f"seed = [cyan]{seed}[/cyan]")
    if not Confirm.ask("Launch both now?", default=True):
        return None
    return cfg_a, cfg_b
