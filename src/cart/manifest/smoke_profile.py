"""Phase-0 smoke profile (METHODOLOGY §0.3).

Proves the instrumentation works on the pinned anchor by profiling a small subset of
the static manifest and recording, per unit, the executed pass stages vs the declared
stages. This is NOT the authoritative per-event baseline profile (that is Phase 2);
it only verifies the instrumentation capability.
"""
from __future__ import annotations

import json
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import qiskit

from cart.features.stage_map import StageMap
from cart.manifest.backends import coupling_map_for
from cart.manifest.circuits import build
from cart.manifest.instrumentation import instrumented_transpile
from cart.manifest.static_manifest import TestUnit, DEFAULT_BASIS


def run_smoke_profile(
    units: list[TestUnit],
    out_dir: str | Path,
    *,
    limit: int = 6,
    seed: int = 1234,
) -> Path:
    smap = StageMap.load()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for u in units[:limit]:
        opt = int(u.transpiler_config_id.split("+")[0].removeprefix("opt"))
        circ = build(u.circuit_family, u.n_qubits, seed=seed)
        cmap = coupling_map_for(u.backend_id, u.n_qubits)
        _, res = instrumented_transpile(
            circ,
            coupling_map=cmap,
            basis_gates=list(DEFAULT_BASIS),
            optimization_level=opt,
            seed_transpiler=seed,
            stage_map=smap,
        )
        declared = set(u.declared_pass_stages)
        executed = set(res.executed_pass_stages)
        rows.append(
            {
                "test_id": u.test_id,
                "declared_pass_stages": sorted(declared),
                "executed_pass_stages": res.executed_pass_stages,
                "executed_not_declared": sorted(executed - declared),
                "declared_not_executed": sorted(declared - executed),
                "transpilation_time_s": round(res.transpilation_time_s, 4),
                "peak_memory_mb": round(res.peak_memory_mb, 2),
                "n_executed_passes": len(res.executed_passes),
                "routing_observations": res.routing_observations,
                "out_depth": res.out_depth,
                "out_size": res.out_size,
            }
        )

    payload = {
        "schema": "smoke_profile/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "qiskit_version": qiskit.__version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "stage_map_anchor": smap.qiskit_anchor,
        "n_profiled": len(rows),
        "rows": rows,
    }
    out_path = out_dir / "smoke_profile.json"
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path
