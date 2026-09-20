"""Minimal per-event from-source venv runner (historical events).

For a historical event whose baseline+candidate Qiskit were built from source via
`build_qiskit_event` into per-event venvs, this runs the worker in each venv (subprocess), loads
the two transpiled circuits (QPY) back into the harness/anchor env, applies the tiered oracles, and
assigns a label. Sufficient to validate one fix-boundary event, the forward-regression event (H4),
and the functional event. It does NOT run the full Phase-2 sweep.

Per-event venvs are expected at:
  environment/_builds/<event_environment_id>-base/venv   (baseline, "good")
  environment/_builds/<event_environment_id>-cand/venv   (candidate, "buggy")
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from cart.events.schema import Event, FaultType
from cart.manifest.static_manifest import DEFAULT_BASIS, TestUnit
from cart.manifest.backends import coupling_map_for
from cart.manifest.circuits import build
from cart.oracles.semantic import check_semantic
from cart.oracles.quality import evaluate_quality, QualityThresholds
from cart.oracles.performance import screen_performance

_REPO_ROOT = Path(__file__).resolve().parents[3]

LABEL_FOR_FAULT = {FaultType.functional: "functional_fail", FaultType.semantic: "semantic_fail",
                   FaultType.quality: "quality_regression", FaultType.performance: "performance_regression",
                   # Output-invisible channels (canonical ledger). determinism -> the property/determinism
                   # oracle emits "quality_regression"; contract_metadata -> "contract_metadata_fail".
                   FaultType.contract_metadata: "contract_metadata_fail",
                   FaultType.determinism: "quality_regression"}


def _venv_python(env_id: str) -> Path | None:
    base = _REPO_ROOT / "environment" / "_builds" / env_id / "venv"
    for cand in (base / "bin" / "python", base / "Scripts" / "python.exe"):
        if cand.exists():
            return cand
    return None


def _run_worker(python_exe: str, unit: TestUnit, out_dir: Path, basis: list[str], seed: int = 1234) -> dict:
    opt = int(unit.transpiler_config_id.split("+")[0].removeprefix("opt"))
    cmd = [str(python_exe), "-m", "cart.labels.historical_worker",
           "--family", unit.circuit_family, "--n", str(unit.n_qubits), "--backend", unit.backend_id,
           "--opt", str(opt), "--basis", ",".join(basis), "--seed", str(seed), "--out", str(out_dir)]
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True,
                   capture_output=True, timeout=600)
    return json.loads((out_dir / "worker.json").read_text())


def _load_qpy(path: Path):
    from qiskit import qpy
    with open(path, "rb") as fh:
        return qpy.load(fh)[0]


def _is_num(x):
    try:
        float(x); return True
    except (TypeError, ValueError):
        return False


def _circuit_fingerprint(circ):
    """Structural fingerprint: gate order, qubit indices, numeric params, and final layout —
    sensitive to layout-only non-determinism (unlike op-counts/depth)."""
    ops = tuple((instr.operation.name,
                 tuple(circ.find_bit(q).index for q in instr.qubits),
                 tuple(round(float(p), 9) for p in getattr(instr.operation, "params", []) if _is_num(p)))
                for instr in circ.data)
    layout = circ.layout.final_index_layout() if circ.layout is not None else None
    return (ops, tuple(layout) if layout is not None else None)


def run_historical_event(
    event: Event, units: list[TestUnit], out_root: str | Path, *,
    baseline_python: str | None = None, candidate_python: str | None = None,
    candidate_basis: list[str] | None = None, thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
    """Run one historical event over `units`. `*_python` override the per-event venvs (tests pass
    sys.executable as a stand-in). `candidate_basis` overrides the candidate basis (functional
    fixture). Returns a summary with per-unit records."""
    out_root = Path(out_root)
    th = thresholds or QualityThresholds.load()
    bpy = baseline_python or (_venv_python(f"{event.event_environment_id}-base"))
    cpy = candidate_python or (_venv_python(f"{event.event_environment_id}-cand"))
    if not bpy or not cpy:
        raise FileNotFoundError(
            f"per-event venvs missing for {event.event_id}; build them first:\n"
            f"  build_qiskit_event {event.baseline_sha} {event.event_environment_id}-base\n"
            f"  build_qiskit_event {event.candidate_sha} {event.event_environment_id}-cand")

    records: list[dict] = []
    expected = LABEL_FOR_FAULT.get(event.fault_type)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for u in units:
            bdir, cdir = tmp / f"{u.test_id}-base", tmp / f"{u.test_id}-cand"
            bw = _run_worker(bpy, u, bdir, list(DEFAULT_BASIS))
            cw = _run_worker(cpy, u, cdir, candidate_basis or list(DEFAULT_BASIS))

            cmap = coupling_map_for(u.backend_id, u.n_qubits)
            original = build(u.circuit_family, u.n_qubits, seed=1234, measured=False)
            rec: dict[str, Any] = {"event_id": event.event_id, "test_id": u.test_id,
                                   "evaluation_cohort": event.evaluation_cohort,
                                   "baseline_qiskit": bw.get("qiskit_version"),
                                   "candidate_qiskit": cw.get("qiskit_version")}

            if bw["status"] == "error":
                rec.update(label="baseline_build_error", detail=bw.get("error"))
            elif cw["status"] == "error":  # candidate crashed -> functional fault
                rec.update(label="functional_fail", oracle_strength="structural",
                           detail=cw.get("error_type"))
            else:
                base_out = _load_qpy(bdir / "circuit.qpy")
                cand_out = _load_qpy(cdir / "circuit.qpy")
                sem = check_semantic(original, cand_out, coupling_map=cmap, basis_gates=list(DEFAULT_BASIS))
                qual = evaluate_quality(base_out, cand_out, th)
                perf = screen_performance([bw.get("cpu_time_s", bw["transpile_time_s"])],
                                          [cw.get("cpu_time_s", cw["transpile_time_s"])])
                if sem.strength == "structural" and sem.details.get("structural_ok") is False:
                    label = "functional_fail"
                elif sem.equivalent is False:
                    label = "semantic_fail"
                elif qual.is_regression:
                    label = "quality_regression"
                elif perf.suspected_regression:
                    label = "performance_regression"
                else:
                    label = "pass"
                rec.update(label=label, oracle_strength=sem.strength, oracle_equivalent=sem.equivalent,
                           delta_2q=qual.delta_2q, delta_depth=qual.delta_depth,
                           suspected_perf_regression=perf.suspected_regression)

            rec["fault_id_detected"] = event.fault_id if rec["label"] == expected else None
            records.append(rec)

    # write raw (write-once) + derived
    raw_dir = out_root / "raw" / event.event_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    blob = json.dumps({"schema": "historical_run/v1", "event_id": event.event_id,
                       "records": records}, indent=2, sort_keys=True)
    raw_path = raw_dir / "historical_run.json"
    if not raw_path.exists():
        raw_path.write_text(blob)
    counts: dict[str, int] = {}
    for r in records:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    return {"event_id": event.event_id, "n_records": len(records), "label_counts": counts,
            "raw_artifact": str(raw_path),
            "raw_sha256": hashlib.sha256(raw_path.read_text().encode()).hexdigest()}


def _run_targeted_worker(python_exe: str, unit, out_dir: Path, seed: int = 1234,
                         isolated_pass: str | None = None) -> dict:
    import os
    cmd = [str(python_exe), "-m", "cart.labels.historical_worker",
           "--targeted", unit.test_id, "--backend", unit.backend_id, "--opt", str(unit.opt_level),
           "--basis", ",".join(DEFAULT_BASIS), "--seed", str(seed), "--out", str(out_dir)]
    if isolated_pass:
        cmd += ["--isolated-pass", isolated_pass]
    env = dict(os.environ); env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=600)
    return json.loads((out_dir / "worker.json").read_text())


def run_targeted_event(event: Event, out_root: str | Path, *,
                       baseline_python: str | None = None, candidate_python: str | None = None) -> dict[str, Any]:
    """Run the targeted regression-trigger unit(s) for `event` via per-event venvs (or overrides).
    Semantic units use the standard semantic oracle; 'property' units use a determinism check
    (candidate transpiled twice, same seed, must agree)."""
    from cart.manifest.targeted import units_for_fault, build_targeted, TARGETED_UNITS  # noqa
    out_root = Path(out_root)
    bpy = baseline_python or _venv_python(f"{event.event_environment_id}-base")
    cpy = candidate_python or _venv_python(f"{event.event_environment_id}-cand")
    if not bpy or not cpy:
        raise FileNotFoundError(f"per-event venvs missing for {event.event_id}; build them first.")
    tunits = units_for_fault(event.fault_id)
    expected = LABEL_FOR_FAULT.get(event.fault_type)
    records: list[dict] = []
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for u in tunits:
            original = build_targeted(u.test_id)
            cmap = None if u.backend_id == "none" else coupling_map_for(u.backend_id, original.num_qubits)
            rec: dict[str, Any] = {"event_id": event.event_id, "test_id": u.test_id,
                                   "test_origin": u.test_origin, "oracle_type": u.oracle_type}
            if u.oracle_type == "property":   # determinism: candidate twice, must agree
                c1 = _run_targeted_worker(cpy, u, tmp / f"{u.test_id}-c1")
                c2 = _run_targeted_worker(cpy, u, tmp / f"{u.test_id}-c2")
                if "error" in (c1.get("status"), c2.get("status")):
                    rec["label"] = "functional_fail"
                else:
                    o1, o2 = _load_qpy(tmp / f"{u.test_id}-c1" / "circuit.qpy"), _load_qpy(tmp / f"{u.test_id}-c2" / "circuit.qpy")
                    # Compare full structure + final layout (op-counts/depth alone are invariant
                    # under a layout permutation, which would miss a layout-only non-determinism).
                    same = _circuit_fingerprint(o1) == _circuit_fingerprint(o2)
                    rec["label"] = "pass" if same else "quality_regression"
                    rec["deterministic"] = same
            elif u.oracle_type == "contract":   # contract/metadata: isolated-pass differential (H1)
                ipass = getattr(u, "isolated_pass", "") or None
                bw = _run_targeted_worker(bpy, u, tmp / f"{u.test_id}-base", isolated_pass=ipass)
                cw = _run_targeted_worker(cpy, u, tmp / f"{u.test_id}-cand", isolated_pass=ipass)
                b_ok, c_ok = bw.get("status") == "ok", cw.get("status") == "ok"
                rec["track"] = "secondary_retrospective"
                rec["isolated_pass"] = ipass
                if not b_ok and not c_ok:
                    rec["label"] = "inconclusive"
                    rec["detail"] = f"both builds errored in isolation ({bw.get('error_type')}/{cw.get('error_type')})"
                elif b_ok != c_ok:   # asymmetric error => the builds diverge on the trigger
                    rec["label"] = "contract_metadata_fail"
                    rec["divergence"] = "asymmetric_error"
                    rec["error_side"] = "candidate" if not c_ok else "baseline"
                else:
                    from cart.oracles.property_layout import compare_layout_props
                    bo = _load_qpy(tmp / f"{u.test_id}-base" / "circuit.qpy")
                    co = _load_qpy(tmp / f"{u.test_id}-cand" / "circuit.qpy")
                    circ_div = _circuit_fingerprint(bo) != _circuit_fingerprint(co)
                    ps = compare_layout_props(bw.get("property_set", {}), cw.get("property_set", {}))
                    rec["circuit_diverges"] = circ_div
                    rec["property_divergent_fields"] = ps.divergent_fields
                    rec["label"] = "contract_metadata_fail" if (circ_div or ps.equivalent is False) else "pass"
                rec["fault_id_detected"] = event.fault_id if rec["label"] == "contract_metadata_fail" else None
            else:   # semantic / structural
                bw = _run_targeted_worker(bpy, u, tmp / f"{u.test_id}-base")
                cw = _run_targeted_worker(cpy, u, tmp / f"{u.test_id}-cand")
                if cw.get("status") == "error":
                    rec["label"] = "functional_fail"
                else:
                    cand_out = _load_qpy(tmp / f"{u.test_id}-cand" / "circuit.qpy")
                    sem = check_semantic(original, cand_out, coupling_map=cmap, basis_gates=list(DEFAULT_BASIS))
                    rec["oracle_strength"] = sem.strength
                    rec["oracle_equivalent"] = sem.equivalent
                    if sem.strength == "structural" and sem.details.get("structural_ok") is False:
                        rec["label"] = "functional_fail"
                    elif sem.equivalent is False:
                        rec["label"] = "semantic_fail"
                    else:
                        rec["label"] = "pass"
            rec.setdefault("fault_id_detected", event.fault_id if rec["label"] == expected else None)
            records.append(rec)
    raw_dir = out_root / "raw" / event.event_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "targeted_run.json").write_text(json.dumps({"schema": "targeted_run/v1",
                                                           "event_id": event.event_id, "records": records}, indent=2, sort_keys=True))
    counts: dict[str, int] = {}
    for r in records:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    return {"event_id": event.event_id, "n_records": len(records), "label_counts": counts,
            "raw_artifact": str(raw_dir / "targeted_run.json")}


def run_historical(event_id: str, *, unit_limit: int = 4, out_root: str | Path | None = None,
                   candidate_basis: list[str] | None = None, use_targeted: bool = False) -> dict[str, Any]:
    from cart.events.table import load_events
    from cart.manifest.static_manifest import enumerate_test_units
    events = {e.event_id: e for e in load_events()}
    if event_id not in events:
        raise KeyError(f"unknown event {event_id}")
    out_root = Path(out_root) if out_root else _REPO_ROOT / "data"
    if use_targeted:
        return run_targeted_event(events[event_id], out_root)
    units = enumerate_test_units()[:unit_limit]
    return run_historical_event(events[event_id], units, out_root, candidate_basis=candidate_basis)
