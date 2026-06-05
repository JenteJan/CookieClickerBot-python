"""JavaScript snippets executed inside the Cookie Clicker page context.

Kept as module-level constants so the runner stays readable. Anything mutating
the page goes through one of these strings via ``driver.execute_script``.
"""

WAIT_FOR_GAME_READY = """
return typeof Game !== 'undefined'
       && Game.ready === 1
       && typeof Game.Objects !== 'undefined';
"""

CLOSE_PROMPT = "Game.ClosePrompt();"

# Cut rendering CPU for headless/background runs. The game's logic and draw are
# separate: Game.Loop only calls the expensive Game.Draw() when Game.visible is
# true (it's normally toggled by the tab's visibilitychange). Headless Firefox
# still reports the page visible, so it renders full-speed for nobody. We force
# visible=false (re-asserted on a short interval since the event can flip it
# back) and disable the cosmetic prefs (particles, floating numbers, wobble,
# fancy graphics, etc.). Game logic — cookies, CPS, golden cookies — is
# unaffected; only drawing stops. Returns the prefs we changed.
DISABLE_RENDERING = """
Game.visible = false;
if (!window._abKeepHidden) {
    window._abKeepHidden = setInterval(function() { Game.visible = false; }, 1000);
}
var off = ['particles','numbers','wobbly','fancy','milk','cursors','filters','extraButtons'];
if (Game.prefs) {
    for (var i = 0; i < off.length; i++) {
        if (off[i] in Game.prefs) Game.prefs[off[i]] = 0;
    }
}
return true;
"""

# Force deterministic RNG for A/B trials. The game pins per-event randomness to
# Game.seed (e.g. "seed/lumpT", "seed-fortune"), but also calls Math.seedrandom()
# with NO argument 11 times to deliberately go back to entropy — which would
# defeat a one-time seed. So we (a) pin Game.seed to a fixed value, and
# (b) wrap Math.seedrandom so a no-arg "go random" call instead re-keys from our
# fixed seed plus a monotonic counter — deterministic, but still varied per call.
# arguments[0] = seed string.
#
# Caveat: two runs share the RNG stream only while they make identical choices;
# once their purchases diverge (e.g. a Building Special rolls a building), the
# streams desync. This reduces variance and guarantees an identical START, not
# bit-identical luck forever — the trial log is what proves where they diverge.
SEED_RNG = """
var seed = arguments[0];
if (typeof Math.seedrandom !== 'function') return false;
if (!window._origSeedrandom) window._origSeedrandom = Math.seedrandom;
window._abSeed = seed;
window._abSeedCounter = 0;
Math.seedrandom = function(arg) {
    if (arg === undefined || arg === null || arg === '') {
        window._abSeedCounter++;
        return window._origSeedrandom(window._abSeed + '#' + window._abSeedCounter);
    }
    return window._origSeedrandom(arg);
};
// Re-key the live stream now, and pin the game's own seed.
Math.seedrandom(seed + '#init');
if (typeof Game !== 'undefined') Game.seed = seed;
return true;
"""

START_AUTOCLICK_COOKIE = """
if (window._autoClickCookie) clearInterval(window._autoClickCookie);
window._autoClickCookie = setInterval(function() { Game.ClickCookie(); }, arguments[0]);
"""

# Pop the shimmers (golden cookies, reindeer). When window._botPopWrath === false,
# SKIP wrath cookies (the red ones during the Grandmapocalypse) so their Clot/Ruin
# effects can't fire — at the cost of also forgoing the wrath-only Elder Frenzy.
# Reindeer have no .wrath property so they're always popped. (`pop()` removes the
# shimmer, so iterate backwards over the current snapshot.)
_POP_SHIMMERS_JS = """
for (var _i = Game.shimmers.length - 1; _i >= 0; _i--) {
    var _s = Game.shimmers[_i];
    if (window._botPopWrath === false && _s.wrath) continue;
    _s.pop();
}
"""

START_AUTOCLICK_GOLDEN = ("""
if (window._autoGolden) clearInterval(window._autoGolden);
window._autoGolden = setInterval(function() {
""" + _POP_SHIMMERS_JS + """
}, arguments[0]);
""")

# Set whether wrath cookies are auto-popped (default true if never set).
SET_POP_WRATH = "window._botPopWrath = arguments[0];"

# Gated auto-clicker start for A/B: both browsers share the OS wall clock, so
# passing the same Date.now() deadline (arguments[2], ms epoch) makes both
# instances actually begin clicking at the same instant — independent of when
# Selenium delivers each command. Until the deadline the intervals run but
# no-op. args: cookieMs, goldenMs, startAtMs.
START_AUTOCLICK_GATED = ("""
var cookieMs = arguments[0], goldenMs = arguments[1], startAt = arguments[2];
window._abStartAt = startAt;
if (window._autoClickCookie) clearInterval(window._autoClickCookie);
if (window._autoGolden) clearInterval(window._autoGolden);
window._autoClickCookie = setInterval(function() {
    if (Date.now() >= window._abStartAt) Game.ClickCookie();
}, cookieMs);
window._autoGolden = setInterval(function() {
    if (Date.now() >= window._abStartAt) {
""" + _POP_SHIMMERS_JS + """
    }
}, goldenMs);
return Date.now();
""")

# One round-trip snapshot of everything we evaluate per purchase tick.
GAME_SNAPSHOT = """
return {
    cookies: Game.cookies,
    cookiesPs: Game.cookiesPs,
    // -1 when the player has toggled the store to sell mode. While selling,
    // Game.Objects[x].buy() is silently redirected to sell(), so the bot must
    // not "purchase" or it would dump buildings on the user's behalf.
    buyMode: Game.buyMode,
    buildings: Object.values(Game.Objects).map(function(b) {
        var totalCps = b.storedTotalCps * Game.globalCpsMult;
        var cps = b.storedCps * Game.globalCpsMult;
        var heuristic = b.price > 0 ? cps / b.price : 0;
        return {
            name: b.name,
            heuristic: heuristic,
            amount: b.amount,
            price: b.price,
            locked: b.locked,
            storedCps: b.storedCps,
            totalCps: totalCps
        };
    }),
    // getPrice() reflects live discounts (Master of the Armory aura, Season,
    // Five-finger discount, Haggler's Charm) that the cached basePrice misses.
    upgradesInStore: Game.UpgradesInStore.map(function(u) {
        return {id: u.id, price: (u.getPrice ? u.getPrice() : u.basePrice)};
    })
};
"""

GET_ALL_UPGRADES = """
return Object.values(Game.Upgrades).map(function(u) {
    // dname is the human-facing display name (localized); name is the internal
    // key. Prefer dname so the UI never shows an internal id. pool tags the
    // upgrade kind ('' normal, 'cookie' flavored CpS, 'toggle'/'switch' the
    // Golden switch / Shimmering veil / cosmetic selectors we must never buy).
    return [u.id, u.desc, u.basePrice, u.dname || u.name, u.pool || ''];
});
"""

# True marginal CPS for every in-store upgrade, measured with the game's own
# CalculateGains(): flag the upgrade bought, recompute, read the new cookiesPs,
# then revert. This captures passive-multiplier upgrades (flavored cookies,
# kittens, building tiers, synergies) that the description parser approximates
# or misses. Wrapped in try/finally so a throw can't leave the live game in a
# mutated state. Returns {id: deltaCps} and the baseline cps used.
EVALUATE_UPGRADE_MARGINALS = """
var base = Game.cookiesPs;
var out = {};
var store = Game.UpgradesInStore;
for (var i = 0; i < store.length; i++) {
    var u = store[i];
    var was = u.bought;
    var delta = 0;
    try {
        u.bought = 1;
        Game.CalculateGains();
        delta = Game.cookiesPs - base;
    } catch (e) {
        delta = 0;
    } finally {
        u.bought = was;
    }
    out[u.id] = delta;
}
// Restore the real CPS after all the hypotheticals.
Game.CalculateGains();
return {base: base, deltas: out};
"""

# True marginal CPS of one MORE of each building, measured with CalculateGains
# (bump amount by 1, recompute, read the cookiesPs delta, revert). Unlike the
# static storedCps/price heuristic this captures the boost a new building gives to
# OTHER buildings — Thousand-Fingers cursor scaling, grandma-per-building
# synergies, building-pair synergies, Idleverse/Cortex cross-boosts, etc. Wrapped
# in try/finally so a throw can't leave amounts mutated. Returns {name: deltaCps}.
EVALUATE_BUILDING_MARGINALS = """
var base = Game.cookiesPs;
var out = {};
for (var key in Game.Objects) {
    var b = Game.Objects[key];
    var amt = b.amount, delta = 0;
    try {
        b.amount = amt + 1;
        Game.CalculateGains();
        delta = Game.cookiesPs - base;
    } catch (e) {
        delta = 0;
    } finally {
        b.amount = amt;
    }
    out[b.name] = delta;
}
Game.CalculateGains();  // restore real CPS
return {base: base, deltas: out};
"""

# "Tier unlock bundles": a tiered building upgrade (each ~2x that building's
# output) only becomes purchasable once you own Game.Tiers[tier].unlock of the
# building. This evaluates, per building, the nearest LOCKED tiered upgrade
# reachable within maxStep buildings, and treats "buy the missing buildings +
# the unlocked upgrade" as one bundle: combined cost and combined true CPS gain
# (bump amount, flag the upgrade bought, CalculateGains, revert). The runner
# scores the bundle by gain/cost so it competes with single buys.
#
# Returns a list of:
#   {building, upgradeId, qty, cost, gainCps}
# where qty buildings + upgrade upgradeId are bought together.
EVALUATE_TIER_BUNDLES = """
var maxStep = arguments[0];
var base = Game.cookiesPs;
var out = [];

for (var key in Game.Objects) {
    var b = Game.Objects[key];
    // nearest locked tiered upgrade within reach
    var best = null;
    for (var tier in b.tieredUpgrades) {
        var up = b.tieredUpgrades[tier];
        if (!up || up.bought || up.unlocked) continue;  // only still-locked tiers
        var need = Game.Tiers[tier] ? Game.Tiers[tier].unlock : -1;
        if (need == null || need < 0) continue;
        var qty = need - b.amount;
        if (qty < 0) qty = 0;                 // threshold already met, just locked-by-order
        if (qty > maxStep) continue;
        if (best === null || qty < best.qty) best = {up: up, qty: qty, need: need};
    }
    if (best === null) continue;

    var buildingCost = best.qty > 0 ? b.getSumPrice(best.qty) : 0;
    var upCost = (best.up.getPrice ? best.up.getPrice() : best.up.basePrice);
    var cost = buildingCost + upCost;

    // Combined true CPS gain: amount += qty AND upgrade bought, then recompute.
    var amt = b.amount, was = best.up.bought, gain = 0;
    try {
        b.amount = amt + best.qty;
        best.up.bought = 1;
        Game.CalculateGains();
        gain = Game.cookiesPs - base;
    } catch (e) {
        gain = 0;
    } finally {
        b.amount = amt;
        best.up.bought = was;
    }

    out.push({building: b.name, upgradeId: best.up.id, qty: best.qty,
              cost: cost, gainCps: gain});
}
Game.CalculateGains();  // restore real CPS
return out;
"""

# Compact state snapshot for the A/B trial log. Active buffs are included so the
# analysis can verify two seeded runs really did get identical luck (same buffs
# at the same times) before attributing any cookie gap to strategy.
TRIAL_SNAPSHOT = """
var buffs = [];
for (var b in Game.buffs) { if (Game.buffs[b]) buffs.push(b); }
return {
    cookies: Game.cookies,
    cookiesEarned: Game.cookiesEarned,
    cookiesPs: Game.cookiesPs,
    // Base production WITHOUT golden-cookie buffs (main.js sets this to
    // cookiesPs*mult before applying Frenzy etc.). This is the stable measure
    // of build strength — cookiesPs spikes x7 during a Frenzy and is too noisy
    // to compare. A/B analysis should prefer this.
    unbuffedCps: Game.unbuffedCps,
    buildingsOwned: Game.BuildingsOwned,
    upgradesOwned: Game.UpgradesOwned,
    achievementsOwned: Game.AchievementsOwned,
    prestige: Game.prestige,
    buffs: buffs,
    wrinklers: Game.wrinklers ? Game.wrinklers.filter(function(w){return w && w.phase==2;}).length : 0,
    seedCounter: window._abSeedCounter || 0
};
"""

# Read the live golden-cookie spawn timing straight from the game, which already
# applies every frequency modifier (Lucky day, Serendipity, Arcane Aura, season,
# pantheon, etc.). Returns min/max spawn FRAMES and fps; the Python side converts
# to a mean interval. Also reports current cookies/cps and whether a Frenzy-style
# multiplier is active (so the Lucky cap can use the buffed CPS).
GOLDEN_TIMING = """
var g = Game.shimmerTypes['golden'];
var minF = 0, maxF = 0;
try { minF = g.getMinTime(g); maxF = g.getMaxTime(g); } catch (e) {}
var hasFortune = Game.Has && Game.Has('Get lucky');
return {
    minFrames: minF,
    maxFrames: maxF,
    fps: Game.fps || 30,
    cookies: Game.cookies,
    cookiesPs: Game.cookiesPs,       // live (buffed) CPS — Lucky cap uses this
    unbuffedCps: Game.unbuffedCps,
    getLucky: !!hasFortune,          // "Get lucky" raises the cap multiplier
    canSpawn: !!(g.spawnConditions ? g.spawnConditions() : true)
};
"""

COUNT_GOLDEN_COOKIE_UPGRADES = """
var names = arguments[0];
var total = 0;
for (var i = 0; i < names.length; i++) {
    var u = Game.Upgrades[names[i]];
    if (u && u.bought == 1) total++;
}
return total;
"""

BUY_BUILDING = "Game.Objects[arguments[0]].buy(arguments[1]);"
# buy(1) passes bypass=truthy, which skips the click-handler. For most upgrades
# .click() is fine, but grandmapocalypse upgrades (One Mind, Communal Brainsweep,
# Elder Pact, …) attach a clickFunction that opens a blocking confirm Prompt and
# returns false — so .click() every tick re-spawns that modal and freezes the UI.
# buy(1) is exactly what the game's own "Yes" button calls, so it purchases
# directly with no modal.
BUY_UPGRADE = "Game.UpgradesById[arguments[0]].buy(1);"

# Execute a pre-computed batch of buys in one round trip (the bulk-buy drain).
# The runner already decided WHAT to buy and in WHAT order (reusing its scoring +
# golden-reserve checks, simulated locally), so this stays dumb: it just walks the
# list and buys. Each action is a compact array to keep the payload small:
#   ['b', buildingName, qty]  -> buy qty of a building
#   ['u', upgradeId]          -> buy an in-store upgrade (skip if already bought)
# buy() is used (not click()) for the same reason as BUY_UPGRADE: it never opens a
# blocking grandmapocalypse modal. Returns how many individual buys landed.
BULK_BUY = """
var actions = arguments[0];
var n = 0;
for (var i = 0; i < actions.length; i++) {
    var a = actions[i];
    if (a[0] === 'b') {
        var o = Game.Objects[a[1]];
        if (o) { var q = a[2] || 1; o.buy(q); n += q; }
    } else {
        var u = Game.UpgradesById[a[1]];
        if (u && u.unlocked && !u.bought) { u.buy(1); n += 1; }
    }
}
return n;
"""

# Buy a tier-unlock bundle atomically: the qty buildings first (which unlocks
# the tiered upgrade via the game's own UnlockTiered hook), then the upgrade.
# args: building name, qty, upgrade id.
BUY_TIER_BUNDLE = """
var name = arguments[0], qty = arguments[1], upId = arguments[2];
if (qty > 0) Game.Objects[name].buy(qty);
var up = Game.UpgradesById[upId];
if (up && up.unlocked && !up.bought) up.buy(1);
return up ? (up.bought == 1) : false;
"""

# Click the news ticker iff a clickable fortune is currently showing.
# Gated on the 'Fortune cookies' heavenly upgrade — without it the game can't
# spawn fortunes at all (main.js L7858), so polling is wasted otherwise.
# We deliberately do NOT call Game.getNewTicker() to force extra rolls: a
# player tapping the ticker triggers a manual reroll that skips the fortune
# check, so force-rolling here would be doing something the UI can't do.
CLICK_TICKER_IF_USEFUL = """
// 1. A clickable fortune is showing (needs the Fortune cookies heavenly upgrade).
if (Game.Has && Game.Has('Fortune cookies')
    && Game.TickerEffect && Game.TickerEffect.type === 'fortune') {
    Game.tickerL.click();
    return 'fortune';
}
// 2. The window is narrow enough that the ticker shows "help!" — clicking it in
// that state awards "Stifling the press" (the game checks windowW <
// tickerTooNarrow in the click handler). This is a genuine click of the real
// help-state ticker, not a forced win, so we only do it when that state holds.
var stifling = Game.Achievements && Game.Achievements['Stifling the press'];
if (Game.windowW < Game.tickerTooNarrow && stifling && !stifling.won) {
    Game.tickerL.click();
    return 'stifling';
}
return '';
"""

# Find building-count achievements worth rushing toward. For each building we
# look at its UNWON tiered achievements (building.tieredAchievs → the count is
# Game.Tiers[tier].achievUnlock), pick the nearest reachable one, and quantify
# the actual gain of crossing it.
#
# Achievements raise milk (Game.milkProgress = AchievementsOwned/25), which
# multiplies CPS through kitten upgrades — so the true value is measured with
# the game's own CalculateGains() (bump AchievementsOwned, recompute, revert),
# exactly like upgrade marginals. Buildings reset on ascension but achievements
# persist, so already-won ones are skipped (the old code re-rushed them every
# run for zero gain) and hardcoded thresholds are gone (they were partly wrong).
#
# Returns, per actionable building:
#   {name, qty, cost, gainCps}  — buy `qty` more to cross an unwon achievement.
EVALUATE_ACHIEVEMENT_BUILDINGS = """
var maxStep = arguments[0];   // don't chase achievements more than this many away
var baseCps = Game.cookiesPs;
var out = [];

for (var key in Game.Objects) {
    var b = Game.Objects[key];
    // nearest unwon tiered achievement for this building
    var bestQty = 0, bestCount = 0;
    for (var tier in b.tieredAchievs) {
        var ach = b.tieredAchievs[tier];
        if (!ach || ach.won) continue;
        var need = Game.Tiers[tier] ? Game.Tiers[tier].achievUnlock : 0;
        if (!need) continue;
        var qty = need - b.amount;
        if (qty <= 0 || qty > maxStep) continue;
        if (bestQty === 0 || qty < bestQty) { bestQty = qty; bestCount = need; }
    }
    if (bestQty === 0) continue;

    var cost = b.getSumPrice(bestQty);

    // True CPS gain from the +1 achievement this purchase would unlock.
    var owned = Game.AchievementsOwned;
    Game.AchievementsOwned = owned + 1;
    var gain = 0;
    try { Game.CalculateGains(); gain = Game.cookiesPs - baseCps; }
    catch (e) { gain = 0; }
    finally { Game.AchievementsOwned = owned; }

    out.push({name: b.name, qty: bestQty, cost: cost, gainCps: gain});
}
Game.CalculateGains();  // restore real CPS
return out;
"""

PLANT_CLOVERS = """
if (Game.ObjectsById[2].minigame && Game.ObjectsById[2].minigame.plantsById[4].unlocked == 1) {
    for (var i = 0; i < 7; i++) {
        for (var j = 0; j < 7; j++) {
            try {
                if (Game.ObjectsById[2].minigame.getTile(i, j)[0] == 0) {
                    Game.ObjectsById[2].minigame.seedSelected = 4;
                    Game.ObjectsById[2].minigame.clickTile(i, j);
                }
            } catch (error) {}
        }
    }
}
"""

# ---- Garden (Farm minigame) -------------------------------------------------
#
# One read + one batched write per garden tick. The Python side (cookiebot.garden)
# decides every move from the snapshot; GARDEN_ACTIONS just applies the list.
#
# Garden API (M = Game.ObjectsById[2].minigame):
#   M.getTile(x,y) -> [plantId, age]   (0 = empty)
#   M.isTileUnlocked(x,y)              (which plots the current Farm level opened)
#   M.plantsById[id]: {key,name,mature,unlocked,children,cost}
#   M.useTool(seedId,x,y)              plant a seed on an empty tile
#   M.harvest(x,y)                     remove a plant (maturity already unlocked it)
#   M.soil / M.soils / M.nextSoil      soil index / defs / cooldown timestamp(ms)
# Maturity: age >= plant.mature. We never freeze (M.freeze suppresses effects).
GET_GARDEN_STATE = """
var M = Game.ObjectsById[2] && Game.ObjectsById[2].minigame;
if (!M || !M.plantsById) return {unlocked: false};
// Soils are gated by farms owned (M.parent.amount >= soil.req): Fertilizer 50,
// Clay 100, Pebbles 200, Wood chips 300. Expose id+req so Python can guard.
var soils = [];
for (var sk in M.soils) {
    var s = M.soils[sk];
    soils.push({key: sk, id: s.id, req: s.req || 0});
}
var plants = [];
for (var i = 0; i < M.plantsById.length; i++) {
    var p = M.plantsById[i];
    if (!p || !p.key) continue;  // slot 0 / empties are undefined
    plants.push({
        id: p.id, key: p.key, name: p.name,
        mature: p.mature, unlocked: !!p.unlocked,
        cost: p.cost, costM: p.costM, children: (p.children || []).slice()
    });
}
var tiles = [];
for (var y = 0; y < 6; y++) {
    for (var x = 0; x < 6; x++) {
        if (!M.isTileUnlocked(x, y)) continue;
        var t;
        try { t = M.getTile(x, y); } catch (e) { continue; }
        var id = t[0], age = t[1];
        var pl = id ? M.plantsById[id] : null;
        var matureAge = pl ? pl.mature : 0;
        tiles.push({x: x, y: y, id: id, age: age, matureAge: matureAge,
                    key: pl ? pl.key : null, mature: id !== 0 && age >= matureAge});
    }
}
return {
    unlocked: true,
    freeze: M.freeze ? 1 : 0,
    soil: M.soil,
    soils: soils,
    farms: M.parent ? M.parent.amount : 0,
    nextSoil: M.nextSoil || 0,
    now: Date.now(),
    plants: plants,
    tiles: tiles
};
"""

# Apply a list of action dicts (arguments[0]); each move is independently
# guarded so one failure can't abort the batch. Returns simple counts.
GARDEN_ACTIONS = """
var M = Game.ObjectsById[2] && Game.ObjectsById[2].minigame;
var acts = arguments[0] || [];
var out = {planted: 0, harvested: 0, soil: -1};
if (!M) return out;
for (var i = 0; i < acts.length; i++) {
    var a = acts[i];
    try {
        if (a.op === 'soil') {
            // Mirror the game's own guard (we bypass its click handler): right
            // farms owned, not frozen, off cooldown, actually changing.
            var sObj = null;
            for (var sk in M.soils) { if (M.soils[sk].id === a.soil) { sObj = M.soils[sk]; break; } }
            if (sObj && !M.freeze && M.soil !== a.soil &&
                Date.now() >= (M.nextSoil || 0) && M.parent.amount >= (sObj.req || 0)) {
                M.toCompute = true;
                M.soil = a.soil;
                M.nextSoil = Date.now() + (Game.Has('Turbo-charged soil') ? 1 : 1000*60*10);
                out.soil = a.soil;
            }
        } else if (a.op === 'plant') {
            // Proven path (see PLANT_CLOVERS): select the seed, click the empty
            // tile. clickTile plants the selected seed on an empty plot.
            if (M.getTile(a.x, a.y)[0] === 0) {
                M.seedSelected = a.seed;
                M.clickTile(a.x, a.y);
                out.planted++;
            }
        } else if (a.op === 'harvest') {
            var tt = M.getTile(a.x, a.y);
            if (tt[0] !== 0) {
                var hp = M.plantsById[tt[0]];
                var wasUnlocked = hp ? !!hp.unlocked : true;
                var hage = tt[1], hmat = hp ? hp.mature : 0;
                M.harvest(a.x, a.y);
                out.harvested++;
                // Track unlock-on-harvest: a mature locked species SHOULD flip to
                // unlocked here. Report both outcomes so the Python side can tell
                // whether discovery is actually being captured.
                if (hp && !wasUnlocked) {
                    if (hp.unlocked) { (out.unlocked = out.unlocked || []).push(hp.key); }
                    else { (out.notUnlocked = out.notUnlocked || []).push(
                        hp.key + " age=" + hage + "/" + hmat); }
                }
            }
        }
    } catch (e) {}
}
M.seedSelected = -1;
return out;
"""

# Cast Force the Hand of Fate (spellsById[1]) when a frenzy-stack is up — it
# spawns a golden cookie whose Lucky! payout scales with the bank, so during a
# Frenzy this is the big combo. If a really juicy combo lands a moment later
# (3+ buffs incl. Click frenzy / Dragonflight), inflate the bank first by
# selling 400 temples + taking all bank loans, then cast FtHoF again so the
# 15%-of-bank payout is maximised.
GET_LUCKY = """
var FRENZY_BUFFS = [
    "Frenzy","Breakthrough","Extra cycles","Juicy profits","Winning streak",
    "Brainstorm","High-five","Oiled-up","Luxuriant harvest","Macrocosm",
    "Congregation","Cosmic nursery","Refactoring","Ore vein",
    "Righteous cataclysm","Solar flare","Delicious lifeforms",
    "Fervent adoration","Golden ages","Manabloom","Deduplication"
];

function buffNames(extraNames) {
    var names = FRENZY_BUFFS.concat(extraNames || []);
    var hits = [];
    for (var n = 0; n < names.length; n++) {
        if (Game.buffs[names[n]]) hits.push(names[n]);
    }
    return hits;
}

// Fully instrumented for combo debugging. Besides casting FtHoF on a buff stack,
// it records EVERYTHING about the moment — every active buff (CpS & click mult +
// time left), the live multiplier, shimmers on screen, magic vs. cost, and the
// exact cast / sell / loan actions (including the async juicy second cast) — into
// a window-global event buffer that the Python side drains and writes to disk, so
// an overnight run leaves a complete per-combo record.
if (!window._botComboEvents) window._botComboEvents = [];
function ev(o) { o.t = Date.now(); window._botComboEvents.push(o); }

var out = {hasGrimoire: false, n: 0, buffs: [], magic: null, magicM: null,
           ftofCost: null, cast: false, mult: 1, goldens: 0, now: Date.now(),
           cookies: Game.cookies, cookiesPs: Game.cookiesPs, unbuffedCps: Game.unbuffedCps,
           buffDetails: [], shimmers: []};
out.buffs = buffNames();
out.n = out.buffs.length;
if (Game.unbuffedCps > 0) out.mult = Game.cookiesPs / Game.unbuffedCps;
out.goldens = Game.shimmers ? Game.shimmers.length : 0;
if (Game.shimmers) for (var si = 0; si < Game.shimmers.length; si++) out.shimmers.push(Game.shimmers[si].type);
// Click buffs (Dragonflight, Click frenzy, …) multiply CLICK power, not CpS.
out.clickMult = 1; out.clickBuffs = []; out.cpsBuffs = [];
for (var bn in Game.buffs) {
    var bf = Game.buffs[bn];
    if (!bf) continue;
    out.buffDetails.push({name: bn, cps: bf.multCpS || 1, click: bf.multClick || 1,
                          time: bf.time, maxTime: bf.maxTime});
    if (bf.multClick && bf.multClick > 1) { out.clickMult *= bf.multClick; out.clickBuffs.push(bn); }
    if (bf.multCpS && bf.multCpS > 1) out.cpsBuffs.push(bn);
}
var wiz = Game.ObjectsById[7] ? Game.ObjectsById[7].minigame : null;
out.hasGrimoire = !!wiz;
if (wiz) {
    out.magic = wiz.magic;
    out.magicM = wiz.magicM;
    var spell = wiz.spellsById[1];
    if (spell) out.ftofCost = (spell.costMin || 0) + (spell.costPercent || 0) * wiz.magicM;
    // When to cast Force the Hand of Fate (FtHoF):
    //   (a) ESCALATE — an existing 2+ buff stack is already up (the original gate):
    //       chain another golden onto it for the big multi-buff combo.
    //   (b) OPEN — a single Frenzy (CpS multiplier ≥2) is up AND magic is near full.
    //       This is the missing opener: random goldens almost never produce a
    //       2-buff stack on their own, so without (b) the (a) gate could never be
    //       reached and FtHoF was effectively never cast (magic sat pinned at max
    //       all night). We bank magic to ~full and dump it the instant a Frenzy
    //       lands, aiming for a Lucky / Click frenzy ON TOP of the Frenzy (a
    //       Frenzy-boosted Lucky is the single biggest cookie windfall in the
    //       game). Gating the opener on near-full magic self-throttles it to ~one
    //       cast per magic-refill, so a 77s Frenzy fires a single cast rather than
    //       a magic-draining spam of independent (and occasionally backfiring)
    //       rolls. The escalation cast inside (a) still re-checks live state.
    var frenzyActive = out.mult >= 2;
    var magicReady = wiz.magic >= Math.max(out.ftofCost || 0, wiz.magicM * 0.6);
    out.wantOpen = frenzyActive && magicReady;   // surfaced for logging
    if (spell && (out.n >= 2 || out.wantOpen)) {
        var mb = wiz.magic;
        out.cast = !!wiz.castSpell(spell);
        ev({type: 'ftof', n: out.n, mult: out.mult, magicBefore: mb, magicAfter: wiz.magic,
            cost: out.ftofCost, ok: out.cast, buffs: out.buffs, cookies: Game.cookies});
        if (out.cast) {
            setTimeout(function() {
                var jb = buffNames(["Click frenzy", "Dragonflight"]);
                if (jb.length >= 3) {
                    Game.ObjectsById[7].sell(400);
                    ev({type: 'sell', building: 'Wizard tower', qty: 400, buffs: jb, cookies: Game.cookies});
                    var bank = Game.ObjectsById[5].minigame;
                    if (bank) {
                        // takeLoan() does NOT check the unlock gate — calling it on a
                        // locked loan still spends the 20-50%-of-bank downpayment. Gate
                        // on office level (loan 1 > 1, loan 2 > 3). Loan 3 is skipped:
                        // +20% for 2 days then -20% for 5 days is the opposite of a burst.
                        if (bank.officeLevel > 1) { bank.takeLoan(1); ev({type: 'loan', id: 1}); }
                        if (bank.officeLevel > 3) { bank.takeLoan(2); ev({type: 'loan', id: 2}); }
                    }
                    var mb2 = wiz.magic;
                    var ok2 = !!wiz.castSpell(wiz.spellsById[1]);
                    ev({type: 'ftof2', magicBefore: mb2, magicAfter: wiz.magic, ok: ok2, cookies: Game.cookies});
                }
            }, 1000);
        }
    }
}
out.events = window._botComboEvents.splice(0);   // drain what's accumulated since last tick
return out;
"""

FARM_SUGAR_LUMPS = """
if (Date.now() - Game.lumpT >= Game.lumpRipeAge) {
    Game.clickLump();
}
"""

BUY_PLEDGE = """
var pledge = Game.UpgradesById[74];
if (pledge && pledge.unlocked == 1 && pledge.bought == 0 && Game.cookies >= pledge.basePrice) {
    pledge.click(event);
}
"""

# Max-burst combo pantheon. Slots are 0=Diamond (strongest), 1=Ruby, 2=Jade.
#   Diamond: Godzamok (Ruin, id 2) — selling buildings triggers a big click buff
#            scaled by how many were sold. THE combo engine: the FtHoF combo above
#            sells 400 wizard towers, so this fires right as the autoclicker stacks
#            on Frenzy + Click frenzy + Dragonflight.
#   Ruby:    Muridal (Labor, id 6) — clicking is X% more powerful.
#   Jade:    Mokalsium (Mother, id 8) — milk/CpS multiplier (no downside).
# Swaps are scarce (max 3, regenerate over hours), so only move a god that's NOT
# already in its target slot, and only while a swap is available — never burn
# swaps re-slotting an already-correct setup. Initial setup costs 3 swaps once.
#
# slotGod() ALONE only updates the data model (M.slot + recalc flags); the real
# game does the swap accounting and rendering in its drop handler. Calling
# slotGod directly therefore left slots looking empty until hovered and never
# spent a swap (effectively cheating). So we mirror the drop handler: spend a
# worship swap via useSwap(1) and re-parent the god's DOM node into the slot.
SET_PANTHEON = """
var temple = Game.ObjectsById[6];
var M = temple && temple.minigame;
if (!M || temple.level == 0 || !M.slot) return;
var want = [2, 6, 8];  // [Diamond, Ruby, Jade] = Godzamok, Muridal, Mokalsium
function l(id){ return document.getElementById(id); }

function realSlot(godId, slot) {
    var god = M.godsById[godId];
    if (!god || god.slot === slot) return false;  // already in place
    if (M.swaps <= 0) return false;               // play fair: no free swaps
    M.useSwap(1);                                  // spend the worship swap + set swapT
    var div = l('templeGod' + god.id), slotEl = l('templeSlot' + slot);
    if (div && slotEl) {                           // re-parent DOM like the drop handler
        var prev = M.slot[slot];                   // god already in the target slot
        if (prev !== -1) {
            var prevDiv = l('templeGod' + prev);
            if (prevDiv) {
                if (god.slot !== -1) l('templeSlot' + god.slot).appendChild(prevDiv);
                else {
                    var ph = l('templeGodPlaceholder' + prev);
                    if (ph && ph.parentNode) ph.parentNode.insertBefore(prevDiv, ph);
                }
            }
        }
        slotEl.appendChild(div);
    }
    M.slotGod(god, slot);                          // commit data model + recalc flags
    return true;
}

for (var slot = 0; slot < 3; slot++) {
    if (M.slot[slot] === want[slot]) continue;     // already correct
    if (M.swaps <= 0) break;                        // out of swaps; revisit later
    try { realSlot(want[slot], slot); } catch (e) {}
}
"""

# Spend sugar lumps by a value-ordered priority (strategy guide §18.5). Leveling
# a building to level N costs N+1 lumps (Game.spendLump(level+1, …)). We do ONE
# level-up per call (the cheapest worthwhile target we can afford), so a steady
# lump income trickles into the best slot over time.
#
# Priority, in order:
#   1. Unlock the four minigames at level 1 — biggest gameplay unlock:
#      Wizard Tower (7, Grimoire) → Temple (6, Pantheon) → Farm (2, Garden)
#      → Bank (5, Stock Market). Pantheon also gets its gods slotted on unlock.
#   2. Farm → level 9 (max garden grid).
#   3. Cursor → level 12 (Stock Market HQ / glove bonuses).
#   4. Spread everything else toward level 10 (each level = +1% that building's
#      CpS; level 10 also grants an achievement → more milk).
#
# arguments[0] = max level to push buildings to in the "spread" phase (e.g. 10).
SPEND_SUGAR_LUMPS = """
var spreadCap = arguments[0] || 10;
// No lump-spend confirmation prompts (would block headless / freeze the UI).
if (Game.prefs) Game.prefs.askLumps = 0;

function canAfford(obj) { return Game.lumps >= obj.level + 1; }
function tryLevel(obj) {
    if (obj && canAfford(obj)) {
        var was = obj.level;
        obj.levelUp(false);
        if (obj.level > was) {
            // The pantheon is slotted by SET_PANTHEON on the minigame tick (it
            // owns the correct slots + swap-safety), so no slotting here — this
            // just unlocks the Temple's minigame by reaching level 1.
            return true;
        }
    }
    return false;
}

// 1. Minigame unlocks (value order).
var unlockOrder = [7, 6, 2, 5];
for (var i = 0; i < unlockOrder.length; i++) {
    var o = Game.ObjectsById[unlockOrder[i]];
    if (o && o.level == 0) { if (tryLevel(o)) return true; else return false; }
}

// 2. Farm to level 9 (garden grid size).
var farm = Game.ObjectsById[2];
if (farm && farm.level < 9) { return tryLevel(farm); }

// 3. Cursor to level 12 (stock HQ / gloves).
var cursor = Game.ObjectsById[0];
if (cursor && cursor.level < 12) { return tryLevel(cursor); }

// 4. Spread: level the lowest building toward spreadCap (cheapest = most value
//    per lump, and evens out the +1%/level bonuses).
var best = null;
for (var key in Game.Objects) {
    var b = Game.Objects[key];
    if (b.amount > 0 && b.level < spreadCap) {
        if (best === null || b.level < best.level) best = b;
    }
}
if (best) return tryLevel(best);
return false;
"""

CHECK_STOCK_MARKET = """
var bank = Game.ObjectsById[5].minigame;
if (!bank) return;
// Tier-keyed buy-low / sell-high. Higher-tier goods have wider price bands.
var tiers = [
    { idxMin: 12, idxMax: 99, buyBelow: 10, sellAbove: 100 },
    { idxMin: 6,  idxMax: 11, buyBelow: 5,  sellAbove: 80 },
    { idxMin: 0,  idxMax: 5,  buyBelow: 2,  sellAbove: 60 }
];
for (var i = 0; i < bank.goodsById.length; i++) {
    var good = bank.goodsById[i];
    var maxStock = bank.getGoodMaxStock(good);
    for (var t = 0; t < tiers.length; t++) {
        var cfg = tiers[t];
        if (i < cfg.idxMin || i > cfg.idxMax) continue;
        if (good.stock != maxStock && good.val < cfg.buyBelow) bank.buyGood(i, maxStock);
        if (good.stock != 0 && good.val > cfg.sellAbove) bank.sellGood(i, good.stock);
        break;
    }
}
"""

# Close any leftover dragon/Santa special popup or prompt the game may have
# opened (the cause of the "dialog stays open" hang). Only ever CLOSES — it
# checks the popup is actually on-screen before toggling, so it never opens one.
# Close only a blocking Game.Prompt overlay (e.g. a confirm from UpgradeDragon).
# We deliberately do NOT touch the dragon/Santa "special" popup here: calling
# Game.ToggleSpecialMenu re-rendered it OPEN with stale data on the live build
# (the "stuck younger-Krumblor menu"), and the bot never needs that popup — it
# sets auras by writing Game.dragonAura directly and trains via Game.UpgradeDragon.
_CLOSE_SPECIAL = """
try { if (typeof Game.ClosePrompt === 'function') Game.ClosePrompt(); } catch (e) {}
"""

# One-shot cleanup for a special popup left stuck open by an earlier run (or the
# old ToggleSpecialMenu bug). Closes it the way the game does — by removing the
# 'onScreen' class — and CLEARS any inline display override (incl. a stale
# display:none a previous version may have set) so the player can open it normally
# again. Never opens or rebuilds it. Run once at startup. Returns wasOpen.
CLEAR_STUCK_SPECIAL_MENU = """
var wasOpen = false;
try {
    if (typeof Game.ClosePrompt === 'function') Game.ClosePrompt();
    var pop = (typeof l === 'function') ? l('specialPopup') : null;
    if (pop) {
        var cn = pop.className || '';
        wasOpen = cn.indexOf('onScreen') >= 0 || pop.style.display === 'block';
        pop.className = cn.replace(/\\bonScreen\\b/g, '').trim();
        pop.style.display = '';   // clear inline override; let the game's CSS drive it
    }
} catch (e) {}
return wasOpen;
"""

# Level up Krumblor as far as is affordable AND safe in one go (verified against
# live main.js Game.dragonLevels / Game.UpgradeDragon). Loops so a big bank rips
# through the cheap egg/training levels in a single tick instead of one per tick.
#   - cost() returns a BOOLEAN "requirement met" (e.g. Game.cookies>=N, or
#     "own >=50 of every building"), not a cookie amount.
#   - Aura-training levels carry no cost/buy function (advanced by picking an aura
#     in the UI); we stop there ('needs_aura') rather than guess.
#   - Sacrifice levels permanently sacrifice N of EVERY building. Taken only when
#     (a) every building keeps >= keep units afterward AND (b) rebuying the whole
#     sacrifice costs <= sacFrac of the current bank (0 = ignore the cost gate).
# args: keep (int), sacFrac (float). Returns {trained:[names...], maxed, blocked,
# needs_aura, waiting}.
DRAGON_TRAIN = """
var keep = arguments[0];
var sacFrac = arguments[1];
var out = {trained: [], maxed: false, locked: false, blocked: null, needs_aura: null, waiting: null};
if (!Game.Has || !Game.Has('How to bake your dragon')) { out.locked = true; return out; }
var levels = Game.dragonLevels;
for (var guard = 0; guard < 60; guard++) {
    var lvl = Game.dragonLevel;
    if (!levels || lvl >= levels.length - 1) { out.maxed = true; break; }
    var me = levels[lvl];
    if (typeof me.cost !== 'function' || typeof me.buy !== 'function') {
        out.needs_aura = {level: lvl, name: me.name}; break;
    }
    if (!me.cost()) { out.waiting = {level: lvl, name: me.name}; break; }
    var sm = me.buy.toString().match(/\\.sacrifice\\((\\d+)\\)/);
    if (sm) {
        var n = parseInt(sm[1]);
        var rebuy = 0, unsafe = null;
        for (var i in Game.Objects) {
            var o = Game.Objects[i];
            if (o.amount < keep + n) { unsafe = {building: o.name, need: keep + n}; break; }
            rebuy += (typeof o.getSumPrice === 'function') ? o.getSumPrice(n) : 0;
        }
        if (unsafe) { unsafe.level = lvl; unsafe.name = me.name; out.blocked = unsafe; break; }
        if (sacFrac > 0 && rebuy > Game.cookies * sacFrac) {
            out.blocked = {level: lvl, name: me.name, reason: 'rebuy-too-pricey', rebuy: rebuy}; break;
        }
    }
    Game.UpgradeDragon();             // re-checks cost() then buy()s; increments dragonLevel
    if (Game.dragonLevel > lvl) out.trained.push(me.name);
    else { out.waiting = {level: lvl, name: me.name}; break; }   // didn't advance — avoid a spin
}
out.level = Game.dragonLevel;
out.max = levels ? levels.length - 1 : 0;
""" + _CLOSE_SPECIAL + """
return out;
"""

# Equip the golden-cookie-combo dragon auras as they become available. An aura is
# unlocked once the dragon has passed the level that grants it: in main.js auras
# unlock one-per-level past the egg stages, so the highest unlocked aura id is
# (Game.dragonLevel - 4). The SECOND aura slot only exists on a fully trained
# dragon. We never call SetDragonAura on a locked aura, so a fresh/under-leveled
# dragon equips nothing (no more wrongly equipping a late aura on an egg).
# args: ordered aura NAMES (prefs[0] -> slot 0, prefs[1] -> slot 1). Names are
# resolved to ids off Game.dragonAuras at runtime. Returns what (if any) changed.
SET_DRAGON_AURAS = """
var prefs = arguments[0] || [];
var out = {ok: false, set: [], changed: [], pending: [], missing: [], failed: [],
           equipped: [], slots: 0, dragonLevel: null, dragonMax: 0,
           unlockedMax: null, noSetFn: false};
if (typeof Game === 'undefined' || !Game.dragonAuras || !Game.dragonLevels) return out;
out.dragonLevel = Game.dragonLevel;
out.dragonMax = Game.dragonLevels.length - 1;
var unlockedMax = Game.dragonLevel - 4;                 // highest unlocked aura id
out.unlockedMax = unlockedMax;
var fullyTrained = Game.dragonLevel >= Game.dragonLevels.length - 1;
out.slots = fullyTrained ? 2 : 1;                       // 2nd slot needs the maxed dragon
function auraId(name) {
    for (var k in Game.dragonAuras) {
        var a = Game.dragonAuras[k];
        if (a && a.name === name) return (a.id !== undefined) ? a.id : (k | 0);
    }
    return -1;
}
function auraName(id) {
    for (var k in Game.dragonAuras) {
        var a = Game.dragonAuras[k];
        if (a && ((a.id !== undefined ? a.id : (k | 0)) === id)) return a.name;
    }
    return '';
}
for (var s = 0; s < prefs.length; s++) {
    var id = auraId(prefs[s]);
    if (id < 0) { out.missing.push(prefs[s]); continue; }        // no such aura in this build
    if (s >= out.slots || id > unlockedMax) { out.pending.push(prefs[s]); continue; }  // slot/aura locked
    var cur = (s === 0) ? Game.dragonAura : Game.dragonAura2;
    if (cur === id) { out.set.push(prefs[s]); continue; }        // already equipped
    // Assign the field directly. Game.SetDragonAura(aura, slot) opens a Confirm
    // prompt (the "stuck dialog") and doesn't apply synchronously — setting the
    // field is exactly what that prompt's Confirm button does.
    if (s === 0) Game.dragonAura = id; else Game.dragonAura2 = id;
    var now = (s === 0) ? Game.dragonAura : Game.dragonAura2;    // verify it took
    if (now === id) { out.set.push(prefs[s]); out.changed.push(prefs[s]); }
    else out.failed.push(prefs[s]);
}
if (out.changed.length && typeof Game.CalculateGains === 'function') Game.CalculateGains();
// Report the actually-equipped aura names (for the status panel).
var n0 = auraName(Game.dragonAura); if (n0 && n0 !== 'No aura') out.equipped.push(n0);
var n1 = auraName(Game.dragonAura2); if (n1 && n1 !== 'No aura') out.equipped.push(n1);
""" + _CLOSE_SPECIAL + """
out.ok = true;
return out;
"""

# Seasonal collectibles come from the game's own per-season DROP ARRAYS, not the
# `.season` tag (which most builds leave '' on the actual upgrades). These are the
# canonical lists the game rolls drops from:
#   valentines -> heartDrops (bought directly from the store — instant)
#   halloween  -> halloweenDrops (RNG off wrinklers + golden cookies)
#   easter     -> easterEggs (RNG off golden cookies; the biggest set, ~20)
#   christmas  -> reindeerDrops (RNG off popping reindeer) + Santa leveling
# Feature-detected: a missing array just yields an empty list for that season.
_SEASON_DROPS_JS = """
function dropNames(arr) {
    var o = [];
    if (arr) for (var i = 0; i < arr.length; i++) {
        var e = arr[i];
        if (typeof e === 'string') o.push(e);
        else if (e && e.name) o.push(e.name);
    }
    return o;
}
var DROPS = {
    christmas: dropNames(Game.reindeerDrops),
    halloween: dropNames(Game.halloweenDrops),
    easter: dropNames(Game.easterEggs),
    valentines: dropNames(Game.heartDrops)
};
"""

# In the CURRENT season: buy every available collectible (cheapest first, keeping
# the reserve) and level Santa during Christmas; then report per-season owned /
# total / still-buyable so Python can drive the dwell + switch policy.
# args: reserveSeconds. Returns {ok, hasSwitcher, season, santaLevel, santaMax,
# bought, santa, counts:{season:{owned,total,buyable}}, dropLens:{season:n}}.
SEASON_COLLECT = ("""
var reserveSeconds = arguments[0] || 0;
var out = {ok: false, hasSwitcher: false, season: '', santaLevel: -1, santaMax: 0,
           bought: 0, santa: 0, counts: {}, dropLens: {}};
if (typeof Game === 'undefined' || !Game.ready) return out;
out.season = Game.season || '';
out.hasSwitcher = !!(Game.Has && Game.Has('Season switcher'));
var reserve = (Game.cookiesPs || 0) * reserveSeconds;
""" + _SEASON_DROPS_JS + """
function tally(names) {
    var owned = 0, buyable = 0;
    for (var i = 0; i < names.length; i++) {
        var u = Game.Upgrades[names[i]];
        if (!u) continue;
        if (u.bought) owned++;
        else if (u.unlocked) buyable++;
    }
    return {owned: owned, total: names.length, buyable: buyable};
}
for (var s in DROPS) { out.counts[s] = tally(DROPS[s]); out.dropLens[s] = DROPS[s].length; }

out.santaMax = Game.santaLevels ? Game.santaLevels.length - 1 : 14;
out.santaLevel = (typeof Game.santaLevel === 'number') ? Game.santaLevel : -1;

var cur = out.season;
// Buy the current season's available collectibles, cheapest first, keep reserve.
if (cur && DROPS[cur]) {
    var avail = [];
    for (var i = 0; i < DROPS[cur].length; i++) {
        var u = Game.Upgrades[DROPS[cur][i]];
        if (u && u.unlocked && !u.bought) avail.push(u);
    }
    avail.sort(function(a, b) { return a.getPrice() - b.getPrice(); });
    for (var i = 0; i < avail.length; i++) {
        var p = avail[i].getPrice();
        if (Game.cookies - p < reserve) continue;
        avail[i].buy(1);
        out.bought++;
    }
}
// Christmas: level Santa (unlocks the Santa upgrade chain for the normal buyer).
if (cur === 'christmas' && typeof Game.santaLevel === 'number'
    && typeof Game.UpgradeSanta === 'function') {
    var guard = 0;
    while (Game.santaLevel < out.santaMax && guard < 30) {
        var sp = Game.santaPrice;
        if (typeof sp === 'number' && isFinite(sp) && (Game.cookies - sp) < reserve) break;
        var before = Game.santaLevel;
        Game.UpgradeSanta();
        if (Game.santaLevel === before) break;
        out.santa++; guard++;
    }
    out.santaLevel = Game.santaLevel;
}
out.ok = true;
return out;
""")

# Enter a season by toggling its switch biscuit (respecting the reserve). Returns
# {ok, season, reason}. reason: '' on success, else 'no-switcher' / 'unknown-season'
# / 'biscuit-locked' / 'reserve' / 'no-effect'.
ENTER_SEASON = """
var name = arguments[0];
var reserveSeconds = arguments[1] || 0;
var out = {ok: false, season: (typeof Game !== 'undefined' ? Game.season : ''), reason: ''};
if (typeof Game === 'undefined' || !Game.ready) { out.reason = 'not-ready'; return out; }
if (!Game.Has || !Game.Has('Season switcher')) { out.reason = 'no-switcher'; return out; }
var BISCUIT = {christmas: 'Festive biscuit', halloween: 'Ghostly biscuit',
               valentines: 'Lovesick biscuit', easter: 'Bunny biscuit'};
var bn = BISCUIT[name];
if (!bn) { out.reason = 'unknown-season'; return out; }
var b = Game.Upgrades[bn];
if (!b || !b.unlocked) { out.reason = 'biscuit-locked'; return out; }
var reserve = (Game.cookiesPs || 0) * reserveSeconds;
var p = (typeof b.getPrice === 'function') ? b.getPrice() : 0;
if (Game.cookies - p < reserve) { out.reason = 'reserve'; return out; }
b.buy(1);
out.season = Game.season;
out.ok = (Game.season === name);
if (!out.ok) out.reason = 'no-effect';
return out;
"""

# One-shot ground-truth dump of the live dragon + season API, logged once at
# startup so we can see exactly what this game build exposes (the bot can't be
# observed from the dev box). Pure reads; never mutates anything.
DIAGNOSE_DRAGON_SEASON = """
var d = {};
try {
    d.hasDragon = !!(Game.Has && Game.Has('How to bake your dragon'));
    d.dragonLevel = Game.dragonLevel;
    d.dragonLevelsLen = Game.dragonLevels ? Game.dragonLevels.length : null;
    d.dragonAura = Game.dragonAura;
    d.dragonAura2 = Game.dragonAura2;
    d.setDragonAuraType = typeof Game.SetDragonAura;
    d.upgradeDragonType = typeof Game.UpgradeDragon;
    // Is the special (dragon/Santa) popup currently open, and what is it showing?
    var pop = (typeof l === 'function') ? l('specialPopup') : null;
    d.specialPopup = pop
        ? {className: pop.className || '', display: (pop.style ? pop.style.display : ''),
           onScreen: (pop.className || '').indexOf('onScreen') >= 0}
        : 'absent';
    d.specialTab = (typeof Game.specialTab !== 'undefined') ? Game.specialTab : 'undef';
    var auras = [];
    for (var k in Game.dragonAuras) {
        var a = Game.dragonAuras[k];
        var dsc = (a && a.desc) ? ('' + a.desc).replace(/<[^>]*>/g, ' ').slice(0, 80) : '';
        auras.push(k + ':' + (a ? a.name : '?') + (dsc ? ' [' + dsc + ']' : ''));
    }
    d.auras = auras;
} catch (e) { d.dragonErr = '' + e; }
try {
    d.hasSwitcher = !!(Game.Has && Game.Has('Season switcher'));
    d.season = Game.season;
    var sc = {};
    for (var k in Game.Upgrades) {
        var u = Game.Upgrades[k];
        if (!u.season || u.pool === 'switch') continue;
        if (!sc[u.season]) sc[u.season] = {owned: 0, total: 0};
        sc[u.season].total++; if (u.bought) sc[u.season].owned++;
    }
    d.seasonCounts = sc;
    var names = ['Festive biscuit', 'Ghostly biscuit', 'Lovesick biscuit', 'Bunny biscuit', "Fool's biscuit"];
    var biscuits = {};
    for (var i = 0; i < names.length; i++) {
        var u = Game.Upgrades[names[i]];
        biscuits[names[i]] = u
            ? {unlocked: !!u.unlocked, bought: !!u.bought, pool: u.pool,
               price: (typeof u.getPrice === 'function') ? u.getPrice() : null}
            : false;
    }
    d.biscuits = biscuits;
    d.santaLevel = Game.santaLevel;
    d.upgradeSantaType = typeof Game.UpgradeSanta;
    // Any Christmas/festive/Santa/reindeer upgrade — find "Festive test tube" and
    // see why it isn't bought (locked? not in season? unparseable? a pool we skip?).
    var fest = [];
    for (var k in Game.Upgrades) {
        var u = Game.Upgrades[k];
        if (!/festive|test tube|reindeer|santa|christmas|snow|joll|merri/i.test(u.name)) continue;
        fest.push({name: u.name, pool: u.pool, season: u.season || '',
                   unlocked: !!u.unlocked, bought: !!u.bought,
                   inStore: (Game.UpgradesInStore || []).indexOf(u) >= 0});
    }
    d.festiveUpgrades = fest;
    // The per-season drop arrays the new season logic relies on. Report each
    // array's length + how many we already own, so we can confirm the names and
    // see remaining collectibles per season.
    function arrInfo(arr) {
        if (!arr) return null;
        var names = [], owned = 0;
        for (var i = 0; i < arr.length; i++) {
            var e = arr[i];
            var nm = (typeof e === 'string') ? e : (e && e.name);
            if (!nm) continue;
            names.push(nm);
            var u = Game.Upgrades[nm];
            if (u && u.bought) owned++;
        }
        return {len: names.length, owned: owned, sample: names.slice(0, 3)};
    }
    d.dropArrays = {
        reindeerDrops: arrInfo(Game.reindeerDrops),
        halloweenDrops: arrInfo(Game.halloweenDrops),
        easterEggs: arrInfo(Game.easterEggs),
        heartDrops: arrInfo(Game.heartDrops),
        santaDrops: arrInfo(Game.santaDrops)
    };
} catch (e) { d.seasonErr = '' + e; }
return d;
"""

# Reliability self-check: probe each subsystem's required live-game API and return
# 'ok' / 'FAIL' / 'err'. Logged once at startup so a build mismatch (the kind that
# silently broke auras / seasons) surfaces immediately instead of via a bug report.
SELF_CHECK = """
var r = {};
function chk(c){ return c ? 'ok' : 'FAIL'; }
try { r.dragon = chk(Game.dragonAuras && Game.dragonLevels && typeof Game.UpgradeDragon === 'function'); } catch(e){ r.dragon = 'err'; }
try { r.dragonAuraSettable = chk(typeof Game.dragonAura === 'number'); } catch(e){ r.dragonAuraSettable = 'err'; }
try {
    var drops = !!(Game.reindeerDrops && Game.halloweenDrops && Game.easterEggs && Game.heartDrops);
    r.season = chk(typeof Game.season !== 'undefined' && Game.Has) + (drops ? '' : ' (drops-missing)');
} catch(e){ r.season = 'err'; }
try { r.santa = chk(typeof Game.UpgradeSanta === 'function' && typeof Game.santaLevel === 'number'); } catch(e){ r.santa = 'err'; }
try { r.wrinklers = chk(Game.wrinklers && typeof Game.getWrinklersMax === 'function'); } catch(e){ r.wrinklers = 'err'; }
try { r.golden = chk(Game.shimmers && Game.shimmerTypes && Game.shimmerTypes['golden']); } catch(e){ r.golden = 'err'; }
// Minigames only exist once the building is leveled (a sugar lump). 'locked' is
// expected on a fresh game and is NOT a failure — only a present-but-broken API is.
function mg(name, ok) {
    try {
        var o = Game.Objects[name];
        if (!o) return 'no-building';
        if (!o.minigame) return 'locked';
        return ok(o.minigame) ? 'ok' : 'FAIL';
    } catch (e) { return 'err'; }
}
r.grimoire = mg('Wizard tower', function(m){ return !!(m.spellsById && m.spellsById[1]); });
r.pantheon = mg('Temple', function(m){ return !!m.slot; });
r.garden = mg('Farm', function(m){ return !!m.plantsById; });
try { r.heavenly = chk(typeof Game.heavenlyChips === 'number' && typeof Game.UpgradesById === 'object'); } catch(e){ r.heavenly = 'err'; }
return r;
"""

# Discovery dump for the (not-yet-built) prestige layer: heavenly chips, the
# heavenly-upgrade pool ('prestige'), the cheapest unbought-but-unlocked ones with
# their chip cost, the permanent-upgrade slots, and the typeof candidate buy/assign
# functions — so the heavenly auto-buyer is built against the real API. Pure reads.
DIAGNOSE_HEAVENLY = """
var d = {};
try {
    d.heavenlyChips = Game.heavenlyChips;
    d.heavenlyChipsEarned = Game.heavenlyChipsEarned;
    d.prestige = Game.prestige;
    var owned = 0, total = 0, avail = [];
    for (var k in Game.Upgrades) {
        var u = Game.Upgrades[k];
        if (u.pool !== 'prestige') continue;
        total++;
        if (u.bought) { owned++; continue; }
        if (u.unlocked) avail.push({name: u.name, id: u.id, cost: u.basePrice,
                                    canAfford: Game.heavenlyChips >= u.basePrice});
    }
    d.prestigeUpgrades = {owned: owned, total: total, unlockedUnbought: avail.length};
    avail.sort(function(a, b){ return a.cost - b.cost; });
    d.nextHeavenly = avail.slice(0, 10);
    // How do you BUY one / ASSIGN a permanent slot? Report typeofs to pick the API.
    d.fns = {
        upgradeBuy: (Game.UpgradesById && Game.UpgradesById[0]) ? typeof Game.UpgradesById[0].buy : 'n/a',
        PurchaseHeavenlyUpgrade: typeof Game.PurchaseHeavenlyUpgrade,
        BuildAscendTree: typeof Game.BuildAscendTree,
        AssignPermanentUpgrade: typeof Game.AssignPermanentUpgrade,
        ascendMetaType: typeof Game.ascendMeta
    };
    d.permanentUpgrades = Game.permanentUpgrades ? Game.permanentUpgrades.slice() : 'absent';
    // How many permanent slots are unlocked (heavenly 'Permanent upgrade slot I..V').
    var slotNames = ['Permanent upgrade slot I','Permanent upgrade slot II','Permanent upgrade slot III','Permanent upgrade slot IV','Permanent upgrade slot V'];
    var slots = 0;
    for (var i = 0; i < slotNames.length; i++) { var su = Game.Upgrades[slotNames[i]]; if (su && su.bought) slots++; }
    d.permanentSlotsOwned = slots;
} catch (e) { d.err = '' + e; }
return d;
"""

# Spend heavenly chips on heavenly (pool 'prestige') upgrades, cheapest unlocked
# first (which naturally walks the prereq tree). Uses Game.PurchaseHeavenlyUpgrade
# when present and VERIFIES each buy took (u.bought) — if it didn't, we stop and
# report, so "needs the ascend screen" or a wrong API surfaces instead of spinning.
# args: optional deny-list of names to skip. Returns what was bought + chips left.
BUY_HEAVENLY_UPGRADES = """
var deny = {};
(arguments[0] || []).forEach(function(n){ deny[n] = 1; });
var out = {ok: false, bought: [], failed: '', chips: 0, owned: 0, total: 0, fn: ''};
if (typeof Game === 'undefined' || typeof Game.heavenlyChips !== 'number') return out;
var hasFn = typeof Game.PurchaseHeavenlyUpgrade === 'function';
out.fn = hasFn ? 'PurchaseHeavenlyUpgrade' : 'buy';
var guard = 0;
while (guard++ < 300) {
    var best = null;
    for (var k in Game.Upgrades) {
        var u = Game.Upgrades[k];
        if (u.pool !== 'prestige' || u.bought || !u.unlocked || deny[u.name]) continue;
        if (Game.heavenlyChips < u.basePrice) continue;
        if (best === null || u.basePrice < best.basePrice) best = u;
    }
    if (!best) break;
    if (hasFn) Game.PurchaseHeavenlyUpgrade(best); else if (best.buy) best.buy();
    if (best.bought) out.bought.push(best.name);
    else { out.failed = best.name; break; }   // buy didn't take — stop, report
}
// tallies for the status panel
for (var k in Game.Upgrades) {
    var u = Game.Upgrades[k];
    if (u.pool !== 'prestige') continue;
    out.total++; if (u.bought) out.owned++;
}
out.chips = Game.heavenlyChips;
if (out.bought.length && typeof Game.CalculateGains === 'function') Game.CalculateGains();
out.ok = true;
return out;
"""

ASCEND_INFO = """
var buffed = false;
for (var b in Game.buffs) {
    var bf = Game.buffs[b];
    if (bf && ((bf.multCpS && bf.multCpS > 1) || (bf.multClick && bf.multClick > 1))) { buffed = true; break; }
}
return {
    prestige: Game.prestige,
    potential: Game.HowMuchPrestige(Game.cookiesReset + Game.cookiesEarned),
    buffed: buffed,
    shimmers: Game.shimmers ? Game.shimmers.length : 0
};
"""

# Force ascension (the 1 arg skips the confirm), then complete the rebirth a
# moment later once the ascension screen has processed. Heavenly chips persist.
# Ascend, then RETRY the reincarnation every second until we're actually off the
# ascension screen (a single delayed Reincarnate() can no-op if the screen isn't
# ready yet — that left the bot idling on the ascend screen for minutes). Bypasses
# the confirm (arg 1) and closes any leftover prompt.
DO_ASCEND = """
Game.Ascend(1);
if (window._reincTimer) clearInterval(window._reincTimer);
var tries = 0;
window._reincTimer = setInterval(function() {
    tries++;
    if (Game.OnAscend) {
        if (typeof Game.ClosePrompt === 'function') Game.ClosePrompt();
        Game.Reincarnate(1);
    }
    if (!Game.OnAscend || tries >= 30) clearInterval(window._reincTimer);
}, 1000);
"""

# Force-finish a reincarnation if we're still stuck on the ascension screen
# (Python-side safety net, called from the ascend tick). Returns whether it acted.
FINISH_ASCENSION = """
if (typeof Game !== 'undefined' && Game.OnAscend) {
    if (typeof Game.ClosePrompt === 'function') Game.ClosePrompt();
    Game.Reincarnate(1);
    return true;
}
return false;
"""

GET_SAVE_DATA = "return Game.WriteSave(1);"
LOAD_SAVE_DATA = "return Game.LoadSave(arguments[0]);"
HARD_RESET = "Game.HardReset(2);"

# Pops every attached wrinkler that has eaten something. 1.1x return on what
# they ate (3x for shiny wrinklers). Off by default — popping early forfeits
# the +0.5%/wrinkler growth bonus from letting them eat.
ACHIEVEMENTS_OWNED_COUNT = "return Game.AchievementsOwned || 0;"

ACHIEVEMENT_OWNED = """
var ach = Game.Achievements && Game.Achievements[arguments[0]];
if (!ach) return null;
return ach.won == 1;
"""

POP_WRINKLERS = """
if (Game.wrinklers) {
    for (var i = 0; i < Game.wrinklers.length; i++) {
        var w = Game.wrinklers[i];
        if (w && w.phase == 2 && w.sucked > 0) {
            w.hp = 0;
        }
    }
}
"""

# Attached-wrinkler snapshot for the pop policy: how many are attached (phase 2),
# the max slots (Game.getWrinklersMax accounts for Elder Spice / Dragon Guts), the
# total cookies they've digested, how many are shiny (type 1), and the live season
# (so we can farm spooky cookies during Halloween without depending on the season
# tick). Pure read.
WRINKLER_STATE = """
var out = {count: 0, max: 10, sucked: 0, shiny: 0, halloweenDone: true,
           season: (typeof Game !== 'undefined' ? (Game.season || '') : '')};
if (typeof Game === 'undefined' || !Game.wrinklers) return out;
if (typeof Game.getWrinklersMax === 'function') out.max = Game.getWrinklersMax();
// Are all 7 Halloween wrinkler-drop cookies already owned? If so there's no
// drop left to farm, so popping during Halloween is pure loss (holding pays
// 1.1x). Only while incomplete is Halloween popping worth it.
if (Game.halloweenDrops) {
    out.halloweenDone = true;
    for (var h = 0; h < Game.halloweenDrops.length; h++) {
        var u = Game.Upgrades[Game.halloweenDrops[h]];
        if (u && !u.bought) { out.halloweenDone = false; break; }
    }
}
for (var i = 0; i < Game.wrinklers.length; i++) {
    var w = Game.wrinklers[i];
    if (!w || w.phase != 2) continue;
    out.count++;
    out.sucked += w.sucked || 0;
    if (w.type == 1) out.shiny++;
}
return out;
"""

# Pop wrinklers only while a CpS-multiplying buff (Frenzy, Elder Frenzy, etc.)
# is active. Detected via multCpS > 1 rather than buff names, so it covers any
# present or future multiplier buff. Returns true if anything was popped.
POP_WRINKLERS_IF_FRENZY = """
var frenzy = false;
for (var name in Game.buffs) {
    var b = Game.buffs[name];
    if (b && b.multCpS && b.multCpS > 1) { frenzy = true; break; }
}
if (!frenzy || !Game.wrinklers) return false;
var popped = false;
for (var i = 0; i < Game.wrinklers.length; i++) {
    var w = Game.wrinklers[i];
    if (w && w.phase == 2 && w.sucked > 0) { w.hp = 0; popped = true; }
}
return popped;
"""
