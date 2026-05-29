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
    unlocks_achievement: bool = False
    name: str = ""


# Marginal CPS bonus from a single new achievement. Each achievement adds +4%
# milk; each kitten upgrade multiplies CPS by (1 + milk × factor) for its own
# factor. With ~350 achievements and all kittens owned, the sum-of-derivatives
# works out to ≈ +0.48% of current CPS per new achievement (cookieclicker.wiki.gg/wiki/Milk).
_ACHIEVEMENT_CPS_FRACTION = 0.0048


def is_achievement_unlock_upgrade(name: str) -> bool:
    """Best-effort name-pattern detection of upgrades whose purchase crosses an
    achievement threshold the bot's description-parser doesn't see.

    Catches two big categories:
      - Kitten upgrades ("Kitten helpers", "Kitten workers" …) → Jellicles at 10.
      - Grandma synergies ("Farmer grandmas", "Cosmic grandmas" …,
        plus "Antigrandmas" / "Metagrandmas") → Elder (7) / Veteran (14).
    """
    n = (name or "").strip().lower()
    if n.startswith("kitten "):
        return True
    if n.endswith("grandmas") and n != "grandmas":
        return True
    return False


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

    # Golden-cookie upgrades (frequency / duration / effect). Match singular and
    # plural, any case: "Get lucky" reads "Golden cookie effects last twice as
    # long" (singular), which the old plural-only "Golden cookies" check missed —
    # leaving one of the strongest upgrades scored at the 0.05 fallback so it
    # never out-ranked cheap buildings.
    if "golden cookie" in description.lower():
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


def score_upgrade(
    up: Upgrade, cookies_ps: float, buildings: list[Building], price: float | None = None
) -> float:
    """Estimated cps-per-cost. Higher is better. Falls back to 0 when uncertain.

    ``price`` is the live purchase price (from getPrice(), reflecting discounts);
    falls back to the cached base price when not supplied.
    """
    if price is None:
        price = up.base_price
    if price <= 0 or cookies_ps <= 0:
        return 0.0
    target = up.gain.target
    if target == "all":
        score = (up.gain.factor * cookies_ps) / price
    elif target == "clicking":
        # Click upgrades are evaluated as roughly 15 effective clicks/sec.
        score = (cookies_ps * up.gain.factor * 15) / price
    else:
        needle = target.lower()
        score = 0.0
        for b in buildings:
            if needle in b.name.lower() or needle == "factorie":
                score = (up.gain.factor * b.total_cps) / price
                break

    # Achievement-unlock bonus: purchases that tick an Elder/Veteran/Jellicles
    # threshold add roughly +0.48% of CPS via the milk multiplier — invisible
    # to the description parser, so add it here.
    if up.unlocks_achievement:
        score += (_ACHIEVEMENT_CPS_FRACTION * cookies_ps) / price
    return score
