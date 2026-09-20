"""Mutation engine (METHODOLOGY §1.5).

Mutations inject a single controlled fault into the *transpiler* and are implemented as
deterministic transforms of the preset pass manager (or a post-transpile transform), so a
mutation's baseline and candidate share one from-source Qiskit build (baseline_sha ==
candidate_sha; the fault is the operator, recorded in change_metadata).

All operators here are **semantics-preserving** → they are QUALITY (or performance) faults, not
semantic ones. Genuine semantic/functional faults come from historical events (see
HISTORICAL_CANDIDATES.md). Barrier-removal is explicitly NOT a mutation (§1.5): it does not
change semantics.

Operators are robust across the 2.1–2.4 band: they act on top-level optimization tasks, on a
config knob (routing_method), or post-transpile on the circuit — not on passes nested inside
flow controllers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap, PassManager, generate_preset_pass_manager

from cart.events.schema import FaultType

Transpiler = Callable[[QuantumCircuit], QuantumCircuit]
BaseConfig = dict[str, Any]   # generate_preset_pass_manager kwargs


def _build_preset(cfg: BaseConfig) -> "PassManager":
    return generate_preset_pass_manager(**cfg)


def baseline_transpiler(cfg: BaseConfig) -> Transpiler:
    """The unmutated reference transpiler for an event's baseline."""
    return _build_preset(cfg).run


def _remove_top_level_task(pm, stage: str, task_class_name: str) -> int:
    """Remove top-level tasks whose class name matches, from a StagedPassManager stage.
    Returns the number removed. Raises if the private flatten API is unavailable."""
    sub = getattr(pm, stage)
    if not hasattr(sub, "_flatten_tasks"):
        raise RuntimeError("PassManager._flatten_tasks unavailable; pin within the 2.1-2.4 band.")
    flat = list(sub._flatten_tasks(sub._tasks))
    kept = [t for t in flat if type(t).__name__ != task_class_name]
    removed = len(flat) - len(kept)
    setattr(pm, stage, PassManager(kept))
    return removed


# ---- operator builders -------------------------------------------------------------------

def _disable_optimization_loop(cfg: BaseConfig) -> Transpiler:
    """Disable the iterative peephole/cancellation optimization loop (DoWhileController)."""
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "optimization", "DoWhileController")
    return pm.run


def _drop_vf2_post_layout(cfg: BaseConfig) -> Transpiler:
    """Omit the VF2PostLayout layout-improvement pass (present at optimization_level=3)."""
    pm = _build_preset(cfg)
    _remove_top_level_task(pm, "optimization", "VF2PostLayout")
    return pm.run


def _downgrade_routing(cfg: BaseConfig) -> Transpiler:
    """Corrupt the routing heuristic by forcing the weaker 'basic' routing method."""
    mut = dict(cfg)
    mut["routing_method"] = "basic"
    return _build_preset(mut).run


def _insert_redundant_cx_pair(cfg: BaseConfig) -> Transpiler:
    """Post-transpile: append one redundant CX-CX pair (identity) on the first 2q edge used,
    simulating the optimizer failing to cancel a redundant pair. Semantics-preserving."""
    run = _build_preset(cfg).run

    def transpile_fn(circuit: QuantumCircuit) -> QuantumCircuit:
        out = run(circuit)
        for instr in out.data:
            if instr.operation.num_qubits == 2 and instr.operation.name == "cx":
                q0, q1 = instr.qubits
                out.cx(q0, q1)
                out.cx(q0, q1)
                break
        return out

    return transpile_fn


def _incomplete_basis_translation(cfg: BaseConfig) -> Transpiler:
    """Functional fault: an incomplete target basis (drop the single-qubit basis, leaving only
    ['cx']) so the translation stage cannot express the circuit's 1q gates and transpilation
    fails with a TranspilerError. Triggers through NORMAL transpilation (no artificial raise);
    the engine records the natural exception as a functional failure. Fires on any unit containing
    single-qubit gates (all pilot families). Realistic: a transpiler/target change that drops a
    required basis gate so translation can no longer complete."""
    mut = dict(cfg)
    mut["basis_gates"] = ["cx"]
    return _build_preset(mut).run


def _drop_optimization_stage(cfg: BaseConfig) -> Transpiler:
    """Replace the entire optimization stage with a no-op — a regression that silently disables
    circuit optimization. Semantics-preserving (more gates/depth) → quality fault."""
    pm = _build_preset(cfg)
    pm.optimization = PassManager([])
    return pm.run


def _force_opt_level_1(cfg: BaseConfig) -> Transpiler:
    """Silently downgrade the optimization level to 1 — a regression lowering the default effort.
    Detectable only where the unit's level exceeds 1 (e.g. opt-3 units)."""
    mut = dict(cfg)
    mut["optimization_level"] = 1
    return _build_preset(mut).run


def _force_opt_level_0(cfg: BaseConfig) -> Transpiler:
    """Silently downgrade the optimization level to 0 (no optimization) — a stronger graded
    variant of the same regression class. Semantics-preserving → quality fault."""
    mut = dict(cfg)
    mut["optimization_level"] = 0
    return _build_preset(mut).run


def _downgrade_layout_trivial(cfg: BaseConfig) -> Transpiler:
    """Force the trivial layout method, replacing the smart (Sabre/VF2) layout — a regression that
    typically increases routing SWAPs and two-qubit count on routing-sensitive circuits."""
    mut = dict(cfg)
    mut["layout_method"] = "trivial"
    return _build_preset(mut).run


def _insert_redundant_x_pair(cfg: BaseConfig) -> Transpiler:
    """Post-transpile: append an X·X identity on the first qubit (+2 single-qubit gates). The pair
    is basis-compliant (X ∈ basis) and semantics-preserving — redundancy the optimizer failed to
    cancel → quality fault."""
    run = _build_preset(cfg).run

    def transpile_fn(circuit: QuantumCircuit) -> QuantumCircuit:
        out = run(circuit)
        if out.num_qubits > 0:
            q = out.qubits[0]
            out.x(q)
            out.x(q)
        return out

    return transpile_fn


@dataclass(frozen=True)
class MutationOperator:
    family: str
    fault_type: FaultType
    target_stage: str            # canonical stage for change_stage_match (§4.1)
    description: str
    builder: Callable[[BaseConfig], Transpiler]

    def transpiler(self, cfg: BaseConfig) -> Transpiler:
        return self.builder(cfg)

    def change_metadata(self) -> dict[str, Any]:
        return {
            "kind": "mutation",
            "mutation_family": self.family,
            "modified_pass_stages": [self.target_stage],
        }


MUTATION_OPERATORS: dict[str, MutationOperator] = {
    op.family: op for op in [
        MutationOperator("disable_optimization_loop", FaultType.quality, "optimization",
                         "Remove the iterative peephole/cancellation optimization loop.",
                         _disable_optimization_loop),
        MutationOperator("drop_vf2_post_layout", FaultType.quality, "optimization",
                         "Omit VF2PostLayout layout-improvement (optimization_level=3).",
                         _drop_vf2_post_layout),
        MutationOperator("downgrade_routing", FaultType.quality, "routing",
                         "Force the weaker 'basic' routing method (corrupt routing heuristic).",
                         _downgrade_routing),
        MutationOperator("insert_redundant_cx_pair", FaultType.quality, "optimization",
                         "Append a redundant CX-CX identity pair (uncancelled redundancy).",
                         _insert_redundant_cx_pair),
        MutationOperator("drop_optimization_stage", FaultType.quality, "optimization",
                         "Disable the entire optimization stage (no circuit optimization).",
                         _drop_optimization_stage),
        MutationOperator("force_opt_level_1", FaultType.quality, "optimization",
                         "Silently downgrade the optimization level to 1 (lower default effort).",
                         _force_opt_level_1),
        MutationOperator("force_opt_level_0", FaultType.quality, "optimization",
                         "Silently downgrade the optimization level to 0 (no optimization).",
                         _force_opt_level_0),
        MutationOperator("downgrade_layout_trivial", FaultType.quality, "layout",
                         "Force the trivial layout method (replace the smart layout).",
                         _downgrade_layout_trivial),
        MutationOperator("insert_redundant_x_pair", FaultType.quality, "optimization",
                         "Append a redundant X-X identity pair on one qubit (+2 1q gates).",
                         _insert_redundant_x_pair),
        MutationOperator("incomplete_basis_translation", FaultType.functional, "translation",
                         "Incomplete target basis (['cx'] only) -> translation cannot express 1q "
                         "gates -> natural TranspilerError -> functional failure. Documented "
                         "FALLBACK for the functional event if historical crash #16285 does not "
                         "reproduce; also the runner's functional-path test fixture.",
                         _incomplete_basis_translation),
    ]
}


def get_operator(family: str) -> MutationOperator:
    if family not in MUTATION_OPERATORS:
        raise KeyError(f"unknown mutation family: {family!r}. Known: {sorted(MUTATION_OPERATORS)}")
    return MUTATION_OPERATORS[family]
