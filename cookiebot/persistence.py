"""Save-game persistence helpers."""
from __future__ import annotations

import logging
from pathlib import Path

from cookiebot import scripts

log = logging.getLogger(__name__)


def load_save(driver, path: Path) -> None:
    if not path.exists():
        path.write_text("")
        return
    data = path.read_text().strip()
    if not data:
        return
    driver.execute_script(scripts.LOAD_SAVE_DATA, data)
    log.info("loaded save data from %s", path)


def write_save(driver, path: Path) -> None:
    data = driver.execute_script(scripts.GET_SAVE_DATA)
    if not data:
        return
    path.write_text(data)
    log.info("saved game to %s", path)
