"""Garden minigame decision logic.

Pure functions (no Selenium): given a garden snapshot dict (from
``scripts.GET_GARDEN_STATE``) they return a list of action dicts that
``scripts.GARDEN_ACTIONS`` applies. Kept browser-free so it's unit-testable.

Two phases, chosen automatically from the snapshot:

  BREEDING — while the chosen strategy's plants aren't all unlocked yet. Switch
  soil to mutation-favoring Wood chips, plant a checkerboard of the relevant
  *unlocked parent* plants (any unlocked plant that is a parent of a still-locked
  plant, read live from each plant's ``children``), and leave the alternating
  tiles empty so mutations can roll there. Harvest mature plants on the empty
  tiles — maturity already unlocked their seed, and harvesting frees the tile for
  the next roll. This is a robust heuristic, not an optimal mutation solver: it
  reliably climbs the tree toward the strategy's plants over time.

  STEADY — once those plants are unlocked. Drop soil back to dirt and fill the
  grid with the strategy's layout, replanting empties and clearing leftover
  breeding plants.

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

WOODCHIPS_KEY = "woodchips"
DIRT_KEY = "dirt"

# Spread planting over ticks: never spend the whole bank filling the grid at
# once, and always keep a floor of unspent CpS so seeds don't dent the Lucky bank.
MAX_PLANTS_PER_TICK = 6
MIN_BANK_SECONDS = 60.0


def _index(snap: dict):
    """Return (plants_by_key, plants_by_id, soil_id_by_key) from a snapshot."""
    plants_by_key = {p["key"]: p for p in snap.get("plants", [])}
    plants_by_id = {p["id"]: p for p in snap.get("plants", [])}
    # JS object keys arrive as strings; soilNames maps id(str) -> key.
    soil_id_by_key = {k: int(sid) for sid, k in snap.get("soilNames", {}).items()}
    return plants_by_key, plants_by_id, soil_id_by_key


def _breeding_active(strategy: str, plants_by_key: dict) -> bool:
    """True while any of the strategy's plants is still locked."""
    for key in STRATEGY_PLANTS.get(strategy, ()):  # unknown strategy → no targets
        p = plants_by_key.get(key)
        if p is not None and not p["unlocked"]:
            return True
    return False


def _relevant_parents(plants_by_key: dict) -> list[dict]:
    """Unlocked plants that are a parent of at least one still-locked plant.

    A plant's ``children`` lists the species it can mutate into, so an unlocked
    plant with any locked child is worth planting — growing it gives that child a
    chance to appear in an adjacent empty tile. Sorted by id (low tier first) for
    deterministic placement."""
    out = []
    for p in plants_by_key.values():
        if not p["unlocked"]:
            continue
        if any(not plants_by_key.get(c, {"unlocked": True})["unlocked"] for c in p["children"]):
            out.append(p)
    out.sort(key=lambda p: p["id"])
    return out


def _can_afford(cookies: float, cookies_ps: float) -> bool:
    """Keep a floor of unspent CpS so garden seeds never dent the Lucky bank."""
    return cookies > cookies_ps * MIN_BANK_SECONDS


def _soil_action(snap: dict, soil_id_by_key: dict, want_key: str) -> list[dict]:
    """A [soil→want] action if that soil exists, differs from current, and the
    10-min cooldown has elapsed; else []."""
    want = soil_id_by_key.get(want_key)
    if want is None or snap.get("soil") == want:
        return []
    if snap.get("now", 0) < snap.get("nextSoil", 0):
        return []
    return [{"op": "soil", "soil": want}]


def decide_actions(
    snap: dict,
    strategy: str = "cps",
    breed_soil: bool = True,
    cookies: float = 0.0,
    cookies_ps: float = 0.0,
) -> list[dict]:
    """Return the list of garden actions to apply this tick (possibly empty)."""
    if not snap or not snap.get("unlocked"):
        return []
    plants_by_key, plants_by_id, soil_id_by_key = _index(snap)
    tiles = snap.get("tiles", [])
    afford = _can_afford(cookies, cookies_ps)

    if _breeding_active(strategy, plants_by_key):
        return _breed(snap, tiles, plants_by_key, plants_by_id, soil_id_by_key,
                      breed_soil, afford)
    return _steady(snap, tiles, plants_by_key, plants_by_id, soil_id_by_key,
                   strategy, afford)


def _breed(snap, tiles, plants_by_key, plants_by_id, soil_id_by_key,
           breed_soil, afford) -> list[dict]:
    actions: list[dict] = []
    if breed_soil:
        actions += _soil_action(snap, soil_id_by_key, WOODCHIPS_KEY)

    parents = _relevant_parents(plants_by_key)
    if not parents:  # nothing reachable right now — keep low-tier rolls going
        bw = plants_by_key.get("bakerWheat")
        parents = [bw] if bw else []
    if not parents:
        return actions

    planted = 0
    for t in tiles:
        x, y, tid = t["x"], t["y"], t["id"]
        if (x + y) % 2 == 1:
            # Mutation tile: harvest a mature plant to free it for the next roll.
            if tid != 0 and t["mature"]:
                actions.append({"op": "harvest", "x": x, "y": y})
        else:
            # Parent tile: keep a relevant parent growing here.
            if tid == 0 and afford and planted < MAX_PLANTS_PER_TICK:
                parent = parents[(x + 2 * y) % len(parents)]
                actions.append({"op": "plant", "x": x, "y": y, "seed": parent["id"]})
                planted += 1
    return actions


def _desired_key(x: int, y: int, strategy: str):
    """The plant key wanted at (x,y) for a steady-state layout, or None to leave
    the tile empty (juicy mutation centers)."""
    a, b = STRATEGY_PLANTS[strategy]
    if strategy == "juicy":
        # 3x3 rings of Queenbeet around an empty center → Juicy Queenbeet rolls.
        if x % 3 == 1 and y % 3 == 1:
            return None
        return a  # queenbeet
    return a if (x + y) % 2 == 0 else b


def _steady(snap, tiles, plants_by_key, plants_by_id, soil_id_by_key,
            strategy, afford) -> list[dict]:
    actions: list[dict] = []
    actions += _soil_action(snap, soil_id_by_key, DIRT_KEY)

    planted = 0
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
            want_id = plants_by_key.get(want, {}).get("id")
            if want_id and afford and planted < MAX_PLANTS_PER_TICK:
                actions.append({"op": "plant", "x": x, "y": y, "seed": want_id})
                planted += 1
        elif cur_key != want:
            # Leftover breeding plant in a layout slot — clear it to replant.
            actions.append({"op": "harvest", "x": x, "y": y})
    return actions
