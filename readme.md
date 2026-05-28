# Cookie Clicker Bot

This script automates the game [Cookie Clicker](https://orteil.dashnet.org/cookieclicker/) using Selenium WebDriver. It performs various actions in the game to maximize cookie production even when while away.

## Prerequisites

- Python 3.9+
- Firefox (default) or Chrome
- `geckodriver` (for Firefox) or `chromedriver` (for Chrome) on your PATH

## Setup

1. Clone the repository and enter it:
    ```sh
    git clone <repository_url>
    cd CookieClickerBot-python
    ```

2. Create a virtualenv and install dependencies:
    ```sh
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

3. Install a browser driver (macOS examples):
    ```sh
    brew install geckodriver        # Firefox
    brew install --cask chromedriver # Chrome
    ```

## Usage

```sh
python cookieBot.py                  # Firefox
python cookieBot.py --browser chrome # Chrome
python cookieBot.py --headless       # No window
```

Press `Ctrl-C` to stop; the bot will write a final save before quitting.

## Save files

The bot reads and writes `CookieAISaveData.txt` next to `cookieBot.py`. To import an existing save, export it from the game and paste the contents into that file before starting the bot. Restart the bot after editing the file or after prestiging.

## Project layout

```
cookieBot.py               # entry point
cookiebot/
    config.py              # tunables (browser, periods, golden cookie ids)
    driver.py              # Firefox/Chrome setup + page bootstrap
    scripts.py             # all JavaScript executed in the page
    heuristics.py          # upgrade-description parser + scoring
    persistence.py         # save-file read/write
    runner.py              # time-based scheduler + main loop
```

## What the bot does

- **Auto-clicks the big cookie** via a JS `setInterval` (no Python round-trip per click).
- **Pops every shimmer** (golden cookie, reindeer, etc.) the moment it appears.
- **Buys buildings and upgrades** using a CPS-per-cost heuristic, with a cookie reserve once the holding upgrades (52 / 53 / 86) are owned so spell payouts stay maxed.
- **Bulk-buys buildings** approaching achievement thresholds (1, 15, 50, … 1000) when the cost is under 10 s of CPS.
- **Casts Conjure Baked Goods** during frenzy stacks; sells temples and takes bank loans when an extra-juicy combo lands.
- **Manages minigames**: clovers in the garden, sugar lump harvest + spend, pantheon slotting (Mokalsium / Dotjeiess / Selebrak), buy-low/sell-high on the stock market.
- **Saves periodically** to `CookieAISaveData.txt`.

## Is this cheating?

This is obviously not the way the game was meant to be played, but the game was intentionally designed so users can make use of commands in the command line, even allowing you to set your cookies to any number you want.
This bot was intended to only do things so you don't have to, not to do things you couldn't do yourself. Using this bot will **not** get you the [cheated cookies](https://cookieclicker.fandom.com/wiki/Cheating#:~:text=to%20decimal%20converter-,%22Cheated%20cookies%20taste%20awful%22%20Achievement,adjusted%20depending%20on%20the%20CpS.) shadow achievement.
