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

# Upgrades the bot must never auto-buy: the Golden switch and Shimmering veil
# (flat passive CpS in exchange for breaking golden-cookie / clicking play, a bad
# deal for THIS bot) and the cosmetic selectors (milk / background / sound). They
# aren't real upgrades — they toggle a mode — yet both scoring paths rank them at
# the top (the parser sees "golden cookie"/"+%", the payback path sees the flat
# CpS as a huge true marginal). The game tags every one of them with a non-empty
# `pool` ('toggle'/'switch'), and every toggle's store name carries an [off]/[on]
# marker — we exclude on BOTH signals so a single quirk can't let one slip through.
NEVER_BUY_UPGRADE_POOLS = frozenset({"toggle", "switch"})
# Belt-and-suspenders name match (pool-independent), case-insensitive.
NEVER_BUY_UPGRADE_PREFIXES = ("golden switch", "shimmering veil")


def is_never_buy_upgrade(name: str, pool: str = "") -> bool:
    """True if an upgrade should never be auto-purchased — identified by its
    pool (toggle/switch) or by its name (an [off]/[on] toggle marker, or a known
    prefix). Either signal is sufficient."""
    if (pool or "").strip().lower() in NEVER_BUY_UPGRADE_POOLS:
        return True
    n = (name or "").strip().lower()
    if "[off]" in n or "[on]" in n:
        return True
    return any(n.startswith(p) for p in NEVER_BUY_UPGRADE_PREFIXES)

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
    "bulk_buy",
    "bulk_max_buys",
    "bulk_cheap_fraction",
    "auto_ascend",
    "auto_ascend_gain_pct",
    "auto_train_dragon",
    "dragon_keep_buildings",
    "dragon_sacrifice_bank_fraction",
    "auto_dragon_auras",
    "dragon_aura_combo",
    "auto_seasons",
    "season_period_s",
    "season_max_dwell_s",
    "disable_rendering",
    "purchase_period_s",
    "auto_garden",
    "garden_strategy",
    "garden_breed_soil",
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
    ("auto_garden", "bool"),
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
    dragon_period_s: float = 10.0
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
    # Batch sync barrier (runtime only, not persisted). When set, the bot drops
    # a "ready" marker here after loading and waits for the orchestrator's shared
    # start signal, so all instances begin playing at the same instant.
    barrier_dir: str = ""
    # Timestamped backups separate from the main save file. 0 disables backups;
    # retention of 0 days keeps them forever.
    backup_interval_hours: float = 6.0
    backup_retention_days: int = 7
    # Cookies held in reserve (CPS × seconds) once all three holding upgrades
    # (Lucky day / Serendipity / Get lucky) are owned, so Lucky payouts hit the
    # 15-min cap. 6000 s = 100 min, the smallest bank that maxes Lucky.
    # 43200 s = 12 h enables full Cookie Chain payouts as well.
    lucky_reserve_seconds: float = 6000.0
    # Dynamic, EV-driven reserve. When on, the bot computes the marginal value
    # of banking one more cookie (0.15 / golden-cookie spawn interval, via Lucky)
    # and only reserves while that beats the best available purchase — up to the
    # Lucky cap (which rises ~7x during a Frenzy and with "Get lucky"). Replaces
    # the fixed lucky_reserve_seconds bank when enabled. Off by default.
    dynamic_golden_reserve: bool = False
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
    # Bulk-buy drain. The purchase tick normally buys a single item per 50 ms.
    # Right after an ascension the prestige multiplier floods cookies in while
    # hundreds of buildings/upgrades are all trivially cheap no-brainers, so the
    # one-per-tick pace wastes minutes trickling them out over Selenium. When on,
    # a tick keeps buying the best-scored affordable item — reusing the same
    # scoring + golden-reserve checks, simulated locally with no extra round
    # trips — until nothing worthwhile is affordable, then fires the whole batch
    # in ONE browser call. Steady-state ticks still buy 0-1 items (you can rarely
    # afford two worthwhile buys inside 50 ms), so this only "kicks in" when you
    # have a surplus — exactly the post-ascension catch-up. bulk_max_buys caps a
    # single tick's batch so one tick can't run away.
    bulk_buy: bool = True
    bulk_max_buys: int = 250
    # Accuracy guard for the drain. The first buy each tick is always scored from
    # the live snapshot (exact). Every *later* buy in the same tick is only batched
    # when it costs at most this fraction of the remaining bank — i.e. pocket
    # change the simulated-model drift can't misjudge. The moment the best item is
    # pricier than this (a real "save up for it" decision), the drain stops and
    # lets the next tick re-snapshot and score it exactly. 0.02 = only fast-path
    # buys you could afford 50× over. Lower = stricter/more accurate, slower
    # catch-up; raise toward 1.0 to batch more aggressively. 0 = one buy per tick.
    bulk_cheap_fraction: float = 0.02
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
    # Krumblor is best leveled ASAP (its cost only rises), so the dragon tick now
    # trains as many levels as are affordable+safe in one go. A building-sacrifice
    # level is only taken when rebuying the whole sacrifice costs at most this
    # fraction of the current bank — so it fires freely when you're cookie-rich
    # (your case) and holds when buying the buildings back would actually hurt.
    # 0 disables the cost gate (rely on dragon_keep_buildings alone).
    dragon_sacrifice_bank_fraction: float = 0.25
    # Auto-equip the golden-cookie-combo dragon auras once Krumblor is fully
    # trained (the only state with a second aura slot and every aura unlocked).
    # dragon_aura_combo is an ordered, comma-separated list: the first name goes in
    # slot 1, the second in slot 2. Default is the click-combo meta — Radiant
    # Appetite (×2 production) + Dragon's Fortune (+CpS per golden cookie on
    # screen). Setting auras is free and reversible, so this is on by default; it
    # no-ops until the dragon is maxed and only re-sets when the equipped auras
    # differ. Polled on dragon_period_s (the dragon tick runs if either this or
    # auto_train_dragon is on).
    auto_dragon_auras: bool = True
    # Slot1,slot2 aura names. Default suits an insta-pop + autoclick bot: Radiant
    # Appetite (×2 everything, always on) + Dragonflight (clicking-oriented, good
    # when the cookie is being autoclicked). Dragon's Fortune is intentionally NOT
    # the default — it only pays off with golden cookies left ON SCREEN, which
    # insta-popping never does. Swap to "Radiant Appetite,Ancestral Metamorphosis"
    # to favour golden-cookie payouts instead.
    dragon_aura_combo: str = "Radiant Appetite,Dragonflight"
    # Auto-play seasons/holidays. Off by default — it spends cookies to switch and
    # needs the 'Season switcher' heavenly upgrade. When on, the bot enters a
    # season, grabs that season's upgrades cheapest-first (fastest CpS per cookie),
    # levels Santa to max during Christmas (→ Santa's dominion), then cycles to the
    # next incomplete season. Seasonal spending keeps the same golden-cookie
    # reserve as normal buys.
    auto_seasons: bool = False
    season_period_s: float = 15.0
    # A season is normally held until every one of its collectibles is obtained
    # (instant for Valentine's hearts, RNG for Halloween/Easter/Christmas drops),
    # so we don't pay the switch-biscuit cost re-entering. This is a safety escape:
    # if no new collectible has dropped in this many seconds AND another season is
    # still incomplete, move on to make progress there (and cycle back later).
    season_max_dwell_s: float = 1800.0
    # Garden minigame player. Off by default — when off, the bot keeps its old
    # behavior (clover-spam every empty plot). When on, it runs a two-phase
    # player: first BREED the seed log up to the chosen strategy's plants
    # (mutation-favoring Wood chips soil), then fill the grid with a steady-state
    # layout. The seed log is NEVER auto-sacrificed (M.convert is never called).
    auto_garden: bool = False
    # Steady-state layout once the strategy's plants are unlocked:
    #   "cps"    — Queenbeet/Elderwort passive CpS boost (immortal, low micro).
    #   "golden" — Shimmerlily/Golden clover for golden-cookie frequency.
    #   "juicy"  — experimental Juicy Queenbeet farming (big cookie bursts).
    garden_strategy: str = "cps"
    # During the breeding phase, switch soil to Wood chips (favors mutations).
    # Respects the 10-min soil cooldown. Off keeps soil on dirt (slower unlocks).
    garden_breed_soil: bool = True
