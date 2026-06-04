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


# Curated dragon-aura presets, so you pick a number instead of typing exact names.
# (slot1,slot2 — order is cosmetic; both auras are active at once.)
_AURA_PRESETS = [
    ("Radiant Appetite,Dragonflight",
     "Radiant Appetite + Dragonflight — click combo (best with the autoclicker)"),
    ("Radiant Appetite,Ancestral Metamorphosis",
     "Radiant Appetite + Ancestral Metamorphosis — bigger golden-cookie payouts"),
    ("Radiant Appetite,Dragon's Fortune",
     "Radiant Appetite + Dragon's Fortune — only if goldens are left on screen"),
    ("Radiant Appetite,Breath of Milk",
     "Radiant Appetite + Breath of Milk — idle / passive CpS"),
]


def _pick_dragon_auras(cfg: Config) -> None:
    _console.print()
    for i, (_combo, desc) in enumerate(_AURA_PRESETS, 1):
        _console.print(f"    [bold]{i}[/bold]) {desc}")
    custom = len(_AURA_PRESETS) + 1
    _console.print(f"    [bold]{custom}[/bold]) Custom — type two aura names")
    cur = cfg.dragon_aura_combo
    default = next((str(i) for i, (c, _) in enumerate(_AURA_PRESETS, 1) if c == cur), str(custom))
    ans = Prompt.ask("Pick auras", choices=[str(i) for i in range(1, custom + 1)],
                     default=default, show_choices=False)
    if int(ans) == custom:
        cfg.dragon_aura_combo = Prompt.ask("Two aura names, comma-separated", default=cur).strip()
    else:
        cfg.dragon_aura_combo = _AURA_PRESETS[int(ans) - 1][0]


def _bool_entry(label: str, attr: str, prompt: str):
    return (
        label,
        lambda c: "[green]on[/green]" if getattr(c, attr) else "[dim]off[/dim]",
        lambda c: setattr(c, attr, Confirm.ask(prompt, default=getattr(c, attr))),
    )


def _reserve_edit(c: Config) -> None:
    c.lucky_reserve_seconds = max(0.0, FloatPrompt.ask(
        "Lucky reserve in minutes of CPS (100 = max Lucky, 720 = max Chain)",
        default=c.lucky_reserve_seconds / 60)) * 60


def _settings_entries() -> list:
    """Each entry: (label, show(cfg)->str, edit(cfg)). Edited individually so you
    change one thing without walking the whole wizard."""
    return [
        ("Browser", lambda c: c.browser,
         lambda c: setattr(c, "browser", Prompt.ask("Browser", choices=["firefox", "chrome"], default=c.browser))),
        _bool_entry("Headless", "headless", "Run headless?"),
        ("Backup interval", lambda c: _format_interval(c.backup_interval_hours),
         lambda c: setattr(c, "backup_interval_hours", max(0.0, FloatPrompt.ask("Backup every how many hours? (0 = off)", default=c.backup_interval_hours)))),
        ("Backup retention", lambda c: _format_retention(c.backup_retention_days),
         lambda c: setattr(c, "backup_retention_days", max(0, IntPrompt.ask("Keep backups how many days? (0 = forever)", default=c.backup_retention_days)))),
        ("Lucky reserve", lambda c: f"{c.lucky_reserve_seconds / 60:g} min of CPS", _reserve_edit),
        ("Wrinkler strategy", lambda c: c.wrinkler_strategy,
         lambda c: setattr(c, "wrinkler_strategy", Prompt.ask(
             "Wrinklers (hold = manual 'w'; pop-when-full = reclaim at max slots; "
             "always = pop continuously). Pops before ascend + farms Halloween either way",
             choices=["hold", "pop-when-full", "always"], default=c.wrinkler_strategy))),
        _bool_entry("Payback purchase mode", "payback_mode", "Use experimental payback-time purchase mode?"),
        ("Payback cap", lambda c: f"{c.payback_cap_minutes:g} min" if c.payback_cap_minutes else "[dim]no cap[/dim]",
         lambda c: setattr(c, "payback_cap_minutes", max(0.0, FloatPrompt.ask("Skip buys slower to pay off than how many minutes? (0 = no cap)", default=c.payback_cap_minutes)))),
        _bool_entry("Auto-ascend", "auto_ascend", "Auto-ascend (soft reset) when worthwhile?"),
        ("Ascend gain %", lambda c: f"{c.auto_ascend_gain_pct:g}%",
         lambda c: setattr(c, "auto_ascend_gain_pct", max(0.0, FloatPrompt.ask("Ascend when prestige would grow by at least what %?", default=c.auto_ascend_gain_pct)))),
        _bool_entry("Auto-train Krumblor", "auto_train_dragon", "Auto-train Krumblor? (some levels sacrifice buildings)"),
        ("Dragon: keep buildings", lambda c: str(c.dragon_keep_buildings),
         lambda c: setattr(c, "dragon_keep_buildings", max(0, IntPrompt.ask("Keep at least how many of a building after a sacrifice?", default=c.dragon_keep_buildings)))),
        ("Dragon: sacrifice bank fraction", lambda c: f"{c.dragon_sacrifice_bank_fraction:g}",
         lambda c: setattr(c, "dragon_sacrifice_bank_fraction", max(0.0, FloatPrompt.ask("Take a sacrifice level only when rebuy costs <= what fraction of the bank? (0 = always)", default=c.dragon_sacrifice_bank_fraction)))),
        _bool_entry("Auto-equip dragon auras", "auto_dragon_auras", "Auto-equip dragon auras once Krumblor is trained?"),
        ("Dragon auras", lambda c: c.dragon_aura_combo, _pick_dragon_auras),
        _bool_entry("Auto-play seasons/holidays", "auto_seasons",
                    "Auto-play seasons/holidays? (enter a season, collect upgrades, level Santa, cycle — needs 'Season switcher')"),
        _bool_entry("Auto-play garden", "auto_garden", "Auto-play the garden? (breed seeds, then steady-state layout)"),
        ("Garden strategy", lambda c: c.garden_strategy,
         lambda c: setattr(c, "garden_strategy", Prompt.ask("Garden strategy (cps/golden/juicy)", choices=["cps", "golden", "juicy"], default=c.garden_strategy))),
        _bool_entry("Garden: breed soil (Wood chips)", "garden_breed_soil", "Use Wood chips soil while breeding? (faster mutations)"),
    ]


def _edit_settings(cfg: Config) -> None:
    entries = _settings_entries()
    while True:
        _console.print()
        _console.print(Panel.fit("Settings — pick a number to change, d) done", style="bold yellow"))
        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", justify="right")
        table.add_column("Setting")
        table.add_column("Value", style="cyan")
        for i, (label, show, _edit) in enumerate(entries, 1):
            table.add_row(str(i), label, show(cfg))
        _console.print(table)
        ans = Prompt.ask("Choose", choices=[str(i) for i in range(1, len(entries) + 1)] + ["d"],
                         default="d", show_choices=False)
        if ans == "d":
            break
        entries[int(ans) - 1][2](cfg)
        save_profile_settings(cfg)  # persist after each change so nothing is lost
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
    """Choose what both A/B sides start from: a fresh game, or a profile's save.
    Returns "" for a fresh game, a profile name to clone, or None to cancel."""
    profiles = list_profiles()
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Start from")
    table.add_column("Save")
    table.add_row("f", "[green]fresh game[/green] (both reset, empty save)", "")
    for i, name in enumerate(profiles, 1):
        table.add_row(str(i), name, save_info(profile_save_file(name)))
    _console.print(table)
    choices = ["f"] + [str(i) for i in range(1, len(profiles) + 1)]
    ans = Prompt.ask("Both sides start from", choices=choices, default="f", show_choices=False)
    if ans == "f":
        return ""  # fresh game
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
    fresh = (source == "")

    seed = Prompt.ask("Shared RNG seed (same for both → identical luck)", default="ab-trial")

    # Throwaway profiles so the source is never touched. Either clone the source
    # save into both, or start both from an empty save + hard reset (fresh).
    name_a, name_b = "ab-A", "ab-B"
    for nm in (name_a, name_b):
        create_profile(nm)
        if fresh:
            clone_profile_save("", nm)  # empty save
        else:
            clone_profile_save(source, nm)

    # Base settings: from the source profile, or defaults for a fresh game.
    base = Config()
    if not fresh:
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
        cfg.fresh = fresh     # hard-reset both at launch when starting fresh
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
    if fresh:
        _console.print("start = [green]fresh game[/green] (both hard-reset at launch)")
    else:
        _console.print(f"source save = [green]{source}[/green] (cloned to both, untouched)")
    _console.print(f"A = ab-A   {field} = [cyan]{getattr(cfg_a, field)}[/cyan]")
    _console.print(f"B = ab-B   {field} = [cyan]{getattr(cfg_b, field)}[/cyan]   (only difference)")
    _console.print(f"seed = [cyan]{seed}[/cyan]")
    if not Confirm.ask("Launch both now?", default=True):
        return None
    return cfg_a, cfg_b


def show_batch_menu() -> dict | None:
    """Picker for a batch A/B: N headless runs per group, independent luck,
    aggregated live. Forces the two groups to differ in exactly one variable.
    Returns a dict the batch runner consumes, or None to cancel."""
    _console.print()
    _console.print(Panel.fit("Batch A/B — N headless runs per group, averaged", style="bold yellow"))
    if not list_profiles():
        create_profile(DEFAULT_PROFILE)

    source = _pick_source_profile()
    if source is None:
        return None
    fresh = (source == "")

    n = IntPrompt.ask("How many runs per group (A and B each)?", default=10)
    n = max(1, n)

    base = Config()
    if not fresh:
        base.save_profile = source
        load_profile_settings(base)

    # Choose the variable and BOTH explicit values, so they're guaranteed to
    # differ (the old picker defaulted B to A's value → a silent no-op test).
    _console.print("\nVariable to A/B (groups differ ONLY in this):")
    for i, (f, _k) in enumerate(AB_TESTABLE_FIELDS, 1):
        _console.print(f"  [bold]{i}[/bold]) {f}  [dim](base = {getattr(base, f)})[/dim]")
    idx = IntPrompt.ask("Which variable", default=1)
    if idx < 1 or idx > len(AB_TESTABLE_FIELDS):
        return None
    field, kind = AB_TESTABLE_FIELDS[idx - 1]

    _console.print(f"\nSet the two values for [cyan]{field}[/cyan]:")
    val_a = _prompt_value("Group A value", kind, getattr(base, field))
    val_b = _prompt_value("Group B value", kind, _other_default(kind, val_a))
    if val_a == val_b:
        _console.print("[red]A and B values are identical — that's not a test. Aborting.[/red]")
        return None

    def build(value) -> Config:
        cfg = Config(**{k: getattr(base, k) for (k, _kk) in AB_TESTABLE_FIELDS})
        setattr(cfg, field, value)
        return cfg

    cfg_a, cfg_b = build(val_a), build(val_b)
    _console.print()
    _console.print(f"A: {field} = [cyan]{val_a}[/cyan]   ×{n} runs")
    _console.print(f"B: {field} = [cyan]{val_b}[/cyan]   ×{n} runs")
    _console.print(f"start = {'fresh game' if fresh else source}   (headless, independent luck)")
    if not Confirm.ask(f"Launch {2 * n} headless instances now?", default=True):
        return None
    return {
        "cfg_a": cfg_a, "cfg_b": cfg_b, "n": n,
        "source": source, "fresh": fresh, "variable": field,
    }


def _prompt_value(label: str, kind: str, default):
    if kind == "bool":
        return Confirm.ask(label, default=bool(default))
    if kind == "int":
        return IntPrompt.ask(label, default=int(default))
    return FloatPrompt.ask(label, default=float(default))


def _other_default(kind: str, val_a):
    """A sensible different default for group B so the two aren't identical."""
    if kind == "bool":
        return not val_a
    return val_a  # numeric: user must change it; equality check catches no-ops
