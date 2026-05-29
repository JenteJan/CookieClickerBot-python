"""Structured A/B trial logging.

Writes one JSONL file per run under the profile's ``trials/`` folder. Each line
is one event with a monotonic ``t`` (seconds since trial start) so two runs can
be aligned on a shared timeline. Event kinds:

  - ``meta``     once at start: profile, seed, settings snapshot
  - ``snapshot`` periodic state (cookies, cps, buffs, counts)
  - ``buy``      a purchase (building / upgrade / bundle) with score + price
  - ``buff``     a buff/golden-cookie effect became active (luck event)

The buff events plus the buffs[] in snapshots are what let the analysis confirm
two seeded runs got identical luck before crediting strategy for any gap.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class TrialLogger:
    def __init__(self, path: Path, started_monotonic: float | None = None) -> None:
        self.path = path
        self._t0 = started_monotonic if started_monotonic is not None else time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered append so a crash still leaves a usable partial log.
        self._fh = open(path, "a", buffering=1)
        # Track which buffs we've already logged so each is recorded once per spell.
        self._active_buffs: set[str] = set()

    def _write(self, kind: str, **fields: Any) -> None:
        row = {"t": round(time.monotonic() - self._t0, 3), "kind": kind}
        row.update(fields)
        try:
            self._fh.write(json.dumps(row) + "\n")
        except Exception:
            log.exception("trial log write failed")

    def meta(self, **fields: Any) -> None:
        self._write("meta", **fields)

    def snapshot(self, snap: dict) -> None:
        self._write("snapshot", **snap)
        # Derive buff onset events from the snapshot's buff list (cheap, needs no
        # extra round-trip): anything newly present is a fresh luck event.
        current = set(snap.get("buffs", []))
        for name in current - self._active_buffs:
            self._write("buff", name=name)
        self._active_buffs = current

    def buy(self, kind: str, name: str, price: float, score: float, gain_cps: float | None = None) -> None:
        self._write("buy", buy_kind=kind, name=name, price=price, score=score, gain_cps=gain_cps)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
