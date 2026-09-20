"""Instrumented transpilation harness (METHODOLOGY §0.3).

Captures, for one transpilation run:
  - executed_pass_stages : canonical stages actually executed (via pass-manager
    callback, mapped through the stage_map) -- NOT inferred from filenames;
  - executed_passes      : raw pass class names, in execution order;
  - transpilation_time_s : measured wall-clock seconds;
  - peak_memory_mb       : peak Python allocation during the run (tracemalloc);
  - routing_observations : SWAPs inserted, depth, size, op counts, final layout flag.

This is the Phase-0 capability. The authoritative per-event baseline profile
(keyed by event_id, baseline_sha, test_id, event_environment_id) is produced in
Phase 2 by calling this harness against each event's baseline revision.
"""
from __future__ import annotations

import statistics
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Callable

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap, generate_preset_pass_manager

from cart.features.stage_map import StageMap


@dataclass
class InstrumentationResult:
    cpu_time_s: float                        # CPU process time — STABLE cost-calibration metric
    transpilation_time_s: float              # wall-clock — secondary reference only
    peak_memory_mb: float
    executed_passes: list[str]
    executed_pass_modules: list[str]
    executed_pass_stages: list[str]          # ordered, de-duplicated by first occurrence
    routing_observations: dict[str, Any]
    out_depth: int
    out_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_time_s": self.cpu_time_s,
            "transpilation_time_s": self.transpilation_time_s,
            "peak_memory_mb": self.peak_memory_mb,
            "executed_passes": self.executed_passes,
            "executed_pass_modules": self.executed_pass_modules,
            "executed_pass_stages": self.executed_pass_stages,
            "routing_observations": self.routing_observations,
            "out_depth": self.out_depth,
            "out_size": self.out_size,
        }


def instrumented_transpile(
    circuit: QuantumCircuit,
    *,
    coupling_map: CouplingMap | None = None,
    basis_gates: list[str] | None = None,
    optimization_level: int = 2,
    seed_transpiler: int = 1234,
    stage_map: StageMap | None = None,
) -> tuple[QuantumCircuit, InstrumentationResult]:
    """Transpile ``circuit`` while capturing instrumentation evidence."""
    smap = stage_map or StageMap.load()
    basis_gates = basis_gates or ["cx", "rz", "sx", "x"]

    executed_passes: list[str] = []
    executed_modules: list[str] = []

    def _callback(**kw: Any) -> None:  # 2.x keyword callback
        p = kw.get("pass_")
        executed_passes.append(type(p).__name__)
        executed_modules.append(type(p).__module__)

    pm = generate_preset_pass_manager(
        optimization_level=optimization_level,
        coupling_map=coupling_map,
        basis_gates=basis_gates,
        seed_transpiler=seed_transpiler,
    )

    tracemalloc.start()
    c0 = time.process_time()        # CPU process time — stable cost-calibration metric
    t0 = time.perf_counter()        # wall-clock — secondary reference
    out = pm.run(circuit, callback=_callback)
    elapsed = time.perf_counter() - t0
    cpu = time.process_time() - c0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Ordered, de-duplicated stage list (first occurrence order).
    stages_ordered: list[str] = []
    for mod in executed_modules:
        st = smap.stage_for(mod)
        if st not in stages_ordered:
            stages_ordered.append(st)

    in_2q = _count_2q(circuit)
    out_2q = _count_2q(out)
    routing = {
        "swaps_inserted_estimate": max(0, out_2q - in_2q),
        "in_2q_gates": in_2q,
        "out_2q_gates": out_2q,
        "final_layout_present": out.layout is not None,
        "out_op_counts": {k: int(v) for k, v in out.count_ops().items()},
    }

    result = InstrumentationResult(
        cpu_time_s=cpu,
        transpilation_time_s=elapsed,
        peak_memory_mb=peak / (1024 * 1024),
        executed_passes=executed_passes,
        executed_pass_modules=executed_modules,
        executed_pass_stages=stages_ordered,
        routing_observations=routing,
        out_depth=out.depth(),
        out_size=out.size(),
    )
    return out, result


def measure_cost(
    fn: Callable[[QuantumCircuit], QuantumCircuit],
    circuit: QuantumCircuit,
    *,
    repeats: int = 5,
    warmup: int = 1,
) -> tuple[Any, dict[str, Any]]:
    """Absolute cost calibration (B1 §5 / Appendix F). Measures CPU ``process_time`` of
    ``fn(circuit)``:

      * OUTSIDE ``tracemalloc`` — instrumentation overhead is real and would inflate the *absolute*
        budget thresholds (``pr: 120s`` / ``nightly: 3600s`` are absolute, not relative);
      * discarding ``warmup`` initial run(s) — the first run is biased high (imports, cold caches,
        first-touch page faults), and unevenly across units, so it is systematically inflating, not
        merely noisy;
      * over ``repeats`` (>= 5 recommended) timed runs, reporting the **median** plus dispersion
        (min / median / max / IQR) as stability evidence and to catch budget knife-edges before freezing.
    """
    for _ in range(max(0, warmup)):
        fn(circuit)                              # warmup run(s) — discarded
    samples: list[float] = []
    out: Any = None
    for _ in range(max(1, repeats)):
        c0 = time.process_time()
        out = fn(circuit)
        samples.append(time.process_time() - c0)
    s = sorted(samples)
    median = statistics.median(s)
    if len(s) >= 4:
        q1, _med, q3 = statistics.quantiles(s, n=4)
    else:
        q1, q3 = s[0], s[-1]
    stats = {
        "cpu_time_s": median,                    # the calibration cost = median of the clean runs
        "cost_median_s": median,
        "cost_min_s": s[0],
        "cost_max_s": s[-1],
        "cost_iqr_s": q3 - q1,
        "cost_repeats": len(samples),
        "cost_warmup": max(0, warmup),
        "cost_runs_s": samples,
    }
    return out, stats


def _count_2q(circuit: QuantumCircuit) -> int:
    """Count two-qubit gate operations (excludes barriers/measure/etc.)."""
    n = 0
    for instr in circuit.data:
        op = instr.operation
        if op.num_qubits == 2 and op.name not in ("barrier",):
            n += 1
    return n
