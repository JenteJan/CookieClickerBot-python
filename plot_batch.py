#!/usr/bin/env python3
"""Live matplotlib window for a batch A/B run.

Tails every bat-a-* / bat-b-* trial log and updates a window showing each
group's MEDIAN cumulative cookies as a line, with a shaded band spanning that
group's min..max across its instances. Log y-axis (cookies span many orders of
magnitude). Decoupled from the batch runner — works on a live or finished
batch, and never blocks it.

    python plot_batch.py                 # auto-detect bat-a-*/bat-b-*
    python plot_batch.py --interval 3    # refresh seconds
    python plot_batch.py --metric cps    # CPS instead of cookies

Usually auto-launched by the batch runner; you can also run it by hand.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

# Prefer a native interactive window; fall back gracefully if unavailable.
for _bk in ("macosx", "qt5agg", "tkagg"):
    try:
        matplotlib.use(_bk)
        break
    except Exception:
        continue

import matplotlib.pyplot as plt  # noqa: E402

from cookiebot.config import PROFILES_DIR, profile_trials_dir  # noqa: E402


def _read_series(profile: str, metric_key: str) -> tuple[list[float], list[float]]:
    """Return (times_seconds, values) from a profile's newest trial log."""
    d = profile_trials_dir(profile)
    if not d.exists():
        return [], []
    logs = sorted(d.glob("trial_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return [], []
    ts, vs = [], []
    try:
        for line in open(logs[0]):
            r = json.loads(line)
            if r.get("kind") == "snapshot":
                ts.append(r["t"])
                vs.append(float(r.get(metric_key, 0.0)))
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return ts, vs


def _group_profiles(prefix: str) -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    return sorted(d.name for d in PROFILES_DIR.iterdir()
                  if d.is_dir() and d.name.startswith(prefix))


def _resample(series: list[tuple[list[float], list[float]]], grid: list[float]) -> list[list[float]]:
    """For each run, the value at or before each grid time. Returns per-grid-point
    lists of the runs that have data there."""
    cols: list[list[float]] = [[] for _ in grid]
    for ts, vs in series:
        if not ts:
            continue
        j = 0
        for gi, gt in enumerate(grid):
            while j + 1 < len(ts) and ts[j + 1] <= gt:
                j += 1
            if ts[j] <= gt:
                cols[gi].append(vs[j])
    return cols


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=3.0)
    # base = unbuffed CPS (true build strength, no Frenzy spikes) — the default,
    # since it's the fair A/B measure. cookies = cumulative lifetime baked.
    # cps = raw buffed CPS (spiky; only for reference).
    ap.add_argument("--metric", choices=("base", "cookies", "cps"), default="base")
    args = ap.parse_args(argv)
    metric_key = {
        "base": "unbuffedCps",
        "cookies": "cookiesEarned",
        "cps": "cookiesPs",
    }[args.metric]
    ylabel = {
        "base": "base CPS (unbuffed)",
        "cookies": "cumulative cookies",
        "cps": "CPS (buffed, spiky)",
    }[args.metric]

    plt.ion()
    fig, ax = plt.subplots(figsize=(11, 6))
    fig.canvas.manager.set_window_title("Cookie Clicker batch A/B")
    colors = {"A": "tab:cyan", "B": "tab:orange"}

    while True:
        groups = {"A": _group_profiles("bat-a-"), "B": _group_profiles("bat-b-")}
        if not groups["A"] and not groups["B"]:
            ax.clear()
            ax.set_title("waiting for batch profiles (bat-a-* / bat-b-*)…")
            plt.pause(args.interval)
            continue

        ax.clear()
        for label in ("A", "B"):
            series = [_read_series(p, metric_key) for p in groups[label]]
            series = [s for s in series if s[0]]  # only runs with data
            if not series:
                continue
            span = max(max(ts) for ts, _ in series)
            n_grid = 200
            grid = [span * i / n_grid for i in range(1, n_grid + 1)]
            cols = _resample(series, grid)
            xs, med, lo, hi = [], [], [], []
            for gt, col in zip(grid, cols):
                if not col:
                    continue
                xs.append(gt / 60.0)  # minutes
                med.append(_median(col))
                lo.append(min(col))
                hi.append(max(col))
            if not xs:
                continue
            c = colors[label]
            ax.plot(xs, med, color=c, lw=2,
                    label=f"{label} median (n={len(series)})")
            ax.fill_between(xs, lo, hi, color=c, alpha=0.20,
                            label=f"{label} min–max")

        ax.set_yscale("log")
        ax.set_xlabel("minutes")
        ax.set_ylabel(ylabel + "  (log)")
        ax.set_title(f"Batch A/B — {ylabel}: median line, shaded min–max band per group")
        ax.grid(True, which="both", ls=":", alpha=0.4)
        ax.legend(loc="upper left", fontsize=9)
        fig.tight_layout()

        # plt.pause services the GUI event loop AND sleeps; if the window is
        # closed, bail out cleanly.
        if not plt.fignum_exists(fig.number):
            break
        plt.pause(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
