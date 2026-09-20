"""Selection context (METHODOLOGY §3, §4.3).

Holds ONLY pre-execution information a selector may use:
  - static test metadata (manifest),
  - baseline-version costs (test_profile_baseline),
  - candidate change metadata (events),
  - historical outcomes strictly BEFORE the current event_date.

It must never expose the current event's candidate labels to a selector.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cart.events.schema import Event
from cart.events.table import load_events, DEFAULT_TABLE
from cart.manifest.static_manifest import TestUnit, enumerate_test_units, units_for

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data"


@dataclass
class SelectionContext:
    units: dict[str, TestUnit]                       # test_id -> metadata
    events: dict[str, Event]                         # event_id -> event
    baseline_costs: dict[tuple[str, str], float]     # (event_id, test_id) -> baseline_cost_s
    history: list[dict[str, Any]]                    # label rows: event_id, test_id, label, event_date
    default_cost_s: float = 0.01

    # ---- pre-execution lookups -------------------------------------------------------------
    def candidate_test_ids(self) -> list[str]:
        return list(self.units.keys())

    def baseline_cost(self, event_id: str, test_id: str) -> float:
        return self.baseline_costs.get((event_id, test_id), self.default_cost_s)

    def test_meta(self, test_id: str) -> TestUnit:
        return self.units[test_id]

    def event(self, event_id: str) -> Event:
        return self.events[event_id]

    def prior_failure_rate(self, test_id: str, before_date: str, exclude_event: str) -> float:
        """Fraction of PRIOR events (event_date < before_date) where this test detected a fault.
        Uses only historical outcomes — never the current/future event (leakage rule §4.3)."""
        seen = 0
        failed = 0
        for row in self.history:
            if row["test_id"] != test_id:
                continue
            if row["event_id"] == exclude_event:
                continue
            if row["event_date"] >= before_date:      # strictly before only
                continue
            seen += 1
            if row["label"] != "pass":
                failed += 1
        return (failed / seen) if seen else 0.0

    # ---- loading ---------------------------------------------------------------------------
    @classmethod
    def load(cls, data_dir: str | Path = _DATA, events_path: str | Path = DEFAULT_TABLE) -> "SelectionContext":
        data_dir = Path(data_dir)
        units = {u.test_id: u for u in units_for(data_dir)}   # costhet manifest if generated, else pilot
        events = {e.event_id: e for e in load_events(events_path)}

        baseline_costs: dict[tuple[str, str], float] = {}
        prof_path = data_dir / "profile_baseline" / "profiles.json"
        if prof_path.exists():
            for p in json.loads(prof_path.read_text()).get("profiles", []):
                # cost calibration uses CPU process time (stable on a shared laptop); wall-clock fallback
                cost = p.get("cpu_time_s", p.get("transpilation_time_s", 0.01))
                baseline_costs[(p["event_id"], p["test_id"])] = float(cost)

        history: list[dict[str, Any]] = []
        labels_path = data_dir / "derived" / "labels.json"
        if labels_path.exists():
            for r in json.loads(labels_path.read_text()).get("labels", []):
                ev = events.get(r["event_id"])
                history.append({
                    "event_id": r["event_id"], "test_id": r["test_id"], "label": r["label"],
                    "event_date": ev.event_date if ev else "9999-12-31",
                })

        return cls(units=units, events=events, baseline_costs=baseline_costs, history=history)
