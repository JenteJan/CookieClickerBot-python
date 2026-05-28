"""Save-game persistence helpers."""
from __future__ import annotations

import datetime as _dt
import logging
import os
import tempfile
from pathlib import Path

from cookiebot import scripts

log = logging.getLogger(__name__)


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
    log.info("saved game to %s (%d bytes)", path.name, len(data))


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
