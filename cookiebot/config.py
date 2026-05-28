"""Tunable constants and runtime configuration."""
from dataclasses import dataclass
from pathlib import Path

GAME_URL = "https://orteil.dashnet.org/cookieclicker/"
# Saves live in a dedicated gitignored folder next to the package.
PROJECT_DIR = Path(__file__).resolve().parent.parent
SAVES_DIR = PROJECT_DIR / "saves"
SAVE_FILE = SAVES_DIR / "CookieAISaveData.txt"
LEGACY_SAVE_FILE = PROJECT_DIR / "CookieAISaveData.txt"
BACKUPS_DIR = SAVES_DIR / "backups"
SETTINGS_FILE = SAVES_DIR / "settings.json"

OBJECT_NAMES = [
    "Cursor", "Grandma", "Farm", "Mine", "Factory", "Bank", "Temple",
    "Wizard tower", "Shipment", "Alchemy lab", "Portal", "Time machine",
]

GOLDEN_COOKIE_UPGRADE_IDS = [52, 53, 86]

AUTOCLICK_COOKIE_MS = 25
AUTOCLICK_GOLDEN_MS = 1000


PERSISTABLE_FIELDS = (
    "browser",
    "headless",
    "backup_interval_hours",
    "backup_retention_days",
    "lucky_reserve_seconds",
    "auto_fire_safe_achievements",
    "auto_fire_risky_achievements",
)


@dataclass
class Config:
    browser: str = "firefox"
    headless: bool = False
    fresh: bool = False  # Hard-reset the game on launch (skips loading the save).
    purchase_period_s: float = 0.05
    lucky_period_s: float = 0.5
    news_period_s: float = 0.5
    minigame_period_s: float = 4.0
    save_period_s: float = 30.0
    # Timestamped backups separate from the main save file. 0 disables backups;
    # retention of 0 days keeps them forever.
    backup_interval_hours: float = 6.0
    backup_retention_days: int = 7
    # Cookies held in reserve (CPS × seconds) once all three holding upgrades
    # (Lucky day / Serendipity / Get lucky) are owned, so Lucky payouts hit the
    # 15-min cap. 6000 s = 100 min, the smallest bank that maxes Lucky.
    # 43200 s = 12 h enables full Cookie Chain payouts as well.
    lucky_reserve_seconds: float = 6000.0
    # One-shot achievement helpers. Safe = no in-game cost. Risky has a
    # permanent CPS or save side effect — opt in via the menu.
    auto_fire_safe_achievements: bool = False
    auto_fire_risky_achievements: bool = False
