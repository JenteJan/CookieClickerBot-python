"""Tunable constants and runtime configuration."""
from dataclasses import dataclass
from pathlib import Path

GAME_URL = "https://orteil.dashnet.org/cookieclicker/"
# Saves live in a dedicated gitignored folder next to the package.
PROJECT_DIR = Path(__file__).resolve().parent.parent
SAVES_DIR = PROJECT_DIR / "saves"
# Global settings hold only which profile was last active. All strategy/browser
# config lives per-profile so two instances can run genuinely different setups.
SETTINGS_FILE = SAVES_DIR / "settings.json"

# Each named profile is a self-contained folder so its save, backups, archives,
# and its own settings are grouped together:
#   saves/profiles/<name>/save.txt
#   saves/profiles/<name>/settings.json
#   saves/profiles/<name>/backups/<timestamp>.txt
#   saves/profiles/<name>/archives/<timestamp>.txt
PROFILES_DIR = SAVES_DIR / "profiles"
DEFAULT_PROFILE = "default"

# Pre-reorg locations, kept only for one-time migration into the layout above.
_LEGACY_ROOT_SAVE = PROJECT_DIR / "CookieAISaveData.txt"
_LEGACY_SAVES_SAVE = SAVES_DIR / "CookieAISaveData.txt"
_LEGACY_FLAT_BACKUPS = SAVES_DIR / "backups"
_LEGACY_FLAT_ARCHIVES = SAVES_DIR / "archives"


def profile_dir(name: str) -> Path:
    return PROFILES_DIR / sanitize_profile(name)


def profile_save_file(name: str) -> Path:
    """Path to a named profile's save file."""
    return profile_dir(name) / "save.txt"


def profile_backups_dir(name: str) -> Path:
    return profile_dir(name) / "backups"


def profile_archives_dir(name: str) -> Path:
    return profile_dir(name) / "archives"


def profile_settings_file(name: str) -> Path:
    return profile_dir(name) / "settings.json"


def profile_trials_dir(name: str) -> Path:
    return profile_dir(name) / "trials"


def sanitize_profile(name: str) -> str:
    """Reduce a profile name to a safe folder name. Falls back to the default."""
    cleaned = "".join(c for c in (name or "").strip() if c.isalnum() or c in " -_").strip()
    return cleaned or DEFAULT_PROFILE


OBJECT_NAMES = [
    "Cursor", "Grandma", "Farm", "Mine", "Factory", "Bank", "Temple",
    "Wizard tower", "Shipment", "Alchemy lab", "Portal", "Time machine",
]

# The three "holding" upgrades that make banking cookies for Lucky! worthwhile.
# Identified by NAME, not numeric id — upgrade ids shift between game versions,
# and the old hardcoded [52, 53, 86] pointed at unrelated upgrades, which made
# the bot think all three were owned at run start and bank 100 min immediately.
GOLDEN_COOKIE_UPGRADE_NAMES = ["Lucky day", "Serendipity", "Get lucky"]

AUTOCLICK_COOKIE_MS = 25
AUTOCLICK_GOLDEN_MS = 1000


# Global settings file holds only the pointer to the last-active profile.
GLOBAL_FIELDS = (
    "save_profile",
)

# Everything else is saved per-profile, so each A/B profile keeps its own
# browser choice, strategy flags, reserves, etc.
PROFILE_FIELDS = (
    "browser",
    "headless",
    "backup_interval_hours",
    "backup_retention_days",
    "lucky_reserve_seconds",
    "auto_fire_safe_achievements",
    "auto_fire_risky_achievements",
    "auto_pop_wrinklers_in_frenzy",
    "payback_mode",
    "payback_cap_minutes",
    "auto_ascend",
    "auto_ascend_gain_pct",
    "auto_train_dragon",
    "dragon_keep_buildings",
    "disable_rendering",
    "purchase_period_s",
)

# The strategy variables worth A/B-testing, with their type, for the test menu.
# (name, kind) where kind is "bool", "float", or "int". Browser/headless/backup
# are excluded — they don't affect playstyle.
AB_TESTABLE_FIELDS = (
    ("payback_mode", "bool"),
    ("lucky_reserve_seconds", "float"),
    ("auto_pop_wrinklers_in_frenzy", "bool"),
    ("auto_ascend", "bool"),
    ("auto_ascend_gain_pct", "float"),
    ("auto_train_dragon", "bool"),
    ("achievement_payback_cap_s", "float"),
    ("payback_cap_minutes", "float"),
)


@dataclass
class Config:
    # Active named save profile. The bot loads/saves this profile's file.
    save_profile: str = DEFAULT_PROFILE
    browser: str = "firefox"
    headless: bool = False
    fresh: bool = False  # Hard-reset the game on launch (skips loading the save).
    # Stop the game rendering (Game.visible=false + cosmetic prefs off) to cut
    # CPU. Only the canvas/DOM drawing stops; game logic is unaffected. Applied
    # ONLY when headless (a visible window you're watching is never blanked).
    # This is the big win for batch runs (20 headless browsers rendering for
    # nobody). Set false to keep even headless instances drawing.
    disable_rendering: bool = True
    purchase_period_s: float = 0.05
    lucky_period_s: float = 0.5
    news_period_s: float = 0.5
    minigame_period_s: float = 4.0
    save_period_s: float = 30.0
    marginals_period_s: float = 5.0  # payback-mode upgrade re-evaluation cadence
    ascend_period_s: float = 60.0
    dragon_period_s: float = 30.0
    # Building-count achievements. Only rush one that's within this many
    # buildings of the current count, and only if its milk/CPS gain pays the
    # purchase back within the cap. (Achievements persist across ascension, so
    # already-won ones are skipped automatically.)
    achievement_max_step: int = 50
    achievement_payback_cap_s: float = 1200.0  # 20 min of CPS
    # After unlocking the minigames + Farm L9 / Cursor L12, keep leveling the
    # lowest building toward this level (each level = +1% that building's CpS;
    # L10 also grants an achievement). 0 disables the spread phase.
    sugar_lump_spread_cap: int = 10
    # A/B trial mode. When ab_seed is set, RNG is forced deterministic (same
    # seed for both runs → identical starting luck). When ab_log is True, the
    # bot writes a structured JSONL trial log (snapshots + purchase/buff events)
    # to the profile's folder for offline comparison.
    ab_seed: str = ""
    ab_log: bool = False
    ab_snapshot_period_s: float = 5.0  # how often to log a state snapshot
    # Timestamped backups separate from the main save file. 0 disables backups;
    # retention of 0 days keeps them forever.
    backup_interval_hours: float = 6.0
    backup_retention_days: int = 7
    # Cookies held in reserve (CPS × seconds) once all three holding upgrades
    # (Lucky day / Serendipity / Get lucky) are owned, so Lucky payouts hit the
    # 15-min cap. 6000 s = 100 min, the smallest bank that maxes Lucky.
    # 43200 s = 12 h enables full Cookie Chain payouts as well.
    lucky_reserve_seconds: float = 6000.0
    # One-shot achievement helpers. On by default — every entry is a net
    # positive (the God-complex rename now restores your previous name, so the
    # -1% debuff doesn't stick; selling one grandma trades a few seconds of
    # CPS for a permanent +0.48% milk multiplier). Flip off in the menu if
    # you'd rather earn them organically.
    auto_fire_safe_achievements: bool = True
    auto_fire_risky_achievements: bool = True
    # Hold wrinklers (they accumulate eaten cookies) and pop them only while a
    # CpS-multiplying buff like Frenzy is active, capturing the inflated payout.
    # The 'w' hotkey always pops on demand regardless of this setting.
    auto_pop_wrinklers_in_frenzy: bool = False
    # Experimental payback-time purchase mode (guide §18.3). vs the default
    # value/cost heuristic it adds: (1) the achievement-milk bonus to building
    # buys that cross a count threshold (the default mode only credits upgrades),
    # and (2) an optional payback ceiling — skip purchases slower to pay off than
    # payback_cap_minutes (0 = no cap). Off by default for easy A/B comparison.
    payback_mode: bool = False
    payback_cap_minutes: float = 0.0
    # Auto-ascension. Off by default — ascending is a soft reset. When on, the
    # bot reincarnates once ascending now would raise prestige level by at least
    # auto_ascend_gain_pct (relative to current). Heavenly chips persist unspent.
    auto_ascend: bool = False
    auto_ascend_gain_pct: float = 10.0
    # Krumblor dragon training. Off by default. Middle dragon levels permanently
    # SACRIFICE 100 of a building; the guard only allows such a level when that
    # building's count stays ≥ dragon_keep_buildings after the sacrifice.
    # Requires the "How to bake your dragon" heavenly upgrade.
    auto_train_dragon: bool = False
    dragon_keep_buildings: int = 100
