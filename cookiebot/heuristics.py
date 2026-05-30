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

# Building counts that grant an achievement when reached (per building type).
_ACHIEVEMENT_BUILDING_THRESHOLDS = frozenset(
    [1, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 800]
)


def building_buy_crosses_achievement(amount: int, qty: int = 1) -> bool:
    """True if buying ``qty`` more of a building at count ``amount`` crosses a
    building-count achievement threshold."""
    return any(amount < t <= amount + qty for t in _ACHIEVEMENT_BUILDING_THRESHOLDS)


# ---- golden-cookie expected value (Lucky term only) -----------------------
#
# Lucky! pays min(0.15 * bank, cap) + 13, where cap = cookiesPs * 60 * 15 (15
# minutes of CPS), raised to ~7x with "Get lucky". Since cookiesPs is live, the
# cap auto-rises ~7x during a Frenzy. The only golden-cookie effect whose value
# depends on your bank is Lucky, so it's the only term relevant to bank-vs-spend.

_LUCKY_FRAC = 0.15
_LUCKY_BASE_CAP_S = 15 * 60       # 15 min of CPS, the base Lucky cap
_GET_LUCKY_CAP_MULT = 7.0          # "Get lucky" raises the cap ~7x


def mean_spawn_interval_s(min_frames: float, max_frames: float, fps: float = 30.0) -> float:
    """Mean seconds between golden-cookie spawns, given the game's per-frame
    quintic spawn ramp P(spawn) = ((t-min)/(max-min))^5 once t>min."""
    if fps <= 0 or max_frames <= min_frames:
        return float("inf")
    # Discrete survival sum, stepped for speed; matches the game to ~1%.
    step = max(1, int((max_frames - min_frames) / 300))
    surv, mean, t = 1.0, 0.0, 0.0
    span = max_frames - min_frames
    while surv > 1e-6 and t < max_frames * 3:
        t += step
        if t > min_frames:
            p = min(1.0, ((t - min_frames) / span) ** 5)
        else:
            p = 0.0
        ps = surv * (1 - (1 - p) ** step)
        mean += ps * t
        surv *= (1 - p) ** step
    return mean / fps


def lucky_cap(cookies_ps: float, get_lucky: bool) -> float:
    """Max Lucky payout from the per-CPS cap term (the bank can't beat this)."""
    cap = cookies_ps * _LUCKY_BASE_CAP_S
    return cap * _GET_LUCKY_CAP_MULT if get_lucky else cap


def marginal_bank_value_per_s(cookies: float, cookies_ps: float,
                              mean_interval_s: float, get_lucky: bool) -> float:
    """Cookies/sec gained by holding ONE more cookie in reserve, via Lucky.

    Each Lucky pays 0.15*bank up to the cap, ~once per mean_interval. So one
    extra banked cookie adds 0.15 per Lucky — UNTIL the bank is large enough that
    the 15%-term exceeds the cap, after which extra banking does nothing.
    Returns the marginal cookies/sec, directly comparable to a purchase's
    value-per-cost (ΔCPS per cookie spent)."""
    if mean_interval_s <= 0 or cookies_ps <= 0:
        return 0.0
    cap = lucky_cap(cookies_ps, get_lucky)
    # Above the cap, the 15%-of-bank term is capped → marginal value is 0.
    if _LUCKY_FRAC * cookies >= cap:
        return 0.0
    return _LUCKY_FRAC / mean_interval_s


def lucky_reserve_target(cookies_ps: float, get_lucky: bool) -> float:
    """Bank size where 15%-of-bank hits the Lucky cap (banking beyond is wasted)."""
    return lucky_cap(cookies_ps, get_lucky) / _LUCKY_FRAC


def achievement_milk_bonus_cps(cookies_ps: float) -> float:
    """Marginal CPS gained from the milk bump of crossing one achievement."""
    return _ACHIEVEMENT_CPS_FRACTION * cookies_ps


def payback_seconds(price: float, delta_cps: float) -> float:
    """Seconds for a purchase to pay for itself. inf when it adds no CPS."""
    if delta_cps <= 0:
        return float("inf")
    return price / delta_cps


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


# The bot autoclicks continuously, so a click-power upgrade's value is its
# per-click gain × clicks/sec. Default matches AUTOCLICK_COOKIE_MS=25 → 40/s;
# the runner passes the real configured rate.
_DEFAULT_CLICKS_PER_SEC = 40.0

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

    # "Thousand/Million/… fingers": "The mouse and cursors gain +N cookies for
    # each non-cursor building owned." This is PASSIVE cursor CpS (added to the
    # Cursor building's production, scaling with building count) — NOT click
    # power. The parser can't price it precisely (depends on building count +
    # the finger multiplier chain), but it's worth far more than a click upgrade,
    # so we tag it "cursor" → scored against the Cursor building's CpS. Payback
    # mode values it exactly via CalculateGains; this is the fallback.
    if "for each non-cursor building" in description or "non-cursor building" in description:
        return UpgradeGain(1.0, "cursor")

    # Genuine click-power upgrades: "Clicking gains +N% of your CpS" (Plastic
    # mouse line) or the base "mouse and cursor are twice as efficient".
    if "Clicking gains" in description:
        m = _PCT.search(description)
        return UpgradeGain(int(m.group(1)) / 100, "clicking") if m else UpgradeGain(0.05, "clicking")
    if "mouse and cursor" in description:
        return UpgradeGain(1.0, "clicking")

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
    up: Upgrade,
    cookies_ps: float,
    buildings: list[Building],
    price: float | None = None,
    clicks_per_sec: float = _DEFAULT_CLICKS_PER_SEC,
) -> float:
    """Estimated cps-per-cost. Higher is better. Falls back to 0 when uncertain.

    ``price`` is the live purchase price (from getPrice(), reflecting discounts);
    falls back to the cached base price when not supplied. ``clicks_per_sec`` is
    the bot's actual autoclicker rate, used to convert click-power upgrades into
    an effective passive-CPS contribution.
    """
    if price is None:
        price = up.base_price
    if price <= 0 or cookies_ps <= 0:
        return 0.0
    target = up.gain.target
    if target == "all":
        score = (up.gain.factor * cookies_ps) / price
    elif target == "clicking":
        # Click-power upgrade adds factor×CpS to each click. At clicks_per_sec
        # clicks/sec that's an effective +factor×CpS×clicks_per_sec of passive
        # production (the bot autoclicks continuously).
        score = (cookies_ps * up.gain.factor * clicks_per_sec) / price
    elif target == "cursor":
        # Thousand-fingers family: passive cursor CpS scaling with building
        # count. Best proxy is the Cursor building's current total CpS — buying
        # the upgrade roughly adds on that order. (Payback mode prices it exactly
        # via CalculateGains; this keeps it from falling to the 0.05 floor.)
        score = 0.0
        for b in buildings:
            if b.name.lower() == "cursor":
                score = (up.gain.factor * max(b.total_cps, cookies_ps * 0.01)) / price
                break
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
