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

START_AUTOCLICK_COOKIE = """
if (window._autoClickCookie) clearInterval(window._autoClickCookie);
window._autoClickCookie = setInterval(function() { Game.ClickCookie(); }, arguments[0]);
"""

START_AUTOCLICK_GOLDEN = """
if (window._autoGolden) clearInterval(window._autoGolden);
window._autoGolden = setInterval(function() {
    while (Game.shimmers.length > 0) Game.shimmers[0].pop();
}, arguments[0]);
"""

# One round-trip snapshot of everything we evaluate per purchase tick.
GAME_SNAPSHOT = """
return {
    cookies: Game.cookies,
    cookiesPs: Game.cookiesPs,
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
    // key. Prefer dname so the UI never shows an internal id.
    return [u.id, u.desc, u.basePrice, u.dname || u.name];
});
"""

COUNT_GOLDEN_COOKIE_UPGRADES = """
var ids = arguments[0];
var total = 0;
for (var i = 0; i < ids.length; i++) {
    if (Game.UpgradesById[ids[i]].bought == 1) total++;
}
return total;
"""

BUY_BUILDING = "Game.Objects[arguments[0]].buy(arguments[1]);"
BUY_UPGRADE = "Game.UpgradesById[arguments[0]].click(event);"

# Click the news ticker iff a clickable fortune is currently showing.
# Gated on the 'Fortune cookies' heavenly upgrade — without it the game can't
# spawn fortunes at all (main.js L7858), so polling is wasted otherwise.
# We deliberately do NOT call Game.getNewTicker() to force extra rolls: a
# player tapping the ticker triggers a manual reroll that skips the fortune
# check, so force-rolling here would be doing something the UI can't do.
CLICK_TICKER_FORTUNE_IF_PRESENT = """
if (!Game.Has || !Game.Has('Fortune cookies')) return false;
if (Game.TickerEffect && Game.TickerEffect.type === 'fortune') {
    Game.tickerL.click();
    return true;
}
return false;
"""

CALCULATE_ACHIEVEMENT_BUILDINGS = """
var achievementList = [1, 15, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600, 650, 700, 800, 900, 1000];
return Object.values(Game.Objects).map(function(b) {
    for (var i = 0; i < achievementList.length; i++) {
        var diff = achievementList[i] - b.amount;
        if (diff > 0 && diff < 51) {
            if (b.getSumPrice(diff) < Game.cookiesPs * 10) {
                return [b.name, diff];
            }
        }
    }
    return null;
}).filter(function(x) { return x !== null; });
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

function activeFrenzyBuffs(extraNames) {
    var names = FRENZY_BUFFS.concat(extraNames || []);
    var hits = [];
    for (var n = 0; n < names.length; n++) {
        if (Game.buffs[names[n]]) hits.push(Game.buffs[names[n]]);
    }
    return hits;
}

if (activeFrenzyBuffs().length >= 2) {
    var wiz = Game.ObjectsById[7].minigame;
    if (wiz) {
        wiz.castSpell(wiz.spellsById[1]);
        setTimeout(function() {
            if (activeFrenzyBuffs(["Click frenzy", "Dragonflight"]).length >= 3) {
                Game.ObjectsById[7].sell(400);
                var bank = Game.ObjectsById[5].minigame;
                if (bank) {
                    bank.takeLoan(1); bank.takeLoan(2); bank.takeLoan(3);
                }
                wiz.castSpell(wiz.spellsById[1]);
            }
        }, 1000);
    }
}
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

SET_PANTHEON = """
var temple = Game.ObjectsById[6];
if (temple.level != 0 && temple.minigame) {
    try {
        temple.minigame.slotGod(temple.minigame.godsById[1], 1);
        temple.minigame.slotGod(temple.minigame.godsById[6], 2);
        temple.minigame.slotGod(temple.minigame.godsById[8], 3);
    } catch (error) {}
}
"""

SPEND_SUGAR_LUMPS = """
if (Game.lumps > 1) {
    var order = [7, 6, 2, 5];
    for (var k = 0; k < order.length; k++) {
        var obj = Game.ObjectsById[order[k]];
        if (obj && obj.level == 0) {
            obj.levelUp();
            if (order[k] == 6 && obj.minigame) {
                try {
                    obj.minigame.slotGod(obj.minigame.godsById[1], 1);
                    obj.minigame.slotGod(obj.minigame.godsById[6], 2);
                    obj.minigame.slotGod(obj.minigame.godsById[8], 3);
                } catch (error) {}
            }
            break;
        }
    }
}
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

# Level up Krumblor one step if it's affordable and safe. Middle levels call
# Game.Objects[name].sacrifice(100) (permanent), detected by inspecting the
# level's buy() source; such a level is only taken when the building keeps at
# least arguments[0] units after the sacrifice. Requires the dragon to be
# unlocked. Returns a small status object.
DRAGON_TRAIN = """
var keep = arguments[0];
if (!Game.Has || !Game.Has('How to bake your dragon')) return {locked: true};
var levels = Game.dragonLevels;
var lvl = Game.dragonLevel;
if (!levels || lvl >= levels.length - 1) return {maxed: true, level: lvl};
var me = levels[lvl];
if (!me.cost()) return {waiting: true, level: lvl, name: me.name};
var buyStr = me.buy.toString();
if (buyStr.indexOf('sacrifice') >= 0) {
    var m = buyStr.match(/Objects\\['([^']+)'\\]\\.sacrifice\\((\\d+)\\)/);
    if (m) {
        var bname = m[1], n = parseInt(m[2]);
        if (Game.Objects[bname].amount < keep + n) {
            return {blocked: true, level: lvl, name: me.name, building: bname, need: keep + n};
        }
    }
}
Game.UpgradeDragon();
return {trained: true, level: Game.dragonLevel, name: me.name};
"""

ASCEND_INFO = """
return {
    prestige: Game.prestige,
    potential: Game.HowMuchPrestige(Game.cookiesReset + Game.cookiesEarned)
};
"""

# Force ascension (the 1 arg skips the confirm), then complete the rebirth a
# moment later once the ascension screen has processed. Heavenly chips persist.
DO_ASCEND = """
Game.Ascend(1);
setTimeout(function() { Game.Reincarnate(1); }, 1500);
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
