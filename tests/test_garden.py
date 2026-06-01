"""Tests for cookiebot.garden.decide_actions (browser-free).

Runs with the project venv either way:
    .venv/bin/python tests/test_garden.py     # standalone (no deps)
    .venv/bin/python -m pytest tests/ -q       # if pytest is installed
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cookiebot import garden  # noqa: E401

# Plant catalog for the fixtures. children are wired so bakerWheat is the
# "relevant parent" of the still-locked strategy plants in the breeding tests.
# cost=1 → seed cost = cookies_ps*60 (cheap under RICH, expensive when cps is huge).
_PLANTS = {
    "bakerWheat": dict(id=1, key="bakerWheat", name="Baker's wheat", mature=10,
                       cost=1.0, costM=0.0, children=["queenbeet", "elderwort"]),
    "goldenClover": dict(id=5, key="goldenClover", name="Golden clover", mature=15,
                         cost=1.0, costM=0.0, children=[]),
    "shimmerlily": dict(id=6, key="shimmerlily", name="Shimmerlily", mature=15,
                        cost=1.0, costM=0.0, children=[]),
    "elderwort": dict(id=7, key="elderwort", name="Elderwort", mature=30,
                      cost=1.0, costM=0.0, children=[]),
    "queenbeet": dict(id=20, key="queenbeet", name="Queenbeet", mature=38,
                      cost=1.0, costM=0.0, children=["juicyQueenbeet"]),
    "juicyQueenbeet": dict(id=21, key="juicyQueenbeet", name="Juicy queenbeet",
                           mature=43, cost=1.0, costM=0.0, children=[]),
}
# id 0 dirt (req 0), 2 clay (req 100), 4 woodchips (req 300).
_SOILS = [dict(key="dirt", id=0, req=0), dict(key="clay", id=2, req=100),
          dict(key="woodchips", id=4, req=300)]


def _plants(unlocked_keys):
    out = []
    for k, p in _PLANTS.items():
        q = dict(p)
        q["unlocked"] = k in unlocked_keys
        out.append(q)
    return out


def _grid(n=2, fill=None):
    """n×n of unlocked tiles; fill optionally maps (x,y)->(id, age, mature)."""
    fill = fill or {}
    tiles = []
    for y in range(n):
        for x in range(n):
            tid, age, mat = fill.get((x, y), (0, 0, False))
            tiles.append(dict(x=x, y=y, id=tid, age=age, mature=mat))
    return tiles


def _snap(unlocked_keys, tiles, soil=0, now=10_000, next_soil=0, farms=500):
    return dict(unlocked=True, freeze=0, soil=soil, soils=_SOILS, farms=farms,
                nextSoil=next_soil, now=now, plants=_plants(unlocked_keys),
                tiles=tiles)


RICH = dict(cookies=1e12, cookies_ps=1.0)   # affordable (seed cost ≈ 60)


def test_locked_targets_breed_with_woodchips_and_parents():
    snap = _snap(["bakerWheat"], _grid(2), soil=0)
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    # soil flips to woodchips (id 4)
    assert {"op": "soil", "soil": 4} in acts
    # even tiles (0,0) and (1,1) get the relevant parent (bakerWheat id 1)
    plants = [a for a in acts if a["op"] == "plant"]
    assert {(a["x"], a["y"]) for a in plants} == {(0, 0), (1, 1)}
    assert all(a["seed"] == 1 for a in plants)


def test_breed_harvests_mature_mutation_tile():
    # (1,0) is an odd (mutation) tile holding a mature plant → harvest it.
    snap = _snap(["bakerWheat"], _grid(2, {(1, 0): (5, 99, True)}))
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    assert {"op": "harvest", "x": 1, "y": 0} in acts


def test_steady_fills_empties_and_switches_to_clay():
    snap = _snap(["bakerWheat", "queenbeet", "elderwort"], _grid(2), soil=4)
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    assert {"op": "soil", "soil": 2} in acts  # woodchips → clay (+25% effects)
    plants = {(a["x"], a["y"]): a["seed"] for a in acts if a["op"] == "plant"}
    # checkerboard: queenbeet(20) on even, elderwort(7) on odd
    assert plants == {(0, 0): 20, (1, 1): 20, (1, 0): 7, (0, 1): 7}


def test_steady_uses_dirt_when_too_few_farms_for_clay():
    # < 100 farms → clay locked → fall back to dirt (and never force clay).
    snap = _snap(["bakerWheat", "queenbeet", "elderwort"], _grid(2), soil=0, farms=40)
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    assert not any(a["op"] == "soil" and a["soil"] == 2 for a in acts)  # no clay


def test_breed_skips_woodchips_when_too_few_farms():
    # < 300 farms → woodchips locked → no soil action (breeding still proceeds).
    snap = _snap(["bakerWheat"], _grid(2), soil=0, farms=120)
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    assert not any(a["op"] == "soil" for a in acts)
    assert any(a["op"] == "plant" for a in acts)


def test_steady_harvests_wrong_species():
    # (0,0) wants queenbeet but holds bakerWheat (leftover breeding) → harvest.
    snap = _snap(["bakerWheat", "queenbeet", "elderwort"],
                 _grid(2, {(0, 0): (1, 50, True)}), soil=0)
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    assert {"op": "harvest", "x": 0, "y": 0} in acts


def test_juicy_harvests_mature_center():
    # 3×3 grid; center (1,1) holds a mature Juicy Queenbeet → harvest the burst.
    snap = _snap(["bakerWheat", "queenbeet", "juicyQueenbeet"],
                 _grid(3, {(1, 1): (21, 50, True)}), soil=0)
    acts = garden.decide_actions(snap, "juicy", True, **RICH)
    assert {"op": "harvest", "x": 1, "y": 1} in acts
    # center is never planted
    assert not any(a["op"] == "plant" and (a["x"], a["y"]) == (1, 1) for a in acts)


def test_not_unlocked_returns_empty():
    assert garden.decide_actions({"unlocked": False}, "cps", True, **RICH) == []
    assert garden.decide_actions({}, "cps", True, **RICH) == []


def test_unaffordable_skips_planting_but_still_harvests():
    snap = _snap(["bakerWheat", "queenbeet", "elderwort"],
                 _grid(2, {(0, 0): (1, 50, True)}), soil=0)
    acts = garden.decide_actions(snap, "cps", True, cookies=0.0, cookies_ps=1e6)
    assert not any(a["op"] == "plant" for a in acts)      # bank floor blocks planting
    assert {"op": "harvest", "x": 0, "y": 0} in acts       # clearing still happens


def test_soil_respects_cooldown():
    # Cooldown not elapsed (now < nextSoil) → no soil change emitted.
    snap = _snap(["bakerWheat"], _grid(2), soil=0, now=100, next_soil=999_999)
    acts = garden.decide_actions(snap, "cps", True, **RICH)
    assert not any(a["op"] == "soil" for a in acts)


def test_breed_soil_disabled_leaves_soil():
    snap = _snap(["bakerWheat"], _grid(2), soil=0)
    acts = garden.decide_actions(snap, "cps", breed_soil=False, **RICH)
    assert not any(a["op"] == "soil" for a in acts)


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run()
