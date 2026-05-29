#!/usr/bin/env python3
"""Compare two A/B trial logs produced by the bot (cfg.ab_log / --ab-log).

Usage:
    python compare_trials.py A.jsonl B.jsonl
    python compare_trials.py saves/profiles/New*/trials/trial_*.jsonl saves/profiles/Old*/trials/trial_*.jsonl

It aligns both runs on their shared time axis and reports:
  - cookie trajectory at matched timestamps (who's ahead, by how much)
  - luck parity: whether the same buffs/golden cookies fired at the same times
    (if they diverge, a cookie gap can't be cleanly credited to strategy)
  - the divergence point: first time the buff timeline differs
  - purchase summaries per run

Pure stdlib so it runs in the venv with no extra deps.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: Path) -> dict:
    meta, snaps, buys, buffs = {}, [], [], []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.get("kind")
            if kind == "meta":
                meta = row
            elif kind == "snapshot":
                snaps.append(row)
            elif kind == "buy":
                buys.append(row)
            elif kind == "buff":
                buffs.append(row)
    return {"meta": meta, "snaps": snaps, "buys": buys, "buffs": buffs, "path": path}


def fmt(n: float) -> str:
    for thr, suf in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")]:
        if abs(n) >= thr:
            return f"{n / thr:.2f}{suf}"
    return f"{n:.0f}"


def at_time(snaps: list[dict], t: float) -> dict | None:
    """Last snapshot at or before time t."""
    best = None
    for s in snaps:
        if s["t"] <= t:
            best = s
        else:
            break
    return best


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    a, b = load(Path(argv[0])), load(Path(argv[1]))

    la = a["meta"].get("profile", argv[0])
    lb = b["meta"].get("profile", argv[1])
    print(f"A = {la}   (seed={a['meta'].get('seed')!r}, payback={a['meta'].get('payback_mode')})")
    print(f"B = {lb}   (seed={b['meta'].get('seed')!r}, payback={b['meta'].get('payback_mode')})")
    if a["meta"].get("seed") != b["meta"].get("seed"):
        print("  ⚠ different seeds — luck is NOT controlled; treat results as noisy.")
    print()

    # --- luck parity: compare buff onset timelines -------------------------
    def buff_timeline(d):
        return [(round(x["t"], 1), x["name"]) for x in d["buffs"]]

    ta, tb = buff_timeline(a), buff_timeline(b)
    print(f"luck events: A={len(ta)} buffs, B={len(tb)} buffs")
    diverge_t = None
    for i in range(min(len(ta), len(tb))):
        if ta[i] != tb[i]:
            diverge_t = min(ta[i][0], tb[i][0])
            print(f"  buff timelines DIVERGE at ~{diverge_t}s: A={ta[i]} vs B={tb[i]}")
            break
    else:
        if len(ta) == len(tb):
            print("  buff timelines IDENTICAL — luck held the whole run ✓")
        else:
            diverge_t = min(ta[len(tb):] + tb[len(ta):], key=lambda x: x[0])[0] if (ta or tb) else None
            print(f"  buff timelines match until one run has extra events (~{diverge_t}s)")
    print()

    # --- cookie trajectory at matched times --------------------------------
    last_t = min(a["snaps"][-1]["t"], b["snaps"][-1]["t"]) if a["snaps"] and b["snaps"] else 0
    print(f"{'time':>8}  {'A cookies':>12}  {'B cookies':>12}  {'A/B ratio':>9}  leader")
    marks = [t for t in (60, 300, 600, 1200, 1800, 3600) if t <= last_t] or [last_t]
    for t in marks:
        sa, sb = at_time(a["snaps"], t), at_time(b["snaps"], t)
        if not sa or not sb:
            continue
        ca, cb = sa["cookiesEarned"], sb["cookiesEarned"]
        ratio = (ca / cb) if cb else float("inf")
        leader = la if ca > cb else (lb if cb > ca else "tie")
        print(f"{t:>7}s  {fmt(ca):>12}  {fmt(cb):>12}  {ratio:>9.3f}  {leader}")
    print()

    # --- purchase summary --------------------------------------------------
    for d, label in ((a, la), (b, lb)):
        kinds = {}
        for x in d["buys"]:
            kinds[x["buy_kind"]] = kinds.get(x["buy_kind"], 0) + 1
        print(f"{label}: {len(d['buys'])} buys " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))

    if diverge_t is not None:
        print(f"\n→ Compare cookie ratios BEFORE ~{diverge_t}s for a clean strategy read;")
        print("  after that, luck differs and the gap mixes strategy + RNG.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
