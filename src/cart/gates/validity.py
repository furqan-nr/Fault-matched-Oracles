"""Implementation-validity gates (METHODOLOGY §5.3).

These verify implementation correctness, NOT outcomes. All must pass before results are reported.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from cart.events.table import load_events
from cart.selectors.context import SelectionContext
from cart.selectors.baselines import BASELINES
from cart.selectors.proposed import proposed_selector
from cart.selectors.cost_model import expected_cost
from cart.metrics.curves import event_metrics

_REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTORS = {**BASELINES, "proposed": proposed_selector}


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


def _labeled_context(ctx_full: SelectionContext, cand: list[str]) -> SelectionContext:
    return replace(ctx_full, units={t: ctx_full.units[t] for t in cand if t in ctx_full.units})


def gate_budget_compliance(ctx_full, by_event, budget=0.15) -> GateResult:
    over = 0
    for eid, recs in by_event.items():
        ctx = _labeled_context(ctx_full, [r["test_id"] for r in recs])
        for name, sel in SELECTORS.items():
            chosen = sel(ctx, eid, budget, seed=0)
            spent = sum(expected_cost(ctx, eid, t) for t in chosen)
            if spent > budget + 1e-9:
                over += 1
    return GateResult("budget_compliance", over == 0, f"{over} over-budget (event x selector)")


def gate_reproducibility(ctx_full, by_event) -> GateResult:
    bad = 0
    for eid, recs in by_event.items():
        ctx = _labeled_context(ctx_full, [r["test_id"] for r in recs])
        for name, sel in SELECTORS.items():
            if sel(ctx, eid, float("inf"), seed=0) != sel(ctx, eid, float("inf"), seed=0):
                bad += 1
    return GateResult("reproducibility", bad == 0, f"{bad} non-deterministic rankings")


def gate_leakage_absence(ctx_full, by_event, events) -> GateResult:
    """Injecting a fake CURRENT-event outcome must not change any ranking (§4.3)."""
    bad = 0
    for eid, recs in by_event.items():
        ev = events.get(eid)
        if ev is None:
            continue
        cand = [r["test_id"] for r in recs]
        ctx = _labeled_context(ctx_full, cand)
        before = {n: s(ctx, eid, float("inf"), seed=0) for n, s in SELECTORS.items()}
        poisoned = list(ctx_full.history) + [
            {"event_id": eid, "test_id": t, "label": "quality_regression", "event_date": ev.event_date}
            for t in cand
        ]
        ctx2 = replace(ctx, history=poisoned)
        after = {n: s(ctx2, eid, float("inf"), seed=0) for n, s in SELECTORS.items()}
        for n in SELECTORS:
            if before[n] != after[n]:
                bad += 1
    return GateResult("leakage_absence", bad == 0, f"{bad} rankings changed by current-event outcome")


def gate_label_reproducibility(labels) -> GateResult:
    mism = 0
    missing = 0
    for r in labels:
        p = Path(r["raw_artifact"])
        if not p.exists():
            missing += 1
            continue
        stored = json.loads(p.read_text())
        if stored.get("label") != r["label"]:
            mism += 1
    return GateResult("label_reproducibility", mism == 0 and missing == 0,
                      f"{mism} label mismatches, {missing} missing raw artifacts")


def gate_metric_correctness() -> GateResult:
    """Two hand-computed cases (§5.3)."""
    rank = [f"t{i}" for i in range(10)]
    cost = {t: 1.0 for t in rank}
    # Case A: only the 2nd test detects -> ttfr=2/10=0.2, auc=0.8, det@{5,10,20,40}={0,0,1,1}
    em = event_metrics(rank, cost, {"t1": True})
    okA = (abs(em.normalized_ttfr - 0.2) < 1e-9 and abs(em.auc_detection_vs_budget - 0.8) < 1e-9
           and em.detection_at_fraction[0.05] == 0 and em.detection_at_fraction[0.10] == 0
           and em.detection_at_fraction[0.20] == 1 and em.detection_at_fraction[0.40] == 1)
    # Case B: nothing detects -> ttfr=1.0 (censored), auc=0, all detection 0
    em2 = event_metrics(rank, cost, {})
    okB = (not em2.detected and abs(em2.normalized_ttfr - 1.0) < 1e-9
           and em2.auc_detection_vs_budget == 0.0 and all(v == 0 for v in em2.detection_at_fraction.values()))
    return GateResult("metric_correctness", okA and okB, f"caseA={okA}, caseB={okB}")


def gate_oracle_coverage(labels) -> GateResult:
    bad = sum(1 for r in labels if not r.get("oracle_strength") or not r.get("raw_artifact"))
    return GateResult("oracle_coverage", bad == 0, f"{bad} records missing oracle_strength/raw_artifact")


def run_all_gates(data_dir: str | Path = _REPO_ROOT / "data") -> dict[str, Any]:
    data_dir = Path(data_dir)
    labels = json.loads((data_dir / "derived" / "labels.json").read_text()).get("labels", []) \
        if (data_dir / "derived" / "labels.json").exists() else []
    events = {e.event_id: e for e in load_events()}
    ctx_full = SelectionContext.load(data_dir)
    by_event: dict[str, list[dict]] = {}
    for r in labels:
        by_event.setdefault(r["event_id"], []).append(r)

    gates = [
        gate_metric_correctness(),
        gate_budget_compliance(ctx_full, by_event),
        gate_reproducibility(ctx_full, by_event),
        gate_leakage_absence(ctx_full, by_event, events),
        gate_label_reproducibility(labels),
        gate_oracle_coverage(labels),
    ]
    return {"all_passed": all(g.passed for g in gates),
            "gates": [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in gates]}
