"""Browser driver setup."""
from __future__ import annotations

import time
from selenium import webdriver

from cookiebot import scripts
from cookiebot.config import (
    AUTOCLICK_COOKIE_MS,
    AUTOCLICK_GOLDEN_MS,
    GAME_URL,
    Config,
)


def build_driver(cfg: Config) -> webdriver.Remote:
    browser = cfg.browser.lower()
    if browser == "firefox":
        opts = webdriver.FirefoxOptions()
        # -no-remote isolates this instance from a Firefox already running
        # under the user's default profile (otherwise the new process exits
        # immediately with "Process unexpectedly closed with status 0").
        opts.add_argument("-no-remote")
        if cfg.headless:
            opts.add_argument("-headless")
        return webdriver.Firefox(options=opts)
    if browser == "chrome":
        opts = webdriver.ChromeOptions()
        if cfg.headless:
            opts.add_argument("--headless=new")
        return webdriver.Chrome(options=opts)
    raise ValueError(f"Unsupported browser: {cfg.browser!r}")


def open_game(driver: webdriver.Remote) -> None:
    driver.get(GAME_URL)
    _wait_for_game(driver)
    driver.execute_script(scripts.CLOSE_PROMPT)


def _wait_for_game(driver: webdriver.Remote, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if driver.execute_script(scripts.WAIT_FOR_GAME_READY):
            return
        time.sleep(0.25)
    raise RuntimeError("Cookie Clicker did not finish loading in time")


def start_auto_intervals(driver: webdriver.Remote) -> None:
    driver.execute_script(scripts.START_AUTOCLICK_COOKIE, AUTOCLICK_COOKIE_MS)
    driver.execute_script(scripts.START_AUTOCLICK_GOLDEN, AUTOCLICK_GOLDEN_MS)
