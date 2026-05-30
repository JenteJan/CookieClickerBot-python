#!/usr/bin/env python3
"""Deep post-hoc analysis of a finished batch A/B run.

Loads every bat-a-* and bat-b-* trial log, builds median trajectories for each
group on a shared time grid, and explains WHEN and WHY the groups diverge /
converge by decomposing the gap into:

  - CPS trajectory:   median CPS(t) per group + their ratio over time
  - cookie trajectory: median cumulative cookies(t) + ratio (the 'banked lead')
  - luck:   buff counts per group (Frenzy / Click frenzy / etc.) — if these
            differ a lot, divergence is luck, not strategy
  - strategy: purchase mix (buildings vs upgrades vs bundles) and what each
            group spent on, to see if the better group simply bought better
  - divergence point: first time the CPS-ratio leaves [0.9, 1.1] for good
  - convergence: whether the CPS ratio returns toward 1 (rates equalise) even
            while the cookie ratio stays high (banked early lead)

    python analyze_divergence.py
    python analyze_divergence.py --grid 60     # 60s sampling grid
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from cookiebot.config import PROFILES_DIR, profile_trials_dir


def load_runs(prefix: str) -> list[dict]:
    runs = []
    if not PROFILES_DIR.exists():
        return runs
    for d in sorted(PROFILES_DIR.iterdir()):
        if not (d.is_dir() and d.name.startswith(prefix)):
            continue
        logs = sorted(profile_trials_dir(d.name).glob("trial_*.jsonl"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            continue
        snaps, buys, buffs = [], [], []
        for line in open(logs[0]):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = r.get("kind")
            if k == "snapshot":
                snaps.append(r)
            elif k == "buy":
                buys.append(r)
            elif k == "buff":
                buffs.append(r)
        if snaps:
            runs.append({"name": d.name, "snaps": snaps, "buys": buys, "buffs": buffs})
    return runs


def value_at(snaps: list[dict], t: float, key: str) -> float | None:
    best = None
    for s in snaps:
        if s["t"] <= t:
            best = s.get(key)
        else:
            break
    return best


def median(xs: list[float]) -> float:
    s = sorted(x for x in xs if x is not None)
    if not s:
        return 0.0
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def fmt(n: float) -> str:
    for thr, suf in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")]:
        if abs(n) >= thr:
            return f"{n / thr:.2f}{suf}"
    return f"{n:.1f}"


def main(argv: list[str]) -> int:
    grid = 60
    if "--grid" in argv:
        grid = int(argv[argv.index("--grid") + 1])

    A = load_runs("bat-a-")
    B = load_runs("bat-b-")
    if not A or not B:
        print("No batch runs found (need bat-a-* and bat-b-* profiles with logs).")
        return 1
    print(f"A: {len(A)} runs   B: {len(B)} runs")
    span = min(max(s["t"] for s in r["snaps"]) for r in A + B)
    print(f"shared span: {span/3600:.2f} h, sampling every {grid}s\n")

    # --- median trajectories on a shared grid ------------------------------
    ts = [t for t in range(grid, int(span) + 1, grid)]
    cps_ratio_first_diverge = None
    converged_back = False
    print(f"{'time':>7} {'A CPS':>9} {'B CPS':>9} {'CPS A/B':>8} "
          f"{'A cookies':>10} {'B cookies':>10} {'cook A/B':>8}")
    rows = []
    for t in ts:
        a_cps = median([value_at(r["snaps"], t, "cookiesPs") for r in A])
        b_cps = median([value_at(r["snaps"], t, "cookiesPs") for r in B])
        a_ck = median([value_at(r["snaps"], t, "cookiesEarned") for r in A])
        b_ck = median([value_at(r["snaps"], t, "cookiesEarned") for r in B])
        cr = a_cps / b_cps if b_cps else 0.0
        kr = a_ck / b_ck if b_ck else 0.0
        rows.append((t, cr, kr))
        if cps_ratio_first_diverge is None and (cr > 1.1 or (cr < 0.9 and cr > 0)):
            cps_ratio_first_diverge = t
    # print a sparse view (every ~10th grid point)
    step = max(1, len(ts) // 14)
    for i in range(0, len(ts), step):
        t = ts[i]
        a_cps = median([value_at(r["snaps"], t, "cookiesPs") for r in A])
        b_cps = median([value_at(r["snaps"], t, "cookiesPs") for r in B])
        a_ck = median([value_at(r["snaps"], t, "cookiesEarned") for r in A])
        b_ck = median([value_at(r["snaps"], t, "cookiesEarned") for r in B])
        cr = a_cps / b_cps if b_cps else 0.0
        kr = a_ck / b_ck if b_ck else 0.0
        print(f"{t/3600:>6.2f}h {fmt(a_cps):>9} {fmt(b_cps):>9} {cr:>8.2f} "
              f"{fmt(a_ck):>10} {fmt(b_ck):>10} {kr:>8.2f}")

    # convergence: does the CPS ratio return toward 1 in the last third?
    if rows:
        late = [cr for (t, cr, kr) in rows if t > span * 2 / 3 and cr > 0]
        if late:
            late_med = median(late)
            converged_back = abs(late_med - 1.0) < 0.25
    print()
    if cps_ratio_first_diverge:
        print(f"→ CPS rates first diverged (>10%) at ~{cps_ratio_first_diverge/3600:.2f}h")
    print(f"→ late-run CPS ratio ≈ {'~1 (rates converged)' if converged_back else 'still apart'}; "
          "a high cookie ratio with CPS≈1 means one group banked an early lead it kept.")

    # --- luck decomposition ------------------------------------------------
    def buff_counts(runs):
        c = Counter()
        for r in runs:
            for b in r["buffs"]:
                c[b["name"]] += 1
        return c

    print("\n=== luck (total buff events across each group) ===")
    ca, cb = buff_counts(A), buff_counts(B)
    keys = sorted(set(ca) | set(cb), key=lambda k: -(ca[k] + cb[k]))
    print(f"{'buff':>22} {'A/run':>7} {'B/run':>7}")
    for k in keys[:10]:
        print(f"{k:>22} {ca[k]/len(A):>7.2f} {cb[k]/len(B):>7.2f}")
    fa = ca.get("Frenzy", 0) / len(A)
    fb = cb.get("Frenzy", 0) / len(B)
    if abs(fa - fb) / max(fa, fb, 1) > 0.15:
        print(f"  ⚠ Frenzy/run differs {fa:.1f} vs {fb:.1f} — luck is uneven even across "
              f"{len(A)}+{len(B)} runs; gather more runs or longer span.")
    else:
        print(f"  Frenzy/run {fa:.1f} vs {fb:.1f} — luck roughly balanced across the groups ✓")

    # --- strategy decomposition --------------------------------------------
    def buy_mix(runs):
        kinds = Counter()
        for r in runs:
            for x in r["buys"]:
                kinds[x.get("buy_kind", "?")] += 1
        return {k: v / len(runs) for k, v in kinds.items()}

    print("\n=== strategy (avg purchases per run) ===")
    ma, mb = buy_mix(A), buy_mix(B)
    for k in sorted(set(ma) | set(mb)):
        print(f"  {k:>10}: A {ma.get(k,0):>7.1f}   B {mb.get(k,0):>7.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
