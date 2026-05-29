"""Save-game persistence helpers."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import fields
from pathlib import Path

from cookiebot import scripts
from cookiebot.config import (
    DEFAULT_PROFILE,
    PERSISTABLE_FIELDS,
    PROFILES_DIR,
    SAVES_DIR,
    Config,
    _LEGACY_FLAT_ARCHIVES,
    _LEGACY_FLAT_BACKUPS,
    _LEGACY_ROOT_SAVE,
    _LEGACY_SAVES_SAVE,
    profile_archives_dir,
    profile_backups_dir,
    profile_dir,
    profile_save_file,
    sanitize_profile,
)

log = logging.getLogger(__name__)

_BACKUP_GLOB = "*.txt"
_BACKUP_TS_FMT = "%Y-%m-%d_%H%M%S"


def migrate_legacy_save() -> None:
    """One-time moves of pre-existing saves into the per-profile folder layout.

    Handles every prior layout the bot has shipped:
      1. root CookieAISaveData.txt  → saves/CookieAISaveData.txt
      2. saves/CookieAISaveData.txt → profiles/default/save.txt
      3. flat profiles/<name>.txt   → profiles/<name>/save.txt
      4. flat saves/backups/*       → profiles/default/backups/*
      5. flat saves/archives/<p>_*  → profiles/<p>/archives/*
    """
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    # 1: legacy root file into saves/
    if _LEGACY_ROOT_SAVE.exists() and not _LEGACY_SAVES_SAVE.exists():
        os.replace(_LEGACY_ROOT_SAVE, _LEGACY_SAVES_SAVE)
        log.info("migrated root save → %s", _LEGACY_SAVES_SAVE.name)

    # 2: single saves/ file into the default profile folder
    default_save = profile_save_file(DEFAULT_PROFILE)
    if _LEGACY_SAVES_SAVE.exists() and not default_save.exists():
        default_save.parent.mkdir(parents=True, exist_ok=True)
        os.replace(_LEGACY_SAVES_SAVE, default_save)
        log.info("migrated save → profile %r", DEFAULT_PROFILE)

    # 3: flat per-profile files (profiles/<name>.txt) into folders
    for flat in PROFILES_DIR.glob("*.txt"):
        dest = profile_save_file(flat.stem)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(flat, dest)
            log.info("migrated flat profile %r → folder", flat.stem)

    # 4: old global backups belong to the only pre-profiles save: default
    if _LEGACY_FLAT_BACKUPS.is_dir():
        dest_dir = profile_backups_dir(DEFAULT_PROFILE)
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in _LEGACY_FLAT_BACKUPS.glob("*.txt"):
            target = dest_dir / f.name
            if not target.exists():
                os.replace(f, target)
        _rmdir_if_empty(_LEGACY_FLAT_BACKUPS)
        log.info("migrated global backups → profile %r", DEFAULT_PROFILE)

    # 5: old archives named "<profile>_<ts>.txt" into each profile's folder
    if _LEGACY_FLAT_ARCHIVES.is_dir():
        for f in _LEGACY_FLAT_ARCHIVES.glob("*.txt"):
            prof, _, rest = f.stem.partition("_")
            target_dir = profile_archives_dir(prof if rest else DEFAULT_PROFILE)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / ((rest or f.stem) + ".txt")
            if not target.exists():
                os.replace(f, target)
        _rmdir_if_empty(_LEGACY_FLAT_ARCHIVES)
        log.info("migrated archives → per-profile folders")


def _rmdir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass  # not empty or already gone — leave it


# ---- named save profiles --------------------------------------------------


def list_profiles() -> list[str]:
    """Names of existing profiles (folders), alphabetical, default first."""
    if not PROFILES_DIR.exists():
        return []
    names = sorted(p.name for p in PROFILES_DIR.iterdir() if p.is_dir())
    if DEFAULT_PROFILE in names:
        names.remove(DEFAULT_PROFILE)
        names.insert(0, DEFAULT_PROFILE)
    return names


def profile_exists(name: str) -> bool:
    return profile_dir(name).is_dir()


def create_profile(name: str, copy_from: str | None = None) -> str:
    """Create a profile folder with a save file (empty, or copied from another).
    Returns the sanitized name actually used."""
    name = sanitize_profile(name)
    dest = profile_save_file(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return name
    if copy_from and profile_exists(copy_from):
        dest.write_text(profile_save_file(copy_from).read_text())
    else:
        dest.write_text("")
    log.info("created profile %r%s", name, f" from {copy_from!r}" if copy_from else "")
    return name


def delete_profile(name: str) -> bool:
    """Delete a profile's whole folder (save + backups + archives). The default
    profile cannot be deleted."""
    name = sanitize_profile(name)
    if name == DEFAULT_PROFILE:
        return False
    path = profile_dir(name)
    if path.is_dir():
        shutil.rmtree(path)
        log.info("deleted profile %r", name)
        return True
    return False


def archive_profile(name: str) -> Path | None:
    """Copy a profile's current save to a timestamped archive in its own folder.
    Returns the path, or None if there's nothing to archive."""
    src = profile_save_file(name)
    if not src.exists() or src.stat().st_size == 0:
        return None
    dest_dir = profile_archives_dir(name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime(_BACKUP_TS_FMT)
    dest = dest_dir / f"{ts}.txt"
    dest.write_text(src.read_text())
    log.info("archived profile %r → %s", name, dest.name)
    return dest


def list_archives(name: str) -> list[Path]:
    """A profile's archived saves, newest first."""
    d = profile_archives_dir(name)
    if not d.exists():
        return []
    return sorted(d.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)


def restore_archive(archive: Path, profile: str) -> None:
    """Overwrite a profile's save with an archived copy."""
    dest = profile_save_file(profile)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(archive.read_text())
    log.info("restored %s → profile %r", archive.name, profile)


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
    path = backups_dir / f"{ts}.txt"
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
