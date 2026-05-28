# Cookie Clicker Bot

Automates [Cookie Clicker](https://orteil.dashnet.org/cookieclicker/) with Selenium so you can AFK the game and still collect golden cookies, buy upgrades, and chain spell combos.

## Requirements

- Python 3.9+
- Firefox **or** Chrome (your choice)
- The matching browser driver on your `PATH`

## Install

```sh
git clone <repository_url>
cd CookieClickerBot-python

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then install **one** browser driver:

| Browser | Driver        | macOS install                       |
|---------|---------------|-------------------------------------|
| Firefox | `geckodriver` | `brew install geckodriver`          |
| Chrome  | `chromedriver`| `brew install --cask chromedriver`  |

## Run

```sh
python cookieBot.py                    # opens the interactive menu
python cookieBot.py --no-menu          # skip the menu, use CLI flags only
python cookieBot.py --browser chrome   # Chrome
python cookieBot.py --headless         # no window
python cookieBot.py --fresh            # hard-reset the game on launch
```

The default menu lets you continue your save, start a fresh game (backs the
save up to `CookieAISaveData.txt.bak`), change browser / headless settings,
or quit. `Ctrl-C` stops the bot and writes a final save.

## Save files

The bot reads and writes `CookieAISaveData.txt` next to `cookieBot.py`. To import an existing save, export it from the game and paste its contents into that file before starting. Restart the bot after editing the save or after prestiging.

## What it does

- **Auto-clicks** the big cookie and every shimmer (golden cookies, reindeer, etc.) via in-page JS intervals.
- **Buys buildings and upgrades** by CPS-per-cost, keeping a cookie reserve once the holding upgrades (52 / 53 / 86) are owned.
- **Bulk-buys** buildings approaching achievement thresholds when they cost under 10 s of CPS.
- **Casts Conjure Baked Goods** on frenzy stacks; sells temples and takes bank loans on extra-juicy combos.
- **Runs minigames**: garden clovers, sugar lump harvest + spend, pantheon slotting, buy-low/sell-high on the stock market.
- **Saves periodically** to `CookieAISaveData.txt`.

## Project layout

```
cookieBot.py               # entry point
cookiebot/
    config.py              # tunables (periods, golden cookie ids)
    driver.py              # browser setup + page bootstrap
    scripts.py             # JavaScript executed in the page
    heuristics.py          # upgrade-description parser + scoring
    persistence.py         # save-file read/write (atomic, backup)
    menu.py                # interactive pre-launch menu
    runner.py              # scheduler + main loop
```

## Is this cheating?

Not the way the game was meant to be played, but the game was intentionally designed so users can run commands from the JavaScript console — you can even set your cookie count to any number you want. This bot only does things you could already do yourself, so it will **not** trigger the [cheated cookies](https://cookieclicker.fandom.com/wiki/Cheating) shadow achievement.
