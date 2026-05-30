"""Batch A/B runner: spawn N headless bots per group, aggregate live.

Why processes, not threads: each bot makes blocking Selenium calls, so 20 in one
Python process would serialize on the GIL. Each instance is a separate
subprocess running the normal single-bot path (cookieBot.py --no-menu
--headless --profile …), reusing all the proven logic. Their settings differ
because each group's profiles carry different settings.json. No shared seed:
golden-cookie luck can't be seed-controlled, so independent runs + averaging is
the statistically valid approach — the spread is the point.

The runner reads each profile's trial log to show live per-group aggregates.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.console import Group as RGroup
from rich.live import Live
from rich.table import Table
from rich.text import Text

from cookiebot.config import (
    PROJECT_DIR,
    Config,
    profile_trials_dir,
)
from cookiebot.persistence import (
    clone_profile_save,
    create_profile,
    save_profile_settings,
)

log = logging.getLogger("cookiebot.batch")


class BatchABTest:
    def __init__(
        self,
        cfg_a: Config,
        cfg_b: Config,
        n_per_group: int,
        source: str,
        fresh: bool,
        variable: str,
        console: Console | None = None,
    ) -> None:
        self.cfg_a = cfg_a
        self.cfg_b = cfg_b
        self.n = n_per_group
        self.source = source
        self.fresh = fresh
        self.variable = variable
        self.console = console or Console()
        self.procs: list[subprocess.Popen] = []
        self._plot_proc: subprocess.Popen | None = None
        self.profiles_a: list[str] = []
        self.profiles_b: list[str] = []
        self._t0 = time.monotonic()
        # Time series for the live graph. We plot cumulative cookies (monotonic
        # and smooth — the real 'who's ahead' signal) rather than instantaneous
        # CPS, which is too spiky to read (one Frenzy spikes a single instance
        # and flattens everything else on a shared axis).
        self._series_t: list[float] = []
        self._series: dict[str, dict[str, list[float]]] = {
            "A": {"median": [], "lo": [], "hi": []},
            "B": {"median": [], "lo": [], "hi": []},
        }

    def _make_group(self, base: Config, prefix: str) -> list[str]:
        names = []
        for i in range(self.n):
            name = f"{prefix}{i:02d}"
            create_profile(name)
            clone_profile_save("" if self.fresh else self.source, name)
            cfg = Config(**{k: v for k, v in asdict(base).items()})
            cfg.save_profile = name
            cfg.ab_log = True
            cfg.ab_seed = ""        # independent luck per run
            cfg.headless = True
            cfg.fresh = self.fresh
            # CPU savers for 20 concurrent headless browsers: stop rendering and
            # slow the purchase tick from 50ms to 200ms (the heavy part is the
            # per-tick Selenium snapshot; golden cookies are popped by an in-page
            # interval regardless, so a slightly slower buy cadence is harmless).
            cfg.disable_rendering = True
            cfg.purchase_period_s = max(cfg.purchase_period_s, 0.2)
            save_profile_settings(cfg, profile=name)
            names.append(name)
        return names

    def _spawn(self, profile: str) -> subprocess.Popen:
        cmd = [sys.executable, "cookieBot.py", "--no-menu", "--headless",
               "--profile", profile, "--ab-log"]
        if self.fresh:
            cmd.append("--fresh")  # hard-reset in the browser; don't load a save
        return subprocess.Popen(
            cmd, cwd=str(PROJECT_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _spawn_plot(self) -> subprocess.Popen | None:
        """Launch the standalone live matplotlib window. Best-effort: if the GUI
        backend isn't available (e.g. a pure SSH session) we just skip it — the
        rich table + plotext graph still work."""
        try:
            return subprocess.Popen(
                [sys.executable, "plot_batch.py"],
                cwd=str(PROJECT_DIR),
            )
        except Exception:
            log.warning("could not launch the plot window; CLI graph still active")
            return None

    def run(self) -> None:
        log.info("batch A/B: %d runs per group, variable=%s", self.n, self.variable)
        self.profiles_a = self._make_group(self.cfg_a, "bat-a-")
        self.profiles_b = self._make_group(self.cfg_b, "bat-b-")

        # Stagger spawns slightly so 20 browsers don't all hammer startup at once.
        for name in self.profiles_a + self.profiles_b:
            self.procs.append(self._spawn(name))
            time.sleep(0.5)
        log.info("spawned %d headless instances", len(self.procs))

        # Launch the live matplotlib window in its own process (decoupled — it
        # tails the trial logs and never blocks this runner).
        self._plot_proc = self._spawn_plot()

        try:
            with Live(self._render(), console=self.console, refresh_per_second=1, screen=False) as live:
                while any(p.poll() is None for p in self.procs):
                    self._sample_series()
                    live.update(self._render())
                    time.sleep(2.0)
        except KeyboardInterrupt:
            log.info("stopping batch on user request")
        finally:
            for p in self.procs:
                if p.poll() is None:
                    p.terminate()
            # give them a moment to save + exit cleanly
            time.sleep(3.0)
            for p in self.procs:
                if p.poll() is None:
                    p.kill()
            self.console.print(self._render())
            self.console.print("\n[bold]Batch complete.[/bold] Aggregate the logs with analyze_batch.py.")
            # Leave the plot window open so the user can inspect the final
            # curves; it tails the logs and will simply stop updating.
            self.console.print("[dim]The plot window stays open; close it when done.[/dim]")

    # ---- live aggregation -------------------------------------------------

    def _latest(self, profile: str) -> dict | None:
        d = profile_trials_dir(profile)
        if not d.exists():
            return None
        logs = sorted(d.glob("trial_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return None
        last = None
        try:
            for line in open(logs[0]):
                row = json.loads(line)
                if row.get("kind") == "snapshot":
                    last = row
        except (OSError, json.JSONDecodeError):
            return None
        return last

    def _group_stats(self, profiles: list[str]) -> dict:
        cps, cookies = [], []
        for name in profiles:
            s = self._latest(name)
            if s:
                # Base (unbuffed) CPS — stable build strength, not the x7 Frenzy
                # spike. Fall back to cookiesPs for old logs without the field.
                cps.append(s.get("unbuffedCps", s.get("cookiesPs", 0.0)))
                cookies.append(s.get("cookiesEarned", 0.0))
        all_names = self.profiles_a + self.profiles_b
        running = sum(
            1 for name in profiles
            if (idx := all_names.index(name)) < len(self.procs) and self.procs[idx].poll() is None
        )
        return {
            "n": len(profiles),
            "running": running,
            "reporting": len(cps),  # how many instances actually have data yet
            "cps": _summary(cps),
            "cookies": _summary(cookies),
        }

    def _sample_series(self) -> None:
        """Append one time-point of each group's cumulative-cookies median/min/max."""
        minutes = (time.monotonic() - self._t0) / 60.0
        stats = {lbl: self._group_stats(p) for lbl, p in (("A", self.profiles_a), ("B", self.profiles_b))}
        if stats["A"]["reporting"] == 0 and stats["B"]["reporting"] == 0:
            return
        self._series_t.append(minutes)
        for lbl in ("A", "B"):
            ck = stats[lbl]["cookies"]
            self._series[lbl]["median"].append(ck["median"])
            self._series[lbl]["lo"].append(ck["min"])
            self._series[lbl]["hi"].append(ck["max"])

    def _graph(self, width: int = 78, height: int = 18) -> str:
        if len(self._series_t) < 2:
            return "[dim]collecting data for the graph…[/dim]"
        try:
            import plotext as plt
        except ImportError:
            return "[dim](install plotext for the live graph)[/dim]"
        # Cumulative cookies span many orders of magnitude over a run, so plot
        # log10 of the medians (the clean signal); min/max would clutter a small
        # terminal, so the table already shows the spread.
        import math
        def safelog(xs):
            return [math.log10(x) if x and x > 0 else 0.0 for x in xs]
        plt.clf()
        plt.theme("clear")
        plt.plotsize(width, height)
        x = self._series_t
        plt.plot(x, safelog(self._series["A"]["median"]), label="A median", color="cyan")
        plt.plot(x, safelog(self._series["B"]["median"]), label="B median", color="orange")
        plt.title("median cumulative cookies (log10) over time")
        plt.xlabel("minutes")
        return plt.build()

    def _render(self):
        elapsed = time.monotonic() - self._t0
        t = Table(title=f"Batch A/B  —  {elapsed/3600:.2f} h elapsed  —  variable: {self.variable}")
        t.add_column("group")
        t.add_column("var value")
        t.add_column("running", justify="right")
        t.add_column("samples", justify="right")  # instances contributing to the average
        t.add_column("mean baseCPS", justify="right")
        t.add_column("median baseCPS", justify="right")
        t.add_column("mean cookies", justify="right")
        t.add_column("median cookies", justify="right")
        for label, profs, cfg in (("A", self.profiles_a, self.cfg_a), ("B", self.profiles_b, self.cfg_b)):
            st = self._group_stats(profs)
            t.add_row(
                label,
                str(getattr(cfg, self.variable, "?")),
                f"{st['running']}/{st['n']}",
                f"{st['reporting']}/{st['n']}",
                _fmt(st["cps"]["mean"]),
                _fmt(st["cps"]["median"]),
                _fmt(st["cookies"]["mean"]),
                _fmt(st["cookies"]["median"]),
            )
        return RGroup(t, Text(), Text.from_ansi(self._graph()))


def _summary(xs: list[float]) -> dict:
    if not xs:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    s = sorted(xs)
    n = len(s)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return {"mean": sum(s) / n, "median": median, "min": s[0], "max": s[-1]}


def _fmt(n: float) -> str:
    for thr, suf in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")]:
        if abs(n) >= thr:
            return f"{n / thr:.2f}{suf}"
    return f"{n:.0f}"


def batch_main() -> None:
    import logging as _logging
    from rich.logging import RichHandler

    from cookiebot.menu import show_batch_menu
    from cookiebot.persistence import migrate_legacy_save

    console = Console()
    _logging.basicConfig(
        level=_logging.INFO, format="%(message)s", datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )
    migrate_legacy_save()
    picked = show_batch_menu()
    if picked is None:
        return
    BatchABTest(
        picked["cfg_a"], picked["cfg_b"], picked["n"],
        picked["source"], picked["fresh"], picked["variable"],
        console=console,
    ).run()
