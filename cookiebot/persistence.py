"""Save-game persistence helpers."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import tempfile
import time
from dataclasses import fields
from pathlib import Path

from cookiebot import scripts
from cookiebot.config import (
    LEGACY_SAVE_FILE,
    PERSISTABLE_FIELDS,
    SAVE_FILE,
    SAVES_DIR,
    Config,
)

log = logging.getLogger(__name__)

_BACKUP_GLOB = "CookieAISaveData_*.txt"
_BACKUP_TS_FMT = "%Y-%m-%d_%H%M%S"


def migrate_legacy_save() -> None:
    """One-time move of a pre-existing root-level save into ``saves/``."""
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_SAVE_FILE.exists() and not SAVE_FILE.exists():
        os.replace(LEGACY_SAVE_FILE, SAVE_FILE)
        log.info("migrated %s → %s", LEGACY_SAVE_FILE.name, SAVE_FILE.relative_to(SAVES_DIR.parent))


def load_save(driver, path: Path) -> bool:
    """Load save data into the game. Returns True if a save was applied."""
    if not path.exists():
        return False
    data = path.read_text().strip()
    if not data:
        return False
    driver.execute_script(scripts.LOAD_SAVE_DATA, data)
    log.info("loaded save from %s (%d bytes)", path, len(data))
    return True


def write_save(driver, path: Path) -> None:
    """Write the current game state to ``path`` atomically."""
    data = driver.execute_script(scripts.GET_SAVE_DATA)
    if not data:
        log.warning("Game.WriteSave returned empty; skipping write")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # Debug-level: the routine 30s autosave fires constantly. Manual saves (the
    # 's' hotkey) and backups still log at INFO from their own call sites.
    log.debug("saved game to %s (%d bytes)", path.name, len(data))


def backup_save(path: Path) -> Path | None:
    """Rename the current save to ``<name>.bak``. Returns the backup path or None."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    backup = path.with_name(path.name + ".bak")
    os.replace(path, backup)
    return backup


def save_info(path: Path) -> str:
    """One-line summary of the save file's current state."""
    if not path.exists():
        return "no save file yet"
    size = path.stat().st_size
    if size == 0:
        return "save file is empty"
    mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"{size:,} bytes, modified {mtime}"


# ---- timestamped backups --------------------------------------------------


def write_backup(driver, backups_dir: Path, retention_days: int) -> Path | None:
    """Snapshot the current game state to ``backups_dir`` and prune old files."""
    data = driver.execute_script(scripts.GET_SAVE_DATA)
    if not data:
        log.warning("Game.WriteSave returned empty; skipping backup")
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime(_BACKUP_TS_FMT)
    path = backups_dir / f"CookieAISaveData_{ts}.txt"
    path.write_text(data)
    log.info("backup written → %s (%d bytes)", path.name, len(data))
    pruned = prune_backups(backups_dir, retention_days)
    if pruned:
        log.info("pruned %d old backup(s)", pruned)
    return path


def prune_backups(backups_dir: Path, retention_days: int) -> int:
    """Delete backup files older than ``retention_days``. Returns the count removed."""
    if retention_days <= 0 or not backups_dir.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    count = 0
    for f in backups_dir.glob(_BACKUP_GLOB):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        except OSError:
            log.exception("failed to remove %s", f)
    return count


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.exists():
        return []
    return sorted(backups_dir.glob(_BACKUP_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)


# ---- persistent user settings --------------------------------------------


def load_settings(path: Path, cfg: Config) -> Config:
    """Apply any persisted values onto ``cfg`` in place. Missing or invalid file is silently ignored."""
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text() or "{}")
    except (json.JSONDecodeError, OSError):
        log.warning("could not read settings from %s; using defaults", path)
        return cfg
    known = {f.name for f in fields(cfg)}
    for k in PERSISTABLE_FIELDS:
        if k in data and k in known:
            setattr(cfg, k, data[k])
    return cfg


def save_settings(path: Path, cfg: Config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: getattr(cfg, k) for k in PERSISTABLE_FIELDS}
    path.write_text(json.dumps(data, indent=2) + "\n")
