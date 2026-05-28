"""Parsing of upgrade descriptions + scoring of upgrades and buildings."""
from __future__ import annotations

import re
from typing import NamedTuple


class Building(NamedTuple):
    name: str
    heuristic: float
    amount: int
    price: float
    locked: bool
    stored_cps: float
    total_cps: float


class UpgradeGain(NamedTuple):
    factor: float
    target: str  # "all", "clicking", or a building (singular) name


class Upgrade(NamedTuple):
    id: int
    gain: UpgradeGain
    base_price: float


_PCT = re.compile(r"\+(\d+)%")
_BUILDING_EFF = re.compile(r"(\w+) are <b>(\w+)</b> as efficient\.")
_BUILDING_GAIN_PCT = re.compile(r"(\w+) gain <b>\+(\d+)%</b> CpS")


def building_from_js(d: dict) -> Building:
    return Building(
        name=d["name"],
        heuristic=d["heuristic"],
        amount=int(d["amount"]),
        price=float(d["price"]),
        locked=bool(d["locked"]),
        stored_cps=float(d["storedCps"]),
        total_cps=float(d["totalCps"]),
    )


def _drop_trailing_s(s: str) -> str:
    return s[:-1] if s.endswith("s") else s


def parse_upgrade_gain(description: str) -> UpgradeGain:
    """Best-effort classifier for Cookie Clicker upgrade flavor text."""
    if (
        not description
        or "grandmatriarchs will return" in description
        or "Activating this" in description
        or "Contains the wrath" in description
        or "Puts a permanent end" in description
        or "prevents golden cookies" in description
        or "for the next" in description
    ):
        return UpgradeGain(0.0, "all")

    if "Cookie production multiplier" in description:
        m = _PCT.search(description)
        return UpgradeGain(int(m.group(1)) / 100, "all") if m else UpgradeGain(0.05, "all")

    if "mouse and cursor" in description:
        return UpgradeGain(1.0, "clicking")

    if "Clicking gains" in description:
        m = _PCT.search(description)
        return UpgradeGain(int(m.group(1)) / 100, "clicking") if m else UpgradeGain(0.05, "clicking")

    if "milk" in description:
        return UpgradeGain(0.25, "all")

    if "Golden cookies" in description:
        return UpgradeGain(2.0, "all")

    m = _BUILDING_EFF.search(description)
    if m:
        if " gain " in description:
            gain = _BUILDING_GAIN_PCT.search(description)
            if gain:
                return UpgradeGain(int(gain.group(2)) * 15 / 100, _drop_trailing_s(gain.group(1)))
        if m.group(2) == "twice":
            return UpgradeGain(1.0, _drop_trailing_s(m.group(1)))

    return UpgradeGain(0.05, "all")


def score_upgrade(up: Upgrade, cookies_ps: float, buildings: list[Building]) -> float:
    """Estimated cps-per-cost. Higher is better. Falls back to 0 when uncertain."""
    if up.base_price <= 0 or cookies_ps <= 0:
        return 0.0
    target = up.gain.target
    if target == "all":
        return (up.gain.factor * cookies_ps) / up.base_price
    if target == "clicking":
        # Click upgrades are evaluated as roughly 15 effective clicks/sec.
        return (cookies_ps * up.gain.factor * 15) / up.base_price
    needle = target.lower()
    for b in buildings:
        if needle in b.name.lower() or needle == "factorie":
            return (up.gain.factor * b.total_cps) / up.base_price
    return 0.0
