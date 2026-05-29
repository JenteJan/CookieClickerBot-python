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
```

Install **one** browser driver:

| Browser | Driver        | macOS install                       |
|---------|---------------|-------------------------------------|
| Firefox | `geckodriver` | `brew install geckodriver`          |
| Chrome  | `chromedriver`| `brew install --cask chromedriver`  |

The Python virtualenv and dependencies are set up automatically by `run.sh`
on first launch. To do it manually instead:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

The easiest way — `run.sh` creates the venv, installs deps (only when
`requirements.txt` changes), and launches the bot. Works from any directory
and passes arguments through:

```sh
./run.sh                       # opens the interactive menu
./run.sh --no-menu --headless  # skip menu, no window
./run.sh --profile experiment  # use a named save profile
```

Or call the module directly if you manage the venv yourself:

```sh
python cookieBot.py                    # opens the interactive menu
python cookieBot.py --no-menu          # skip the menu, use CLI flags only
python cookieBot.py --browser chrome   # Chrome
python cookieBot.py --headless         # no window
python cookieBot.py --fresh            # hard-reset the game on launch
python cookieBot.py --profile <name>   # select a named save profile
```

The default menu lets you continue your save, start a fresh game (backs the
save up to `saves/CookieAISaveData.txt.bak`), change browser / headless
settings, or quit.

### Runtime hotkeys

While the bot is running, single-key shortcuts work without pressing Enter:

| Key | Action                                |
|-----|---------------------------------------|
| `q` | Quit (saves first)                    |
| `p` | Pause / resume Python-driven actions  |
| `s` | Save now                              |
| `?` | Re-print this list                    |

Pause only stops the Python-driven purchases, spell casts, and minigame
ticks. The in-page auto-clicker and golden-cookie popper keep running
(they're JavaScript intervals). `Ctrl-C` also quits cleanly.

## Save files

Each save is a named **profile** stored at `saves/profiles/<name>.txt`
(gitignored). The bot loads and saves the active profile; the default is
`default`. To import an existing save, export it from the game and paste its
contents into the profile file before starting. Restart the bot after editing
a save or after prestiging.

### Profiles (A/B testing)

The menu's **Save profiles** screen lets you create, switch, restore, and
delete named profiles. Use `--profile <name>` to pick one from the CLI. To
compare two strategies side by side, run two instances with different
profiles and browsers:

```sh
python cookieBot.py --profile aggressive --no-menu
python cookieBot.py --profile conservative --browser chrome --no-menu
```

Each profile can only be run by one instance at a time — a lock file
(`saves/profiles/<name>.lock` holding the owning PID) prevents two instances
from writing the same save and clobbering each other. If you launch a second
instance on a profile that's already running, the menu offers to **branch** it
(copy the in-progress save into a new slot so you can A/B test from the same
point) or pick another free profile; with `--no-menu` it explains and exits.
Locks from crashed processes are detected and cleared automatically.

"New game" archives the current profile's save to
`saves/archives/<profile>_<timestamp>.txt` before resetting, and the Save
profiles screen can restore any archive.

### Backups

Separate from the main save, the bot writes timestamped snapshots to
`saves/backups/CookieAISaveData_YYYY-MM-DD_HHMMSS.txt` on an interval you
control in Settings. Backups older than the retention window are pruned
automatically. Defaults: every 6 h, kept 7 days. Set the interval to `0`
to disable, or retention to `0` to keep forever.

### Persistent settings

Your menu choices (browser, headless, backup interval, backup retention)
are saved to `saves/settings.json` so the next run starts with the same
configuration. CLI flags (`--browser`, `--headless` / `--no-headless`)
override the persisted values for that run.

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
    hotkeys.py             # runtime keypress listener
    runner.py              # scheduler + main loop
saves/                     # CookieAISaveData.txt + .bak (gitignored)
```

## Is this cheating?

Not the way the game was meant to be played, but the game was intentionally designed so users can run commands from the JavaScript console — you can even set your cookie count to any number you want. This bot only does things you could already do yourself, so it will **not** trigger the [cheated cookies](https://cookieclicker.fandom.com/wiki/Cheating) shadow achievement.
