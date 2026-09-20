"""Held-out evaluation (METHODOLOGY §5).

Compares the proposed risk_score selector against the five baselines on the ground-truth labels.
Metrics are computed per event and averaged, grouped by **evaluation_cohort** (forward_regression /
fix_boundary / mutation) so cohorts are never pooled (§1.1/§1.4) — in particular a forward regression is
never averaged together with fix-boundary events (which share fault_source='historical'). Each event has
one fault, so detection is 0/1.

This module computes the **Primary CI evaluation** (§5.1.1): it consumes only `data/derived/
labels.json`, whose test units are generic Benchpress units (`test_provenance = pre_existing`,
`available_before_candidate = true`). Post-fix targeted triggers (`extracted_from_fix`) are NEVER
in this pipeline — they are produced separately by the runner (`targeted_run.json`) and belong only
to the Secondary retrospective fault-revealing evaluation.
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from cart.events.schema import FaultSource
from cart.events.table import load_events
from cart.selectors.context import SelectionContext
from cart.selectors.baselines import BASELINES
from cart.selectors.proposed import proposed_selector
from cart.metrics.curves import (event_metrics, DEFAULT_FRACTIONS, CURVE_GRID,
                                 win_tie_loss, detection_curve, aggregate_seeds,
                                 cliffs_delta, cliffs_magnitude, vargha_delaney_a12, bootstrap_ci)

_REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTORS = {**BASELINES, "proposed": proposed_selector}
# Deterministic selectors run once; "random" is aggregated over many seeds (reviewer must-fix #3).
DETERMINISTIC = [n for n in SELECTORS if n != "random"]
RECALL_FRACTION = 0.20
DEFAULT_RANDOM_SEEDS = 20


def _load_labels(data_dir: Path) -> list[dict[str, Any]]:
    p = data_dir / "derived" / "labels.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("labels", [])


def oracle_false_positive_rate(labels: list[dict]) -> float:
    """Empirical FP rate (§2.6): regression warnings not upheld by confirmation."""
    warnings = [r for r in labels if r["label"] != "pass"]
    if not warnings:
        return 0.0
    unconfirmed = sum(1 for r in warnings if not r.get("confirmed", True))
    return unconfirmed / len(warnings)


def _run_metrics(sel, ctx, event_id, cost, detects, *, seed: int = 0):
    """Rank with `sel` (full budget) and return per-event metrics, restricted to labeled tests."""
    t0 = time.perf_counter()
    ranking = sel(ctx, event_id, float("inf"), seed=seed)
    overhead = time.perf_counter() - t0
    ranking = [t for t in ranking if t in cost]   # safety: only labeled tests
    return event_metrics(ranking, cost, detects), overhead


def group_by_cohort(payloads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group per-event payloads by evaluation_cohort so cohorts are never pooled (§1.1/§1.4):
    forward_regression, fix_boundary, and mutation each form their own group. A forward regression is
    therefore never averaged with fix-boundary events (which share fault_source='historical')."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in payloads:
        groups.setdefault(p.get("cohort") or p["source"], []).append(p)
    return groups


def evaluate(data_dir: str | Path = _REPO_ROOT / "data", cutoff_date: str | None = None,
             split: str = "all", random_seeds: int = DEFAULT_RANDOM_SEEDS) -> dict[str, Any]:
    """Held-out evaluation. In addition to the per-source means, this emits the expanded
    breakdown requested by review: per-event results, random over many seeds (median/min/max),
    win/tie/loss of proposed vs each baseline, and the detection-vs-budget curve. Cohorts
    (fault sources) are never pooled (METHODOLOGY §1.4/§5.4)."""
    data_dir = Path(data_dir)
    labels = _load_labels(data_dir)
    events = {e.event_id: e for e in load_events()}
    ctx_full = SelectionContext.load(data_dir)

    by_event: dict[str, list[dict]] = {}
    for r in labels:
        by_event.setdefault(r["event_id"], []).append(r)

    # Build per-event payloads, grouped by fault source (cohort).
    payloads: list[dict[str, Any]] = []
    for event_id, recs in by_event.items():
        ev = events.get(event_id)
        if ev is None:
            continue
        if split != "all":
            in_test = (cutoff_date is not None and ev.event_date >= cutoff_date)
            if split == "test" and not in_test:
                continue
            if split == "train" and in_test:
                continue
        cand = [r["test_id"] for r in recs]
        cost = {r["test_id"]: float(r["total_cost_s"]) for r in recs}
        detects = {r["test_id"]: (r["fault_id_detected"] == ev.fault_id) for r in recs}
        ctx = replace(ctx_full, units={t: ctx_full.units[t] for t in cand if t in ctx_full.units})
        payloads.append({"event_id": event_id, "source": ev.fault_source.value,
                         "cohort": ev.evaluation_cohort or ev.fault_source.value,
                         "cost": cost, "detects": detects, "ctx": ctx})

    def _mean(xs):
        return round(statistics.mean(xs), 4) if xs else None

    def _cost_summary(costs: list[float]) -> dict[str, Any]:
        if not costs:
            return {}
        cs = sorted(costs)
        mean = statistics.mean(cs)
        out = {"n": len(cs), "min": round(cs[0], 6), "max": round(cs[-1], 6),
               "median": round(statistics.median(cs), 6), "mean": round(mean, 6),
               "total": round(sum(cs), 6),
               "stdev": round(statistics.pstdev(cs), 6),
               "cv": round((statistics.pstdev(cs) / mean) if mean else 0.0, 4)}
        if len(cs) >= 4:
            q = statistics.quantiles(cs, n=4)
            out["p25"], out["p75"] = round(q[0], 6), round(q[2], 6)
            out["iqr"] = round(q[2] - q[0], 6)
        return out

    report: dict[str, Any] = {
        "split": split, "cutoff_date": cutoff_date, "random_seeds": random_seeds,
        "oracle_false_positive_rate": round(oracle_false_positive_rate(labels), 4),
        "grouped_by": "evaluation_cohort",
        "by_source": {}, "per_event": {}, "win_tie_loss": {},
        "random_multiseed": {}, "detection_curve": {"grid": list(CURVE_GRID), "by_source": {}},
        "cost_distribution": {}, "effect_sizes": {}, "bootstrap_ci": {},
    }

    groups = group_by_cohort(payloads)
    for source in sorted(groups):
        ps = groups[source]

        # --- deterministic selectors: one run each, per event -------------------------------
        det_em: dict[str, dict[str, Any]] = {n: {} for n in DETERMINISTIC}
        det_overhead: dict[str, list[float]] = {n: [] for n in DETERMINISTIC}
        for p in ps:
            for name in DETERMINISTIC:
                em, oh = _run_metrics(SELECTORS[name], p["ctx"], p["event_id"], p["cost"], p["detects"])
                det_em[name][p["event_id"]] = em
                det_overhead[name].append(oh)

        # --- random: many seeds -------------------------------------------------------------
        # per_seed_mean[metric] over seeds; rnd_event[event_id] -> (detected, nttfr) over seeds
        per_seed_mean = {"recall": [], "ttfr": [], "auc": []}
        per_seed_detfrac: dict[float, list[float]] = {f: [] for f in DEFAULT_FRACTIONS}
        per_seed_curve: list[list[float]] = []
        rnd_event: dict[str, list[tuple[bool, float]]] = {p["event_id"]: [] for p in ps}
        rnd_overhead: list[float] = []
        for seed in range(random_seeds):
            recall_s, ttfr_s, auc_s = [], [], []
            detfrac_s: dict[float, list[int]] = {f: [] for f in DEFAULT_FRACTIONS}
            seed_pairs: list[tuple[bool, float]] = []
            for p in ps:
                em, oh = _run_metrics(SELECTORS["random"], p["ctx"], p["event_id"],
                                      p["cost"], p["detects"], seed=seed)
                rnd_overhead.append(oh)
                recall_s.append(em.detection_at_fraction[RECALL_FRACTION])
                ttfr_s.append(em.normalized_ttfr)
                auc_s.append(em.auc_detection_vs_budget)
                for f in DEFAULT_FRACTIONS:
                    detfrac_s[f].append(em.detection_at_fraction[f])
                seed_pairs.append((em.detected, em.normalized_ttfr))
                rnd_event[p["event_id"]].append((em.detected, em.normalized_ttfr))
            per_seed_mean["recall"].append(statistics.mean(recall_s) if recall_s else 0.0)
            per_seed_mean["ttfr"].append(statistics.mean(ttfr_s) if ttfr_s else 1.0)
            per_seed_mean["auc"].append(statistics.mean(auc_s) if auc_s else 0.0)
            for f in DEFAULT_FRACTIONS:
                per_seed_detfrac[f].append(statistics.mean(detfrac_s[f]) if detfrac_s[f] else 0.0)
            per_seed_curve.append(detection_curve(seed_pairs))

        # random per-event median (for win/tie/loss and the curve)
        rnd_med_event: dict[str, tuple[bool, float]] = {}
        for eid, pairs in rnd_event.items():
            nts = sorted(nt for _, nt in pairs)
            med = statistics.median(nts) if nts else 1.0
            rnd_med_event[eid] = (med < 1.0 - 1e-9, med)

        # --- by_source means (back-compatible keys) ----------------------------------------
        bs: dict[str, Any] = {}
        for name in DETERMINISTIC:
            ems = [det_em[name][p["event_id"]] for p in ps]
            bs[name] = {
                "n_events": len(ems),
                f"recall@{int(RECALL_FRACTION*100)}%": _mean([e.detection_at_fraction[RECALL_FRACTION] for e in ems]),
                "mean_normalized_TTFR": _mean([e.normalized_ttfr for e in ems]),
                "mean_AUC_detection_vs_budget": _mean([e.auc_detection_vs_budget for e in ems]),
                "detection_at_fraction": {f"{int(f*100)}%": _mean([e.detection_at_fraction[f] for e in ems])
                                          for f in DEFAULT_FRACTIONS},
                "mean_selection_overhead_s": _mean(det_overhead[name]),
            }
        bs["random"] = {
            "n_events": len(ps), "n_seeds": random_seeds,
            f"recall@{int(RECALL_FRACTION*100)}%": _mean(per_seed_mean["recall"]),
            "mean_normalized_TTFR": _mean(per_seed_mean["ttfr"]),
            "mean_AUC_detection_vs_budget": _mean(per_seed_mean["auc"]),
            "mean_selection_overhead_s": _mean(rnd_overhead),
        }
        report["by_source"][source] = bs

        # --- random multiseed median/range -------------------------------------------------
        report["random_multiseed"][source] = {
            "n_seeds": random_seeds,
            f"recall@{int(RECALL_FRACTION*100)}%": aggregate_seeds(per_seed_mean["recall"]),
            "mean_normalized_TTFR": aggregate_seeds(per_seed_mean["ttfr"]),
            "mean_AUC_detection_vs_budget": aggregate_seeds(per_seed_mean["auc"]),
            "detection_at_fraction": {f"{int(f*100)}%": aggregate_seeds(per_seed_detfrac[f])
                                      for f in DEFAULT_FRACTIONS},
        }

        # --- cost distribution over the unique units (mean cost per unit across events) -----
        unit_costs: dict[str, list[float]] = {}
        for p in ps:
            for t, c in p["cost"].items():
                unit_costs.setdefault(t, []).append(c)
        per_unit_mean = [statistics.mean(v) for v in unit_costs.values()]
        # mean cost by width×backend
        bd_acc: dict[str, list[float]] = {}
        for t, v in unit_costs.items():
            meta = ctx_full.units.get(t)
            key = (f"n{meta.n_qubits}-{meta.backend_id}" if meta is not None else "unknown")
            bd_acc.setdefault(key, []).append(statistics.mean(v))
        report["cost_distribution"][source] = {
            "per_unit_mean_cost_s": _cost_summary(per_unit_mean),
            "by_width_backend_mean_s": {k: round(statistics.mean(v), 6) for k, v in sorted(bd_acc.items())},
        }

        # --- per-event table ---------------------------------------------------------------
        pe: dict[str, Any] = {}
        for p in ps:
            eid = p["event_id"]
            row: dict[str, Any] = {}
            for name in DETERMINISTIC:
                em = det_em[name][eid]
                row[name] = {"detected": em.detected, "normalized_TTFR": round(em.normalized_ttfr, 4),
                             "AUC": round(em.auc_detection_vs_budget, 4),
                             f"recall@{int(RECALL_FRACTION*100)}%": em.detection_at_fraction[RECALL_FRACTION]}
            det_med, nt_med = rnd_med_event[eid]
            row["random"] = {"detected": det_med, "normalized_TTFR_median": round(nt_med, 4),
                             "AUC_median": round(max(0.0, 1.0 - nt_med) if det_med else 0.0, 4)}
            pe[eid] = row
        report["per_event"][source] = pe

        # --- win/tie/loss: proposed vs each baseline ---------------------------------------
        prop_nttfr = {p["event_id"]: det_em["proposed"][p["event_id"]].normalized_ttfr for p in ps}
        wtl: dict[str, Any] = {}
        for name in DETERMINISTIC:
            if name == "proposed":
                continue
            base_nttfr = {p["event_id"]: det_em[name][p["event_id"]].normalized_ttfr for p in ps}
            wtl[name] = win_tie_loss(prop_nttfr, base_nttfr)
        wtl["random"] = win_tie_loss(prop_nttfr, {e: nt for e, (_, nt) in rnd_med_event.items()})
        report["win_tie_loss"][source] = wtl

        # --- effect sizes (Cliff's delta, Vargha–Delaney A12) + bootstrap CIs on AUC -------
        prop_auc = [det_em["proposed"][p["event_id"]].auc_detection_vs_budget for p in ps]
        es: dict[str, Any] = {}
        for name in DETERMINISTIC:
            if name == "proposed":
                continue
            base_auc = [det_em[name][p["event_id"]].auc_detection_vs_budget for p in ps]
            d = cliffs_delta(prop_auc, base_auc)
            es[name] = {"cliffs_delta": d, "magnitude": cliffs_magnitude(d),
                        "a12": vargha_delaney_a12(prop_auc, base_auc)}
        rnd_auc_ev = [(1.0 - nt if det else 0.0) for det, nt in
                      (rnd_med_event[p["event_id"]] for p in ps)]
        d = cliffs_delta(prop_auc, rnd_auc_ev)
        es["random"] = {"cliffs_delta": d, "magnitude": cliffs_magnitude(d),
                        "a12": vargha_delaney_a12(prop_auc, rnd_auc_ev)}
        report["effect_sizes"][source] = {"metric": "AUC_detection_vs_budget",
                                          "n_events": len(ps), "proposed_vs": es}
        bci = {name: bootstrap_ci([det_em[name][p["event_id"]].auc_detection_vs_budget for p in ps])
               for name in DETERMINISTIC}
        bci["random"] = bootstrap_ci(per_seed_mean["auc"])
        report["bootstrap_ci"][source] = {"metric": "AUC_detection_vs_budget", "by_selector": bci}

        # --- detection-vs-budget curve -----------------------------------------------------
        curves: dict[str, list[float]] = {}
        for name in DETERMINISTIC:
            curves[name] = detection_curve([(det_em[name][p["event_id"]].detected,
                                             det_em[name][p["event_id"]].normalized_ttfr) for p in ps])
        curves["random"] = detection_curve([rnd_med_event[p["event_id"]] for p in ps])
        # random min/max band across seeds, per grid point
        if per_seed_curve:
            band_min = [round(min(c[i] for c in per_seed_curve), 6) for i in range(len(CURVE_GRID))]
            band_max = [round(max(c[i] for c in per_seed_curve), 6) for i in range(len(CURVE_GRID))]
            curves["random_band_min"] = band_min
            curves["random_band_max"] = band_max
        report["detection_curve"]["by_source"][source] = curves

    return report


# --- Ablation + sensitivity (reuse cached labels; near-zero compute) -----------------------

def _build_payloads(data_dir: Path, cutoff_date: str | None, split: str) -> list[dict[str, Any]]:
    """Per-event (cost, detects, ctx) payloads — shared by ablation/sensitivity analyses."""
    data_dir = Path(data_dir)
    labels = _load_labels(data_dir)
    events = {e.event_id: e for e in load_events()}
    ctx_full = SelectionContext.load(data_dir)
    by_event: dict[str, list[dict]] = {}
    for r in labels:
        by_event.setdefault(r["event_id"], []).append(r)
    payloads: list[dict[str, Any]] = []
    for event_id, recs in by_event.items():
        ev = events.get(event_id)
        if ev is None:
            continue
        if split != "all":
            in_test = (cutoff_date is not None and ev.event_date >= cutoff_date)
            if split == "test" and not in_test:
                continue
            if split == "train" and in_test:
                continue
        cand = [r["test_id"] for r in recs]
        cost = {r["test_id"]: float(r["total_cost_s"]) for r in recs}
        detects = {r["test_id"]: (r["fault_id_detected"] == ev.fault_id) for r in recs}
        ctx = replace(ctx_full, units={t: ctx_full.units[t] for t in cand if t in ctx_full.units})
        payloads.append({"event_id": event_id, "source": ev.fault_source.value,
                         "cohort": ev.evaluation_cohort or ev.fault_source.value,
                         "cost": cost, "detects": detects, "ctx": ctx})
    return payloads


def _proposed_summary(payloads, *, ablate=(), eps_override=None, reserve_frac=None):
    """Mean AUC / nTTFR / recall@20% of the proposed selector (with optional ablation/params)
    per fault source, over the given payloads."""
    out: dict[str, Any] = {}
    for source in sorted({p["source"] for p in payloads}):
        ps = [p for p in payloads if p["source"] == source]
        aucs, ttfrs, recs = [], [], []
        for p in ps:
            ranking = proposed_selector(p["ctx"], p["event_id"], float("inf"), seed=0,
                                        ablate=ablate, eps_override=eps_override, reserve_frac=reserve_frac)
            ranking = [t for t in ranking if t in p["cost"]]
            em = event_metrics(ranking, p["cost"], p["detects"])
            aucs.append(em.auc_detection_vs_budget)
            ttfrs.append(em.normalized_ttfr)
            recs.append(em.detection_at_fraction[RECALL_FRACTION])
        n = len(ps) or 1
        out[source] = {"n_events": len(ps),
                       "mean_AUC": round(sum(aucs) / n, 4),
                       "mean_normalized_TTFR": round(sum(ttfrs) / n, 4),
                       f"recall@{int(RECALL_FRACTION*100)}%": round(sum(recs) / n, 4)}
    return out


def run_ablation(data_dir: str | Path = _REPO_ROOT / "data", cutoff_date: str | None = None,
                 split: str = "all") -> dict[str, Any]:
    payloads = _build_payloads(Path(data_dir), cutoff_date, split)
    variants = {"full": (), "no_novelty": ("novelty",), "no_change_stage": ("change_stage",),
                "no_oracle_confidence": ("oracle_confidence",), "no_impact_prior": ("impact_prior",)}
    return {"schema": "ablation/v1", "split": split,
            "variants": {name: _proposed_summary(payloads, ablate=ab) for name, ab in variants.items()}}


def run_sensitivity(data_dir: str | Path = _REPO_ROOT / "data", cutoff_date: str | None = None,
                    split: str = "all") -> dict[str, Any]:
    payloads = _build_payloads(Path(data_dir), cutoff_date, split)
    grid = []
    for reserve in (0.10, 0.15, 0.20):
        for eps in (0.01, 0.05, 0.10):
            grid.append({"reserve_frac": reserve, "epsilon": eps,
                         "result": _proposed_summary(payloads, eps_override=eps, reserve_frac=reserve)})
    return {"schema": "sensitivity/v1", "split": split, "grid": grid}
