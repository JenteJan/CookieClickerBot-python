# What to do yourself

The bot automates the grind — clicking, buying, spells, golden cookies, minigame
upkeep, most one-shot achievements. But some things it deliberately **doesn't**
do, either because they're strategic choices only you should make, or because
they can't be reproduced cleanly without cheating. Doing these yourself is where
the remaining optimization lives.

Quick legend: 🔴 high impact · 🟡 medium · ⚪ minor / situational.

---

## 1. Heavenly upgrades (after each ascension) 🔴

When you ascend, you spend heavenly chips in the ascension screen. **The bot
does not buy these** — it's a one-time tree and the order matters. Rough value
order (from the strategy reference, §10):

1. **Heavenly chip secret** → then **Heavenly cookies** — unlock the +1% CpS per
   prestige level. Without these your prestige does almost nothing, so grab them
   first.
2. **Permanent upgrade slots I–V** — let you keep your best upgrades across
   ascensions (the bot re-buys upgrades each run, but permanents mean you start
   far stronger). Hugely worth it.
3. **Lucky digit / Lucky number / Lucky payout** — boost golden-cookie value,
   which the bot leans on heavily.
4. **How to bake your dragon** — unlocks Krumblor so the bot's dragon training
   can run (see §3).
5. **Twin Gates of Transcendence**, **Starter kit / kitchen** (free buildings),
   **Season switcher**, **Synergies Vol. I/II**, **Five-finger discount**,
   **Distilled essence of redoubled luck**, sugar-lump upgrades — buy roughly in
   value order as chips allow.

> The bot's `--profile` settings persist your strategy, but heavenly upgrades
> live in the save and must be bought by hand on the ascension screen.

## 2. Deciding *when* to ascend 🔴

Auto-ascend is **off by default** and, when on, uses a single blunt threshold
("ascend when prestige would grow ≥ N%"). Because prestige ≈ ∛(cookies), no
single % is right for a whole playthrough (see the README's caveat). Best
results come from ascending manually when *you* judge it's worth it — typically
when the chips you'd gain can buy a heavenly upgrade you want, or when a run has
plateaued. If you do enable auto-ascend, treat it as a convenience, not optimal.

## 3. Dragon (Krumblor) aura selection 🟡

The bot will **train** the dragon (level it up, including the building
sacrifices) but it **stops at each aura-training level and asks you to pick the
aura** — that's a strategic choice it won't make for you. When you see
`dragon at an aura-training level; choose an aura manually to continue` in the
log, open the dragon panel and pick:

- **Idle / general:** *Dragon's Fortune* (huge with frequent golden cookies) or
  *Reality Bending*.
- **Radiance / clicking builds:** *Radiance*.
- **Sell-combo builds:** *Earth Shatterer* + *Reaper of Fields*.

Until you pick, training pauses at that level.

## 4. Pantheon gods 🟡

The bot slots a fixed default set (Mokalsium / a CpS god / a third) when the
Temple minigame unlocks. That's a reasonable idle setup but **not tuned to your
build or season** — review the pantheon and swap if you're running an active
sell-combo (e.g. Godzamok) or want Cyclius timed to your play hours. Swaps are
free-ish and regenerate, so experiment.

## 5. Achievements you must earn yourself

The bot grabs the one-shot achievements it can (`a` hotkey / auto-fire). Some it
performs the real way (Tabloid addiction, Uncanny clicker, the bakery renames
*What's in a name* / *God complex*, *Just wrong* by selling a grandma, and
*Stifling the press* only when the ticker is genuinely in its narrow "help!"
state). A few it simply force-grants via `Game.Win()` because their real DOM
target is fiddly to script but trivial for a player — *Here you go* (an empty
achievement slot), *Olden days* (a hidden madeleine), *Tiny cookie* (the cookie
icon in Stats), *Cookie-dunker*.

Everything below the bot **can't** get for you — they need real-time timing, a
specific window state, or a deliberate run style.

> ⚠️ **Important:** the `p` pause hotkey does **not** stop the golden-cookie
> popper or the auto-clicker — those are in-page JavaScript intervals that keep
> running while paused. To do the golden-cookie timing achievements you must
> **quit the bot** (`q`) and play that browser window yourself, then relaunch.

### Skill / timing (quit the bot — `q` — and play manually)

- 🟡 **Early bird** — click a golden cookie **< 1 second after it spawns**.
  Quit the bot, wait for a golden cookie, and click it the instant it appears.
- 🟡 **Fading luck** — click a golden cookie **< 1 second before it despawns**.
  Quit the bot (it pops every golden cookie within ~1s, so this is impossible
  while it runs), let one appear, and wait until it's almost gone before
  clicking.
- ⚪ **Stifling the press** — squish the **window narrow** until the news ticker
  shows "help!", then click the ticker. The bot will click it for you *if* it
  catches that state, but it never resizes the window — so make the window
  narrow yourself and it'll trigger (or just click the ticker while narrow).
- ⚪ **Cookie-dunker** — resize the window **vertically** until the big cookie
  dips off the bottom edge ("dunking" it). The bot force-grants this, but the
  real way is a window resize.
- ⚪ **Last Chance to See** — burst a **shiny wrinkler** (a rare sparkly variant).
  The bot's wrinkler popping is off by default; if you spot a shiny one, pop it
  yourself (or enable wrinkler popping briefly).

### Run-style shadow achievements (a dedicated run)

- 🟡 **Hardcore** — reach 1 billion baked with **no upgrades purchased**. Run
  with the bot configured to never buy upgrades, or play it manually.
- 🟡 **Neverclick / True Neverclick** — reach 1 million having clicked the big
  cookie ≤15 times / **never**. The bot auto-clicks, so this needs the
  auto-clicker off and careful play.
- 🟡 **Speed baking I–III** — reach 1M within a tight time limit after ascending.
  A focused fresh-run objective.
- 🔴 **NEVER: "Cheated cookies taste awful"** — the only achievement that flags
  your save as cheated. The bot avoids it on purpose; never open the cheat
  console / type a bakery name ending in `saysopensesame`.

### Collection / grind (mostly just time)

- ⚪ **Season completions** — collect all Christmas-card / Halloween-cookie / egg
  / heart drops and finish each set (needs *Season switcher* to change seasons).
  The bot pops shimmers so it gathers reindeer/eggs passively, but won't switch
  seasons or track completion.
- ⚪ **Garden achievements** — unlock every seed, freeze the garden, harvest rare
  plants (Queenbeet / Elderwort / etc.). The bot only clover-spams; the garden
  meta-game is yours.
- ⚪ **Wholesome** — unlock 100% of your heavenly-chips power (a heavenly-upgrade
  milestone; see §1).
- ⚪ **Building-count / cookies-baked / clicking-count / "play for N days" tiers**
  — pure grind; nothing to do but let it run.

## 6. Things the bot intentionally leaves on the table ⚪

Not achievements, but optimizations it doesn't chase (from the README's "what
it ignores"):

- **FtHoF / RNG prediction** — top players predict the spell RNG to *guarantee*
  Click Frenzy combos. The bot casts on stacks but doesn't predict — arguably
  beyond what a human does by hand, so it's omitted by design.
- **Sugar-lump type manipulation** — forcing Golden/Bifurcated lumps via
  grandma count / dragon auras. The bot just spends lumps on a value priority.
- **Sugar Baking hoard** — if you own the upgrade that rewards stockpiling up to
  100 lumps, there's a spend-vs-hoard tradeoff the bot doesn't model (it always
  spends). Disable lump spending in settings if you want to hoard.
- **Wrinkler timing** — the bot can auto-pop during Frenzies, but the optimal
  "let them fill, pop before a max Lucky" timing is a manual call (`w` pops on
  demand).

---

## TL;DR checklist after each ascension

1. Spend heavenly chips (Heavenly chip secret → Heavenly cookies → Permanent
   upgrade slots → Lucky upgrades → the rest). 🔴
2. If the dragon hit an aura level, pick an aura. 🟡
3. Glance at the pantheon; swap gods if your build changed. 🟡
4. Decide if this run's ascension timing felt right; adjust your manual cadence. 🔴

Everything else — buying, clicking, golden cookies, spells, sugar lumps,
fireable achievements — the bot handles.
