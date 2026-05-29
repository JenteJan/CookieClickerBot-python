# Cookie Clicker Bot

Automates [Cookie Clicker](https://orteil.dashnet.org/cookieclicker/) with
Selenium. It drives a real browser session the way a player would — clicking,
buying, casting spells, popping golden cookies — so you can leave the game
running and keep progressing while away. A live terminal dashboard shows what
it's doing, and named save profiles let you run and A/B-test different
strategies side by side.

> **Legitimacy:** the bot only performs actions a player could do by hand. It
> never sets cookie counts or unlocks things directly, so it does **not** flag
> your save as cheated. See [Is this cheating?](#is-this-cheating).

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

| Browser | Driver         | macOS install                       |
|---------|----------------|-------------------------------------|
| Firefox | `geckodriver`  | `brew install geckodriver`          |
| Chrome  | `chromedriver` | `brew install --cask chromedriver`  |

`run.sh` creates the virtualenv and installs dependencies automatically on
first launch. To do it manually instead:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

`run.sh` creates the venv, installs deps (only when `requirements.txt`
changes), and launches the bot. It works from any directory and passes
arguments straight through:

```sh
./run.sh                       # opens the interactive menu
./run.sh --no-menu --headless  # skip the menu, no window
./run.sh --profile experiment  # use a named save profile
```

Or call the module directly if you manage the venv yourself:

```sh
python cookieBot.py                    # interactive menu
python cookieBot.py --no-menu          # skip the menu, use CLI flags / saved settings
python cookieBot.py --browser chrome   # Chrome instead of Firefox
python cookieBot.py --headless         # no browser window
python cookieBot.py --fresh            # hard-reset the game on launch
python cookieBot.py --profile <name>   # select a named save profile
```

On launch the menu first asks **which save profile to play** (or create a new
one), then offers: start, new game, settings, bonus achievements, and profile
management.

### Runtime hotkeys

While the bot is running, single keys work without pressing Enter:

| Key | Action                                  |
|-----|-----------------------------------------|
| `q` | Quit (saves first)                      |
| `p` | Pause / resume Python-driven actions    |
| `s` | Save now                                |
| `w` | Pop all wrinklers now                   |
| `a` | Fire safe one-shot achievements         |
| `?` | Re-print this list                      |

Pause only stops the Python-driven purchases, spell casts, and minigame ticks.
The in-page auto-clicker and golden-cookie popper keep running (they're
JavaScript intervals). `Ctrl-C` also quits cleanly.

### The live dashboard

A status panel pins to the bottom of the terminal and refreshes in place:
cookies, CPS, time banked, the target reserve, golden-cookie upgrades owned,
achievements, wrinkler mode, last action, and the **top-3 next buys** ranked by
the active heuristic (best = blue and shown as `1`, others as a fraction of it).

## What it does

- **Auto-clicks** the big cookie and pops every shimmer (golden cookies,
  reindeer) the instant it appears.
- **Buys buildings and upgrades** by value-per-cost, keeping a cookie reserve
  once the three holding upgrades (Lucky day / Serendipity / Get lucky) are
  owned so `Lucky!` payouts hit their cap.
- **Bulk-buys** buildings that are about to cross an achievement count when
  it's cheap to do so (achievements raise the milk → CPS multiplier).
- **Grimoire**: casts Force the Hand of Fate during frenzy stacks; on a big
  combo it inflates the bank (sell temples + take bank loans) and recasts.
- **Clicks ticker fortunes** only when one is actually showing (and only if the
  *Fortune cookies* heavenly upgrade is owned) — never force-rerolls.
- **Runs minigames**: garden clovers, sugar-lump harvest + spend, pantheon
  slotting, buy-low/sell-high on the stock market.
- **Optionally** auto-ascends, trains Krumblor, pops wrinklers during frenzies,
  and unlocks one-shot achievements — all off or conservative by default.
- **Saves** periodically and on exit, with timestamped backups.

## How it decides what to buy

Every purchase tick the bot scores each affordable building and in-store
upgrade by **value per cost** — roughly the inverse of payback time — and buys
the top-ranked item, subject to the cookie reserve. Two scoring modes exist
(toggle "payback mode" in Settings):

- **Parser mode (default).** Reads each upgrade's description text and maps
  known phrasings to a CPS effect (cookie multipliers, clicking, milk, golden
  cookies, building-efficiency). Cheap and good for the common cases, but it
  *guesses* `+5%` for any upgrade whose wording it doesn't recognize — which is
  most of the ~700 upgrades, so it systematically undervalues things like
  building-tier doublings.
- **Payback mode (hybrid).** For each in-store upgrade it asks the game itself
  for the true marginal CPS: flag the upgrade bought, run the game's own
  `CalculateGains()`, read the CPS delta, then revert — all in one synchronous
  call. It scores the upgrade as `max(parser, true-marginal / price)`. The
  marginal catches passive multipliers the parser misses; the parser keeps the
  golden-cookie / clicking upgrades whose value isn't passive CPS (their true
  marginal is ~0). In side-by-side A/B runs this mode pulls clearly ahead.

> Payback mode re-evaluates marginals on a slow (5 s) cadence into a cache, so
> the fast purchase tick stays cheap. It costs two `CalculateGains()` calls per
> in-store upgrade per cycle — negligible in practice, but it's the one mode
> that isn't free.

### What "optimal" means here, and what it ignores

The goal is **near-optimal greedy play**: at each step take the action with the
best value-per-cost, keep a bank sized so `Lucky!` golden cookies pay out their
cap, and exploit frenzy combos when they occur. This captures most of what
makes Cookie Clicker progress fast.

It is **not** a true optimum. Known gaps we don't model:

- **Greedy, not lookahead.** It buys the best item *now*; it doesn't plan
  multi-step sequences (e.g. saving for a synergy that makes a later upgrade far
  better). Real optimal play is a scheduling problem we approximate.
- **Golden-cookie value is heuristic.** `Lucky!`/Frenzy/Click Frenzy value
  depends on bank size, buff stacking, and timing. We size the reserve and
  cast on stacks, but we don't run the deterministic FtHoF/RNG predictor that
  top players use to *guarantee* Click Frenzy combos — that would arguably be
  beyond what a player does by hand, and we chose not to.
- **Ascension timing is a blunt threshold.** Auto-ascend fires on a fixed
  "prestige would grow by ≥ N%" rule. Because prestige ≈ ∛(cookies), the same %
  means very different things early vs late, so no single value is right for a
  whole playthrough. It's off by default; ascend manually for best results.
- **Dragon auras and pantheon gods are fixed/partial.** Aura *selection* is left
  to you (a strategic choice); pantheon slotting uses a fixed god set that may
  not suit your build or season.
- **Sugar lumps** are spent on a simple priority, not optimized per the
  type-manipulation tricks advanced players use.
- **Stock market** uses a plain buy-low/sell-high band, which is a minor lever
  next to combos.

If you care about a specific lever, the per-profile Settings let you tune or
disable most of these.

## Save profiles

Each save is a named **profile** with its own self-contained folder. Everything
under `saves/` is gitignored:

```
saves/
  settings.json                 # global: only which profile is active
  profiles/
    <name>/
      save.txt                  # the live save
      settings.json             # this profile's own strategy + browser config
      backups/<timestamp>.txt   # periodic timestamped snapshots
      archives/<timestamp>.txt  # snapshots taken before a "new game" reset
      instance.lock             # PID of the instance currently running it
```

To import an existing save, export it from the game and paste its contents into
`saves/profiles/<name>/save.txt` before starting. Restart the bot after editing
a save or after prestiging.

### A/B testing strategies

Settings are **per-profile**, so two profiles can run genuinely different
strategies. The menu's **Save profiles** screen lets you switch, create,
**branch** (copy a save + its settings into a new slot), restore an archive, or
delete. To compare side by side, run two instances with different profiles:

```sh
./run.sh --profile payback-on  --no-menu
./run.sh --profile payback-off --browser chrome --no-menu
```

Each profile can only be run by one instance at a time — `instance.lock` (the
owning PID) prevents two instances from writing the same save and clobbering
each other. Launch a second instance on a running profile and the menu offers
to **branch** it (A/B from the same point) or pick another free profile; with
`--no-menu` it explains and exits. Locks from crashed processes are detected and
cleared automatically.

> When comparing results, give each run real time and ideally repeat it —
> golden-cookie RNG swings early-game numbers a lot, so a single short sample
> isn't conclusive.

### Backups

Separate from the live save, the bot writes timestamped snapshots to the
profile's `backups/` folder on an interval you set in Settings. Backups older
than the retention window are pruned automatically. Defaults: every 6 h, kept
7 days. Interval `0` disables; retention `0` keeps forever.

### Persistent settings

Global `saves/settings.json` stores only the active profile. Each profile's own
`settings.json` stores its browser, headless flag, backup schedule, lucky
reserve, payback mode, auto-ascend, dragon training, and achievement options —
saved as you change them in the menu. CLI flags (`--browser`,
`--headless` / `--no-headless`, `--profile`) override for that run.

## Bonus achievements

The menu can fire one-shot achievements that don't require grinding (e.g. the
news-ticker and bakery-name ones). "Safe" entries have no in-game cost; "risky"
ones have a small permanent effect (the *God complex* rename is reverted
afterward so its −1% debuff doesn't stick). Already-owned entries are skipped,
so leaving auto-fire on is idempotent.

## Project layout

```
cookieBot.py               # entry point
run.sh                     # venv bootstrap + launcher
cookiebot/
    config.py              # tunables, paths, per-profile vs global settings
    driver.py              # Firefox/Chrome setup + page bootstrap
    scripts.py             # all JavaScript executed in the page
    heuristics.py          # upgrade parsing + value-per-cost scoring
    persistence.py         # saves, profiles, backups, archives, settings
    locks.py               # per-profile instance locks
    menu.py                # interactive pre-launch menu
    hotkeys.py             # runtime keypress listener
    status.py              # live terminal dashboard
    runner.py              # scheduler + main loop + purchase logic
saves/                     # profiles, backups, settings (gitignored)
```

## Is this cheating?

Not the way the game was meant to be played, but the game was intentionally
designed so users can run commands from the JavaScript console — you can even
set your cookie count to any number you want. This bot only does things you
could already do yourself (clicking, buying, casting, popping), so it will
**not** trigger the [cheated cookies](https://cookieclicker.fandom.com/wiki/Cheating)
shadow achievement.
