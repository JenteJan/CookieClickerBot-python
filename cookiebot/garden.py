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


def _relevant_parents(plants_by_key: dict) -> list[dict]:
    """Unlocked plants that are a parent of at least one still-locked plant.

    A plant's ``children`` lists the species it can mutate into, so an unlocked
    plant with any locked child is worth growing. Sorted by id (low tier first)
    for deterministic placement."""
    out = []
    for p in plants_by_key.values():
        if not p["unlocked"]:
            continue
        if any(not plants_by_key.get(c, {"unlocked": True})["unlocked"] for c in p["children"]):
            out.append(p)
    out.sort(key=lambda p: p["id"])
    return out


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
        return _breed(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
                      breed_soil, farms, budget)
    return _steady(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
                   strategy, farms, budget)


def _breed(snap, tiles, plants_by_key, plants_by_id, soils_by_key,
           breed_soil, farms, budget) -> list[dict]:
    actions: list[dict] = []
    if breed_soil:
        actions += _soil_switch(snap, soils_by_key, WOODCHIPS_KEY, farms)

    parents = _relevant_parents(plants_by_key)
    if not parents:  # nothing reachable right now — keep low-tier rolls going
        bw = plants_by_key.get("bakerWheat")
        parents = [bw] if bw else []
    if not parents:
        return actions
    parent_keys = {p["key"] for p in parents}

    for t in tiles:
        x, y, tid = t["x"], t["y"], t["id"]
        even = (x + y) % 2 == 0
        if tid != 0:
            if t["mature"]:
                cur = plants_by_id.get(tid, {})
                cur_key = cur.get("key")
                cur_locked = cur_key is not None and not cur.get("unlocked", True)
                if even:
                    # Parent tiles are the mutation ENGINE: a mature plant here
                    # seeds the adjacent empty mutation tiles every tick it stays
                    # alive, so LEAVE it growing — it dies of old age on its own and
                    # the tile is replanted then. Harvesting it the instant it
                    # matures (the old behaviour) gave it ~zero seeding time and
                    # stalled all breeding. Only pull a still-LOCKED species that
                    # happened to spread onto a parent tile, to bank its unlock.
                    harvest = cur_locked
                else:
                    # Mutation tiles must stay EMPTY to catch fresh rolls. Harvest
                    # whatever matured here: a locked species banks its unlock; an
                    # unlocked one (usually a parent self-spread) is cleared so the
                    # tile can roll again instead of clogging with a copy.
                    harvest = True
                if harvest:
                    actions.append({"op": "harvest", "x": x, "y": y})
            continue
        if even:
            parent = parents[(x + 2 * y) % len(parents)]
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
        cur_key = plants_by_id[tid]["key"] if tid in plants_by_id else None
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
