#!/usr/bin/env python3
"""Aggregate a finished batch A/B run and report whether the two groups differ.

Reads all bat-a-* and bat-b-* profile trial logs, compares the distribution of
final CPS (and cumulative cookies) between the two groups, and runs a simple
two-sample test (Welch's t on log10 values, since CPS spans orders of
magnitude). Pure stdlib.

    python analyze_batch.py
    python analyze_batch.py --metric cookies
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from cookiebot.config import PROFILES_DIR, profile_trials_dir


def final_snapshot(profile: str) -> dict | None:
    d = profile_trials_dir(profile)
    if not d.exists():
        return None
    logs = sorted(d.glob("trial_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    last = None
    for line in open(logs[0]):
        row = json.loads(line)
        if row.get("kind") == "snapshot":
            last = row
    return last


def group(prefix: str, metric: str) -> list[float]:
    if not PROFILES_DIR.exists():
        return []
    vals = []
    for d in sorted(PROFILES_DIR.iterdir()):
        if d.is_dir() and d.name.startswith(prefix):
            s = final_snapshot(d.name)
            if s:
                if metric == "cookies":
                    vals.append(float(s.get("cookiesEarned", 0.0)))
                else:  # base CPS (unbuffed) — the fair, non-spiky measure
                    vals.append(float(s.get("unbuffedCps", s.get("cookiesPs", 0.0))))
    return vals


def stats(xs: list[float]) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0}
    s = sorted(xs)
    mean = sum(s) / n
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    var = sum((x - mean) ** 2 for x in s) / (n - 1) if n > 1 else 0.0
    return {"n": n, "mean": mean, "median": median, "sd": math.sqrt(var),
            "min": s[0], "max": s[-1]}


def welch_log(a: list[float], b: list[float]) -> tuple[float, float] | None:
    """Welch's t on log10 values (CPS is log-distributed). Returns (t, dof)."""
    la = [math.log10(x) for x in a if x > 0]
    lb = [math.log10(x) for x in b if x > 0]
    if len(la) < 2 or len(lb) < 2:
        return None
    ma, mb = sum(la) / len(la), sum(lb) / len(lb)
    va = sum((x - ma) ** 2 for x in la) / (len(la) - 1)
    vb = sum((x - mb) ** 2 for x in lb) / (len(lb) - 1)
    sa, sb = va / len(la), vb / len(lb)
    if sa + sb == 0:
        return None
    t = (ma - mb) / math.sqrt(sa + sb)
    dof = (sa + sb) ** 2 / (sa ** 2 / (len(la) - 1) + sb ** 2 / (len(lb) - 1))
    return t, dof


def fmt(n: float) -> str:
    for thr, suf in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")]:
        if abs(n) >= thr:
            return f"{n / thr:.3f}{suf}"
    return f"{n:.1f}"


def main(argv: list[str]) -> int:
    metric = "base"   # base (unbuffed) CPS by default; or "cookies"
    if "--metric" in argv:
        metric = argv[argv.index("--metric") + 1]

    a = group("bat-a-", metric)
    b = group("bat-b-", metric)
    sa, sb = stats(a), stats(b)
    label = {"cookies": "cumulative cookies", "cps": "final CPS (buffed)"}.get(
        metric, "final base CPS (unbuffed)")
    print(f"metric: {label}\n")
    for lbl, st in (("A", sa), ("B", sb)):
        if st["n"] == 0:
            print(f"{lbl}: no completed runs found")
            continue
        print(f"{lbl}: n={st['n']}  mean={fmt(st['mean'])}  median={fmt(st['median'])}  "
              f"sd={fmt(st['sd'])}  range [{fmt(st['min'])}, {fmt(st['max'])}]")
    print()
    if sa.get("n", 0) and sb.get("n", 0):
        ratio = sa["median"] / sb["median"] if sb["median"] else float("inf")
        print(f"median A / median B = {ratio:.3f}")
        w = welch_log(a, b)
        if w:
            t, dof = w
            # Rough two-sided significance: |t| > ~2 over ~10+ dof ≈ p<0.05.
            verdict = ("LIKELY REAL (|t|>2)" if abs(t) > 2 else
                       "NOT distinguishable (|t|<2) — noise dominates")
            print(f"Welch t on log10(CPS): t={t:.2f}, dof≈{dof:.0f} → {verdict}")
        else:
            print("not enough data for a significance test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
