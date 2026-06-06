"""Garden minigame decision logic.

Pure functions (no Selenium): given a garden snapshot dict (from
``scripts.GET_GARDEN_STATE``) they return a list of action dicts that
``scripts.GARDEN_ACTIONS`` applies. Kept browser-free so it's unit-testable.

Two phases, chosen automatically from the snapshot:

  BREEDING — while the chosen strategy's plants aren't all unlocked yet. Switch
  soil to mutation-favoring Wood chips (3x spread/mutation, when ≥300 farms),
  plant a checkerboard of the relevant *unlocked parent* plants (any unlocked
  plant that is a parent of a still-locked plant, read live from each plant's
  ``children``), and leave the alternating tiles empty so mutations can roll
  there. A seed unlocks when a mature plant of its type is HARVESTED, so we
  harvest mature mutants off the empty tiles. This is a robust heuristic, not an
  optimal mutation solver: it climbs the tree over time but does not guarantee
  the rare 2-parent recipes (e.g. Juicy Queenbeet).

  STEADY — once those plants are unlocked. Switch soil to Clay (+25% plant
  effects, when ≥100 farms) and fill the grid with the strategy's layout,
  replanting empties and clearing leftover breeding plants.

The seed log is never sacrificed (``M.convert`` is never called), and the garden
is never frozen (``M.freeze`` suppresses plant effects).
"""
from __future__ import annotations

# Plants each steady-state strategy needs unlocked, by plant ``key``. Breeding
# runs until all of a strategy's plants are unlocked.
STRATEGY_PLANTS = {
    "cps": ("queenbeet", "elderwort"),
    "golden": ("shimmerlily", "goldenClover"),
    "juicy": ("queenbeet", "juicyQueenbeet"),
}

# "discover" is special: it isn't aiming at a fixed pair, it breeds until EVERY
# plant in the seed log is unlocked (maximising discovery — no breeding plant has
# a harvest value worth stopping for). Once the log is complete it settles into
# this layout.
DISCOVER_DONE_LAYOUT = "cps"

WOODCHIPS_KEY = "woodchips"   # +3x mutation/spread (req 300 farms) — breeding
CLAY_KEY = "clay"             # +25% plant effects (req 100 farms) — steady CpS
DIRT_KEY = "dirt"            # neutral fallback (req 0)

# Spread planting over ticks so we never dump the whole bank into seeds at once.
MAX_PLANTS_PER_TICK = 6


def _index(snap: dict):
    """Return (plants_by_key, plants_by_id, soils_by_key)."""
    plants = snap.get("plants", [])
    plants_by_key = {p["key"]: p for p in plants}
    plants_by_id = {p["id"]: p for p in plants}
    soils_by_key = {s["key"]: s for s in snap.get("soils", [])}
    return plants_by_key, plants_by_id, soils_by_key


def _breeding_active(strategy: str, plants_by_key: dict) -> bool:
    """True while there's still something worth breeding for. For "discover" that's
    ANY locked plant in the whole seed log; for the targeted strategies it's any of
    that strategy's specific plants still being locked."""
    if strategy == "discover":
        return any(not p["unlocked"] for p in plants_by_key.values())
    for key in STRATEGY_PLANTS.get(strategy, ()):  # unknown strategy → no targets
        p = plants_by_key.get(key)
        if p is not None and not p["unlocked"]:
            return True
    return False


# Cap on how many distinct parent species the breeding board plants at once. The
# checkerboard's mutation tiles only roll a recipe when BOTH its parents sit among
# a tile's 4 neighbours; spreading many species thin drops that per-tile coverage.
# Measured on a full 6x6 (18 empty tiles): one 2-parent recipe → ALL 18 tiles can
# roll it; two recipes (4 species) → only ~6/18 each; 5-6 species → ~4/18. So we
# FOCUS on the single lowest-tier reachable recipe (cap 2 = its two parents), which
# floods every mutation tile with that pair — maximal roll density, the fastest way
# to break a discovery stall. Extra recipes sharing those exact parents (e.g. two
# children of the same pair, or two single-parent recipes) piggyback for free; the
# rest defer to the next round once this one unlocks and the board advances.
FOCUS_PARENT_CAP = 2


def _reachable_recipes(plants_by_key: dict) -> list[tuple]:
    """Every mutation we can ACHIEVE right now, as ``(child_id, child_key, parents)``
    sorted by child id (low tier first).

    A plant's ``children`` lists what it mutates into, so reverse it into
    ``parents_of[child] = {species that list child}`` — the game's own recipe data
    (correct keys, no hardcoding). A locked child is REACHABLE only when EVERY one
    of its parents is already unlocked. Packed (8-neighbour) recipes are excluded —
    they can't roll on the checkerboard and are handled by ``_packed_breed``.

    Note: the Meddleweed→fungi (Brown Mold / Crumbspore) entry is HARVEST-based,
    not adjacency, so it isn't in this map — it's covered separately by leaving
    empty tiles (where Meddleweed spawns) and harvesting every mature mutant."""
    parents_of: dict[str, set] = {}
    for p in plants_by_key.values():
        for c in p["children"]:
            parents_of.setdefault(c, set()).add(p["key"])
    unlocked = {k for k, p in plants_by_key.items() if p["unlocked"]}
    recipes: list[tuple] = []
    for child_key, par in parents_of.items():
        if child_key in _PACKED_TARGET_KEYS:
            continue                      # packed recipes can't roll on the checkerboard
        cp = plants_by_key.get(child_key)
        if cp is None or cp["unlocked"] or not par:
            continue                      # only still-locked children with a recipe
        if par <= unlocked:               # every parent available → achievable now
            recipes.append((cp["id"], child_key, frozenset(par)))
    recipes.sort()
    return recipes


def _focus_parents(recipes: list[tuple]) -> set:
    """Pick the parent species to actually plant: always the lowest-tier reachable
    recipe, plus any further recipe that fits without pushing the distinct-parent
    count past ``FOCUS_PARENT_CAP`` (recipes sharing those parents come along free).
    Keeps adjacency density high so the focused recipes roll quickly."""
    chosen: set = set()
    for _cid, _ck, par in recipes:
        if not chosen or len(chosen | par) <= FOCUS_PARENT_CAP:
            chosen |= set(par)
    return chosen


def _reachable_parents(plants_by_key: dict) -> list[dict]:
    """The focused parent species to plant this round (see ``_focus_parents``),
    sorted by id (low tier first) for deterministic placement."""
    chosen = _focus_parents(_reachable_recipes(plants_by_key))
    return sorted((plants_by_key[k] for k in chosen if k in plants_by_key),
                  key=lambda p: p["id"])


def breeding_plan(snap: dict) -> dict:
    """Telemetry (no side effects): what discovery is actively chasing right now, so
    a stalled garden is legible from the panel/log instead of needing days to judge.
    Returns ``{targets, parents, queued, packed}`` — the recipe children being
    pursued this round, their parent species, how many reachable recipes are
    deferred to later rounds, and any packed target."""
    if not snap or not snap.get("unlocked"):
        return {"targets": [], "parents": [], "queued": 0, "packed": None}
    plants_by_key, _by_id, _soils = _index(snap)
    recipes = _reachable_recipes(plants_by_key)
    chosen = _focus_parents(recipes)
    targets = [ck for _cid, ck, par in recipes if par <= chosen]
    packed = _packed_target(plants_by_key, snap.get("tiles", []))
    return {
        "targets": targets,
        "parents": sorted(chosen),
        "queued": max(0, len(recipes) - len(targets)),
        "packed": packed[0] if packed else None,
    }


def _relevant_parents(plants_by_key: dict) -> list[dict]:
    """Fallback: any unlocked plant that is a parent of at least one still-locked
    plant (even if a co-parent is missing). Used only when no fully-reachable
    mutation exists, to keep low-tier rolls going. Sorted by id."""
    out = []
    for p in plants_by_key.values():
        if not p["unlocked"]:
            continue
        if any(not plants_by_key.get(c, {"unlocked": True})["unlocked"] for c in p["children"]):
            out.append(p)
    out.sort(key=lambda p: p["id"])
    return out


# Recipes that need a PACKED 3x3 neighbourhood (the game counts all 8 Moore
# neighbours), which the breeding checkerboard can never satisfy. Each is grown
# with a ring layout: empty centres surrounded by 8 ring-species tiles.
#   Juicy Queenbeet: needs 8 mature Queenbeet around the centre.
#   Everdaisy:       needs >=3 Tidygrass AND >=3 Elderwort around the centre — a
#                    2-species ring alternates to put 4 of each around each centre.
_PACKED_RECIPES = [
    ("juicyQueenbeet", ["queenbeet"]),
    ("everdaisy", ["tidygrass", "elderwort"]),
]
_PACKED_TARGET_KEYS = {t for t, _ in _PACKED_RECIPES}


def _is_center(x: int, y: int) -> bool:
    """Centre tiles of the 3x3 packing (kept empty for the mutation to land)."""
    return x % 3 == 1 and y % 3 == 1


def _is_parent_tile(x: int, y: int) -> bool:
    """Breeding-layout parent tiles: the (even, even) sublattice (a quarter of the
    grid). Parents sit here so the empty (odd, odd) mutation tiles touch them only
    DIAGONALLY — which counts for mutations (Moore-8 neighbourhood) but NOT for
    contamination/spreading (cardinal-4 only). The other ~3/4 of tiles stay empty,
    giving mutations real room instead of a dense checkerboard the parents spread
    over before anything can mutate."""
    return x % 2 == 0 and y % 2 == 0


def _packed_target(plants_by_key: dict, tiles: list[dict]):
    """Return (target_key, ring_species) for a packed recipe that is reachable now
    (target locked, every ring species unlocked) AND the plot has at least one
    interior centre — a (x%3==1, y%3==1) tile whose full 8-neighbour ring is
    unlocked. Otherwise None (plot too small / nothing to pack → checkerboard)."""
    coords = {(t["x"], t["y"]) for t in tiles}
    has_center = any(
        _is_center(x, y) and all(
            (x + dx, y + dy) in coords
            for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)
        for (x, y) in coords)
    if not has_center:
        return None
    for target, ring in _PACKED_RECIPES:
        tp = plants_by_key.get(target)
        if tp is None or tp["unlocked"]:
            continue
        if all(plants_by_key.get(s, {}).get("unlocked") for s in ring):
            return target, ring
    return None


def _packed_breed(snap, tiles, plants_by_key, soils_by_key, ring,
                  breed_soil, farms, budget) -> list[dict]:
    """Ring layout for an 8-neighbour recipe: keep the 3x3 centres EMPTY (the
    mutation lands there) and fill every other tile with a ring species so each
    centre is surrounded by 8 mature parents. Harvest matured centres (captures
    the new plant / clears weeds) and replace wrong-species ring tiles."""
    actions: list[dict] = []
    if breed_soil:
        actions += _soil_switch(snap, soils_by_key, WOODCHIPS_KEY, farms)
    for t in tiles:
        x, y, tid = t["x"], t["y"], t["id"]
        if _is_center(x, y):
            if tid != 0 and t["mature"]:            # mutation/weed matured here → grab it
                actions.append({"op": "harvest", "x": x, "y": y})
            continue
        want = ring[(x + y) % len(ring)]             # alternate the ring species
        wp = plants_by_key.get(want)
        if tid == 0:
            if wp and budget.take(wp):
                actions.append({"op": "plant", "x": x, "y": y, "seed": wp["id"]})
        elif t.get("key") != want and t["mature"]:   # wrong species → swap it out
            actions.append({"op": "harvest", "x": x, "y": y})
    return actions


def _seed_cost(plant: dict, cookies_ps: float) -> float:
    """Cookie cost to plant one seed: max(costM, cookiesPs*cost*60) — the live
    game formula (the 'Seedless to nay' 5% discount is ignored as a safe floor)."""
    return max(float(plant.get("costM", 0.0)), cookies_ps * float(plant.get("cost", 0.0)) * 60.0)


class _Budget:
    """Tracks how many seeds we can still plant this tick without dipping the
    spendable bank (cookies above the golden-cookie reserve) negative."""

    def __init__(self, cookies: float, cookies_ps: float, reserve: float) -> None:
        self.spendable = max(0.0, cookies - reserve)
        self.cps = cookies_ps
        self.planted = 0

    def take(self, plant: dict) -> bool:
        """If affordable and under the per-tick cap, debit the cost and return True."""
        if self.planted >= MAX_PLANTS_PER_TICK:
            return False
        cost = _seed_cost(plant, self.cps)
        if cost > self.spendable:
            return False
        self.spendable -= cost
        self.planted += 1
        return True


def _soil_switch(snap: dict, soils_by_key: dict, want_key: str, farms: int) -> list[dict]:
    """A [soil→want] action if that soil exists, differs from current, is
    unlocked (enough farms), the 10-min cooldown elapsed, and not frozen."""
    s = soils_by_key.get(want_key)
    if not s or snap.get("soil") == s["id"]:
        return []
    if farms < s.get("req", 0):
        return []
    if snap.get("now", 0) < snap.get("nextSoil", 0) or snap.get("freeze"):
        return []
    return [{"op": "soil", "soil": s["id"]}]


def decide_actions(
    snap: dict,
    strategy: str = "cps",
    breed_soil: bool = True,
    cookies: float = 0.0,
    cookies_ps: float = 0.0,
    reserve_cookies: float = 0.0,
) -> list[dict]:
    """Return the list of garden actions to apply this tick (possibly empty)."""
    if not snap or not snap.get("unlocked"):
        return []
    plants_by_key, plants_by_id, soils_by_key = _index(snap)
    tiles = snap.get("tiles", [])
    farms = int(snap.get("farms", 0))
    budget = _Budget(cookies, cookies_ps, reserve_cookies)

    if _breeding_active(strategy, plants_by_key):
        # The checkerboard can breed every CARDINAL/2-parent recipe, but NOT the
        # 8-neighbour "packed" ones (Juicy Queenbeet needs 8 mature queenbeet,
        # Everdaisy needs 3 tidygrass + 3 elderwort around an empty centre). Switch
        # to a packed ring layout for those — but only once normal breeding has
        # nothing left to climb (so the cheap recipes finish first) and the plot is
        # big enough to have a full 3x3 (an interior centre with all 8 neighbours).
        packed = _packed_target(plants_by_key, tiles)
        if packed and not _reachable_parents(plants_by_key):
            return _packed_breed(snap, tiles, plants_by_key, soils_by_key,
                                 packed[1], breed_soil, farms, budget)
        return _breed(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
                      breed_soil, farms, budget)
    return _steady(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
                   strategy, farms, budget)


def _breed(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
           breed_soil, farms, budget) -> list[dict]:
    actions: list[dict] = []
    if breed_soil:
        actions += _soil_switch(snap, soils_by_key, WOODCHIPS_KEY, farms)

    # Prefer the parents of mutations we can ACHIEVE now (all co-parents unlocked);
    # fall back to any parent-of-a-locked-child, then Baker's wheat, so the board is
    # never idle and low-tier rolls (incl. Meddleweed on the empty tiles) keep going.
    parents = _reachable_parents(plants_by_key)
    if not parents:
        parents = _relevant_parents(plants_by_key)
    if not parents:
        bw = plants_by_key.get("bakerWheat")
        parents = [bw] if bw else []
    if not parents:
        return actions
    for t in tiles:
        x, y, tid = t["x"], t["y"], t["id"]
        parent_tile = _is_parent_tile(x, y)
        if tid != 0:
            if t["mature"]:
                # Use the tile's OWN resolved fields (the snapshot looks the plant
                # up at the correct id-1); plants_by_id keyed by the tile's raw id
                # would be off by one.
                cur_locked = not t.get("unlocked", True)
                if parent_tile:
                    # Parent tiles are the mutation ENGINE: a mature plant here
                    # contributes to the (Moore-8) mutation rolls on the diagonal
                    # empty tiles every tick it stays alive, so LEAVE it growing — it
                    # dies of old age on its own and the tile is replanted then. Only
                    # pull a still-LOCKED species that strayed here, to bank its unlock.
                    harvest = cur_locked
                else:
                    # Every non-parent tile must stay EMPTY so mutations have room.
                    # Harvest whatever matured here: a locked species banks its unlock;
                    # anything else (a parent CONTAMINATION/spread — these land on the
                    # cardinal buffer tiles) is cleared so the board stays open instead
                    # of the spreads choking out the mutation sites.
                    harvest = True
                if harvest:
                    actions.append({"op": "harvest", "x": x, "y": y})
            continue
        if parent_tile:
            # Sublattice-checkerboard the two focused parents across the (even,even)
            # tiles so every interior (odd,odd) empty tile has BOTH species on its
            # diagonals (mutation counts Moore-8) while its cardinal neighbours stay
            # empty (contamination is cardinal-only) — max mutation, zero spreading.
            parent = parents[((x // 2) + (y // 2)) % len(parents)]
            if budget.take(parent):
                actions.append({"op": "plant", "x": x, "y": y, "seed": parent["id"]})
    return actions


def _desired_key(x: int, y: int, strategy: str):
    """The plant key wanted at (x,y) for a steady-state layout, or None to leave
    the tile empty (juicy mutation centers)."""
    if strategy == "discover":  # log complete → settle into a solid CpS layout
        strategy = DISCOVER_DONE_LAYOUT
    a, b = STRATEGY_PLANTS[strategy]
    if strategy == "juicy":
        # 3x3 rings of Queenbeet around an empty center → Juicy Queenbeet rolls.
        if x % 3 == 1 and y % 3 == 1:
            return None
        return a  # queenbeet
    return a if (x + y) % 2 == 0 else b


def _steady(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
            strategy, farms, budget) -> list[dict]:
    actions: list[dict] = []
    # Clay (+25% effects) once affordable on farms, else neutral dirt.
    clay_req = soils_by_key.get(CLAY_KEY, {}).get("req", 1 << 30)
    want_soil = CLAY_KEY if farms >= clay_req else DIRT_KEY
    actions += _soil_switch(snap, soils_by_key, want_soil, farms)

    for t in tiles:
        x, y, tid = t["x"], t["y"], t["id"]
        cur_key = t.get("key")  # resolved correctly in the snapshot (id-1)
        want = _desired_key(x, y, strategy)

        if want is None:
            # Intended-empty center: harvest a matured plant (e.g. a Juicy
            # Queenbeet) for its burst and to reopen the tile.
            if tid != 0 and t["mature"]:
                actions.append({"op": "harvest", "x": x, "y": y})
            continue

        if tid == 0:
            wp = plants_by_key.get(want)
            if wp and budget.take(wp):
                actions.append({"op": "plant", "x": x, "y": y, "seed": wp["id"]})
        elif cur_key != want:
            # Leftover breeding plant in a layout slot — clear it to replant.
            actions.append({"op": "harvest", "x": x, "y": y})
    return actions
