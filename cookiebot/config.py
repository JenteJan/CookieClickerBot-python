"""Tunable constants and runtime configuration."""
from dataclasses import dataclass
from pathlib import Path

GAME_URL = "https://orteil.dashnet.org/cookieclicker/"
# Saves live in a dedicated gitignored folder next to the package.
PROJECT_DIR = Path(__file__).resolve().parent.parent
SAVES_DIR = PROJECT_DIR / "saves"
SAVE_FILE = SAVES_DIR / "CookieAISaveData.txt"
LEGACY_SAVE_FILE = PROJECT_DIR / "CookieAISaveData.txt"

OBJECT_NAMES = [
    "Cursor", "Grandma", "Farm", "Mine", "Factory", "Bank", "Temple",
    "Wizard tower", "Shipment", "Alchemy lab", "Portal", "Time machine",
]

GOLDEN_COOKIE_UPGRADE_IDS = [52, 53, 86]

AUTOCLICK_COOKIE_MS = 25
AUTOCLICK_GOLDEN_MS = 1000


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
