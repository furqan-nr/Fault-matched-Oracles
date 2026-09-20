"""Ground-truth label engine (METHODOLOGY §2.1, §2.6).

Per (event_id, test_id): build baseline + candidate transpilers, profile the baseline, run the
candidate, apply the tiered oracles, and assign a label with precedence
  functional_fail > semantic_fail > quality_regression > performance_regression > pass.

Raw evidence is written write-once to data/raw/<event_id>/<test_id>/result.json (never
overwritten). Derived labels + the per-event baseline profile are regenerable.

This increment processes events whose baseline and candidate transpilers can be built in-process:
the MUTATION events (baseline = preset PM; candidate = mutation operator on the same build).
Historical events (different candidate_sha) require their per-event from-source venvs and are
skipped here with a clear reason until those builds exist.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Callable

from qiskit import QuantumCircuit

from cart.events.schema import Event, FaultSource, FaultType
from cart.events.mutations import baseline_transpiler, get_operator
from cart.manifest.backends import coupling_map_for
from cart.manifest.circuits import build
from cart.manifest.static_manifest import DEFAULT_BASIS, TestUnit, enumerate_test_units
from cart.manifest.instrumentation import instrumented_transpile, measure_cost, _count_2q
from cart.oracles.semantic import check_semantic
from cart.oracles.quality import evaluate_quality, QualityThresholds, count_2q
from cart.oracles.performance import screen_performance

_REPO_ROOT = Path(__file__).resolve().parents[3]

LABEL_FOR_FAULT = {
    FaultType.functional: "functional_fail",
    FaultType.semantic: "semantic_fail",
    FaultType.quality: "quality_regression",
    FaultType.performance: "performance_regression",
    # Output-invisible channels (canonical ledger vocabulary). The determinism oracle emits
    # "quality_regression" on a non-deterministic candidate (see historical_runner property branch).
    FaultType.contract_metadata: "contract_metadata_fail",
    FaultType.determinism: "quality_regression",
}


class EventNotReady(Exception):
    pass


@dataclass
class LabelRecord:
    event_id: str
    test_id: str
    baseline_sha: str
    candidate_sha: str
    event_environment_id: str
    label: str
    fault_id_detected: str | None
    oracle_strength: str
    oracle_equivalent: bool | None
    confirmed: bool
    delta_2q: int
    delta_depth: int
    suspected_perf_regression: bool
    cpu_time_s: float                # CPU process time — stable cost-calibration metric
    transpilation_time_s: float      # wall-clock — secondary reference
    oracle_cost_s: float
    total_cost_s: float              # = cpu_time_s + oracle_cost_s (calibration cost)
    raw_artifact: str
    raw_sha256: str
    details: dict[str, Any] = field(default_factory=dict)


def _base_config(unit: TestUnit):
    opt = int(unit.transpiler_config_id.split("+")[0].removeprefix("opt"))
    cmap = coupling_map_for(unit.backend_id, unit.n_qubits)
    return dict(optimization_level=opt, coupling_map=cmap,
                basis_gates=list(DEFAULT_BASIS), seed_transpiler=1234)


def _transpilers(event: Event, cfg) -> tuple[Callable, Callable]:
    """Return (baseline_transpiler, candidate_transpiler) for the event."""
    if event.fault_source == FaultSource.mutation:
        if not event.mutation_family:
            raise EventNotReady(f"{event.event_id}: mutation missing family")
        return baseline_transpiler(cfg), get_operator(event.mutation_family).transpiler(cfg)
    raise EventNotReady(
        f"{event.event_id}: historical events need per-event from-source builds "
        "(candidate_sha != baseline) — not runnable in-process yet"
    )


def _timed_runs(fn: Callable[[QuantumCircuit], QuantumCircuit], circuit: QuantumCircuit, k: int):
    # Appendix F1 pre-declared CPU process time for the performance screen (was perf_counter);
    # base/candidate use the same metric, so the relative slowdown the screen keys on is preserved.
    times, out = [], None
    for _ in range(k):
        t0 = time.process_time()
        out = fn(circuit)
        times.append(time.process_time() - t0)
    return out, times


def run_event_test(event: Event, unit: TestUnit, out_root: Path,
                   thresholds: QualityThresholds | None = None, perf_runs: int = 3,
                   cost_repeats: int = 5, cost_cache: dict | None = None) -> LabelRecord:
    cfg = _base_config(unit)
    circuit = build(unit.circuit_family, unit.n_qubits, seed=1234, measured=False)
    base_fn, cand_fn = _transpilers(event, cfg)

    # baseline profile (instrumented) — stage/memory/quality evidence ONLY, not the cost
    baseline_out, prof = instrumented_transpile(
        circuit, coupling_map=cfg["coupling_map"], basis_gates=cfg["basis_gates"],
        optimization_level=cfg["optimization_level"], seed_transpiler=cfg["seed_transpiler"])
    # absolute cost: clean (un-instrumented, warmup-discarded) median of >=5 process_time runs.
    # Cached per unit — the baseline transpile is event-independent for mutation events, so it is
    # measured once and reused across events (avoids N x redundant expensive transpiles).
    cost_stats = (cost_cache or {}).get(unit.test_id)
    if cost_stats is None:
        _, cost_stats = measure_cost(base_fn, circuit, repeats=cost_repeats, warmup=1)
        if cost_cache is not None:
            cost_cache[unit.test_id] = cost_stats
    _, base_times = _timed_runs(base_fn, circuit, perf_runs)

    # candidate run (functional check)
    label = "pass"
    functional = False
    try:
        candidate_out, cand_times = _timed_runs(cand_fn, circuit, perf_runs)
    except Exception as exc:  # transpilation crash -> functional fault
        functional = True
        candidate_out, cand_times = None, [0.0]
        functional_detail = repr(exc)

    if functional:
        sem = None
        qual = None
        perf = screen_performance(base_times, [0.0])
        label = "functional_fail"
        oracle_strength, oracle_equiv, confirmed = "structural", None, True
        d2q = d_depth = 0
        details = {"functional_error": functional_detail}
    else:
        sem = check_semantic(circuit, candidate_out, coupling_map=cfg["coupling_map"],
                             basis_gates=cfg["basis_gates"])
        qual = evaluate_quality(baseline_out, candidate_out, thresholds)
        perf = screen_performance(base_times, cand_times,
                                  slowdown_threshold=_perf_threshold())
        oracle_strength = sem.strength
        oracle_equiv = sem.equivalent
        d2q, d_depth = qual.delta_2q, qual.delta_depth

        # structural invalidity (out-of-basis / coupling violation) -> functional fault
        if sem.strength == "structural" and sem.details.get("structural_ok") is False:
            label = "functional_fail"
            confirmed = True
        elif oracle_equiv is False:
            label = "semantic_fail"
            confirmed = (sem.strength == "exact")
        elif qual.is_regression:
            label = "quality_regression"
            confirmed = True
        elif perf.suspected_regression:
            label = "performance_regression"
            confirmed = False  # exploratory; needs Stage-2 (§2.5)
        else:
            label = "pass"
            confirmed = True
        details = {"quality": asdict(qual), "performance": asdict(perf),
                   "oracle": sem.details}

    # fault_id detected only if the label matches the event's specific fault_type (§2.6)
    expected = LABEL_FOR_FAULT.get(event.fault_type)
    fault_id_detected = event.fault_id if label == expected else None

    oracle_cost = sem.cost_s if sem else 0.0
    total_cost = cost_stats["cpu_time_s"] + oracle_cost   # clean-median CPU process time + oracle est

    record_core = {
        "event_id": event.event_id, "test_id": unit.test_id,
        "baseline_sha": event.baseline_sha, "candidate_sha": event.candidate_sha,
        "event_environment_id": event.event_environment_id,
        "label": label, "fault_id_detected": fault_id_detected,
        "oracle_strength": oracle_strength, "oracle_equivalent": oracle_equiv,
        "confirmed": confirmed,
        "delta_2q": d2q, "delta_depth": d_depth,
        "suspected_perf_regression": perf.suspected_regression,
        "cpu_time_s": cost_stats["cpu_time_s"],
        "transpilation_time_s": prof.transpilation_time_s,
        "oracle_cost_s": oracle_cost, "total_cost_s": total_cost,
        "details": details,
    }

    # baseline profile for profiles.json: stage/memory from the instrumented run, cost + dispersion from
    # the clean runs (median overrides the single-run instrumented cpu_time_s; keep the latter for reference).
    baseline_profile = {**prof.to_dict(),
                        "cpu_time_s": cost_stats["cpu_time_s"],
                        "cpu_time_instrumented_s": prof.cpu_time_s,
                        "cost_median_s": cost_stats["cost_median_s"],
                        "cost_min_s": cost_stats["cost_min_s"],
                        "cost_max_s": cost_stats["cost_max_s"],
                        "cost_iqr_s": cost_stats["cost_iqr_s"],
                        "cost_repeats": cost_stats["cost_repeats"],
                        "cost_warmup": cost_stats["cost_warmup"]}
    raw_path, persisted, raw_hash = _write_raw(out_root, event, unit, record_core, baseline_profile)
    # Derive the record from the PERSISTED (write-once) artifact so labels reproduce exactly from
    # raw on every re-run -- including timing-dependent performance labels (§5.3 reproducibility).
    fields = [f for f in LabelRecord.__dataclass_fields__ if f not in ("raw_artifact", "raw_sha256")]
    # Prefer persisted (write-once) values; fall back to freshly computed core for fields absent
    # from older raw artifacts (e.g. cpu_time_s added after the artifact was first written).
    record = LabelRecord(raw_artifact=str(raw_path), raw_sha256=raw_hash,
                         **{k: persisted.get(k, record_core.get(k)) for k in fields})
    profile_entry = {
        "event_id": event.event_id, "baseline_sha": event.baseline_sha,
        "test_id": unit.test_id, "event_environment_id": event.event_environment_id,
        **persisted["baseline_profile"],
    }
    return record, profile_entry


def _perf_threshold() -> float:
    from cart.oracles.quality import _DEFAULT_THRESHOLDS
    import yaml
    d = yaml.safe_load(Path(_DEFAULT_THRESHOLDS).read_text())
    return float(d.get("performance", {}).get("stage1_slowdown_threshold", 0.20))


def _write_raw(out_root: Path, event: Event, unit: TestUnit, core: dict, baseline_profile: dict) -> tuple[Path, str]:
    """Write-once raw artifact (never overwrite existing raw evidence)."""
    d = out_root / "raw" / event.event_id / unit.test_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "result.json"
    payload = {"schema": "ground_truth_result/v1", **core,
               "baseline_profile": baseline_profile}
    blob = json.dumps(payload, indent=2, sort_keys=True)
    if not path.exists():
        path.write_text(blob)
    # Hash the PERSISTED (write-once) content, so the digest identifies the immutable artifact
    # and is stable across re-runs even though timing fields vary in a fresh in-memory blob.
    on_disk = path.read_text()
    digest = hashlib.sha256(on_disk.encode()).hexdigest()
    return path, json.loads(on_disk), digest


def run_ground_truth(events: list[Event], units: list[TestUnit], out_root: str | Path,
                     *, unit_limit: int | None = None, cost_repeats: int = 5) -> dict[str, Any]:
    out_root = Path(out_root)
    th = QualityThresholds.load()
    use_units = units[:unit_limit] if unit_limit else units
    records: list[LabelRecord] = []
    profiles: list[dict] = []
    skipped: list[str] = []
    cost_cache: dict[str, dict] = {}   # per-unit baseline cost (event-independent for mutations)

    for ev in events:
        try:
            _transpilers(ev, _base_config(use_units[0]))  # readiness probe
        except EventNotReady as e:
            skipped.append(str(e))
            continue
        for u in use_units:
            rec, prof_entry = run_event_test(ev, u, out_root, thresholds=th,
                                             cost_repeats=cost_repeats, cost_cache=cost_cache)
            records.append(rec)
            profiles.append(prof_entry)

    # derived labels (regenerable) -> data/derived/labels.json
    labels_path = out_root / "derived" / "labels.json"
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(json.dumps({"schema": "labels/v1",
                                       "n": len(records),
                                       "labels": [asdict(r) for r in records]}, indent=2))

    # event-keyed baseline profile (§0.3) -> data/profile_baseline/profiles.json
    prof_path = out_root / "profile_baseline" / "profiles.json"
    prof_path.parent.mkdir(parents=True, exist_ok=True)
    prof_path.write_text(json.dumps({"schema": "test_profile_baseline/v1",
                                     "key": ["event_id", "baseline_sha", "test_id", "event_environment_id"],
                                     "n": len(profiles), "profiles": profiles}, indent=2))

    summary: dict[str, Any] = {"n_records": len(records), "n_events_skipped": len(skipped),
                               "skipped": skipped, "labels_path": str(labels_path),
                               "profiles_path": str(prof_path), "label_counts": {}}
    for r in records:
        summary["label_counts"][r.label] = summary["label_counts"].get(r.label, 0) + 1
    return summary
