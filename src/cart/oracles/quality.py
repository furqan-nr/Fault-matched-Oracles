"""Quality regression oracle (METHODOLOGY §2.3).

Pareto-style rule with PRE-DECLARED thresholds (configs/thresholds.yaml). Reports Δ 2Q count and
Δ depth separately. Utility-score rule 3 is dropped for the pilot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from qiskit import QuantumCircuit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_THRESHOLDS = _REPO_ROOT / "configs" / "thresholds.yaml"


def count_2q(circuit: QuantumCircuit) -> int:
    return sum(1 for i in circuit.data
               if i.operation.num_qubits == 2 and i.operation.name != "barrier")


@dataclass
class QualityThresholds:
    tau_2q: float = 0.10
    tau_depth: float = 0.10
    tau_depth_improve: float = 0.10
    tau_2q_improve: float = 0.10

    @classmethod
    def load(cls, path: str | Path | None = None) -> "QualityThresholds":
        p = Path(path) if path else _DEFAULT_THRESHOLDS
        d = yaml.safe_load(p.read_text())
        return cls(
            tau_2q=float(d.get("tau_2q", 0.10)),
            tau_depth=float(d.get("tau_depth", 0.10)),
            tau_depth_improve=float(d.get("tau_depth_improve", 0.10)),
            tau_2q_improve=float(d.get("tau_2q_improve", 0.10)),
        )


@dataclass
class QualityResult:
    is_regression: bool
    delta_2q: int
    delta_depth: int
    rel_2q: float
    rel_depth: float
    baseline_2q: int
    candidate_2q: int
    baseline_depth: int
    candidate_depth: int
    rule_fired: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _rel(base: int, cand: int) -> float:
    if base == 0:
        return 0.0 if cand == 0 else float("inf")
    return (cand - base) / base


def evaluate_quality(baseline_out: QuantumCircuit, candidate_out: QuantumCircuit,
                     thresholds: QualityThresholds | None = None) -> QualityResult:
    th = thresholds or QualityThresholds.load()
    b2, c2 = count_2q(baseline_out), count_2q(candidate_out)
    bd, cd = baseline_out.depth(), candidate_out.depth()
    rel2 = _rel(b2, c2)        # positive = worse
    reld = _rel(bd, cd)
    depth_improve = -reld      # positive = improved
    twoq_improve = -rel2

    rule = None
    # Rule 1: 2Q worsens materially AND depth does not improve materially
    if rel2 >= th.tau_2q and depth_improve < th.tau_depth_improve:
        rule = "rule1_2q_worse"
    # Rule 2: depth worsens materially AND 2Q does not improve materially
    elif reld >= th.tau_depth and twoq_improve < th.tau_2q_improve:
        rule = "rule2_depth_worse"

    return QualityResult(
        is_regression=rule is not None,
        delta_2q=c2 - b2, delta_depth=cd - bd,
        rel_2q=rel2, rel_depth=reld,
        baseline_2q=b2, candidate_2q=c2, baseline_depth=bd, candidate_depth=cd,
        rule_fired=rule,
        details={"tau_2q": th.tau_2q, "tau_depth": th.tau_depth,
                 "tau_depth_improve": th.tau_depth_improve, "tau_2q_improve": th.tau_2q_improve},
    )
