#!/usr/bin/env python3
"""Paper 1B expansion probe. Run it with the python of ONE Qiskit build (fix or parent).
Triggers are taken from each fix PR's own regression test (trigger-derivation rule, Sec. 4.7).

  <build-python> probe.py --pr 15943 --label fix --out results_expansion
Writes <out>/pr<PR>/<label>.json. compare.py then diffs fix vs bug.
"""
import argparse, json, math, sys, traceback
from pathlib import Path
import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
import qiskit
from qiskit.quantum_info import Operator


def _pfp(p):
    import hashlib
    if isinstance(p, (int, float)):
        return round(float(p), 9)
    try:
        a = np.asarray(p)
        if a.dtype != object and a.size > 1:
            return "arr:" + hashlib.sha1(np.round(a, 9).tobytes()).hexdigest()[:16]
    except Exception:
        pass
    return str(p)[:40]


def repo_oracles():
    """Import the paper's own oracle implementations (Fault-matched-Oracles/src). Path via env FMO_REPO."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.dirname(here)  # when this folder sits inside the repo (expansion/), repo root is its parent
    default = cand
    repo = os.environ.get("FMO_REPO", default)
    sys.path.insert(0, os.path.join(repo, "src"))
    from cart.oracles.global_phase import check_global_phase
    from cart.oracles.contract_differ import check_contracts
    from cart.oracles.semantic import check_semantic
    return check_global_phase, check_contracts, check_semantic


def struct_fp(qc):
    """Build-independent structural fingerprint (names, qubit idx, hashed params, phase)."""
    ops = [[i.operation.name, [qc.find_bit(q).index for q in i.qubits],
            [_pfp(p) for p in i.operation.params][:6]] for i in qc.data]
    return {"ops": ops, "global_phase": round(float(qc.global_phase) % (2 * math.pi), 9)}


def layout_idx(layout, qc):
    return {str(qc.find_bit(q).index): int(i) for q, i in layout.get_virtual_bits().items()}


# ---------------------------------------------------------------- PR 15943 (global phase)
def p15943():
    from qiskit.transpiler.passes import TemplateOptimization
    out = {}
    try:
        gp_oracle, _, sem_oracle = repo_oracles()
    except Exception as e:
        gp_oracle = sem_oracle = None
        out["_repo_oracle_error"] = f"{type(e).__name__}: {e}"[:200]

    def oracle_fields(c, r):
        d = {}
        if gp_oracle:
            g = gp_oracle(c, r); d["gp_oracle_equivalent"] = g.equivalent; d["gp_oracle_delta"] = g.global_phase_delta
            m = sem_oracle(c, r); d["semantic_oracle_equivalent"] = m.equivalent
        return d
    # test 1: circuit global phase survives a (cx cx) template match
    t = QuantumCircuit(2); t.cx(0, 1); t.cx(0, 1)
    for tag, reps, gp in (("single", 2, math.pi / 4), ("multi", 4, math.pi / 3)):
        c = QuantumCircuit(2, global_phase=gp)
        for _ in range(reps):
            c.cx(0, 1)
        r = TemplateOptimization([t])(c)
        out[f"t1_{tag}"] = {"in_gp": float(c.global_phase), "out_gp": float(r.global_phase),
                            "ops": dict(r.count_ops()),
                            "operator_exact_equal": bool(Operator(c) == Operator(r)),
                            "equiv_mod_phase": bool(Operator(c).equiv(Operator(r))),
                            "fp": struct_fp(r), **oracle_fields(c, r)}
    # tests 2/3: template with nonzero global phase
    tpl = QuantumCircuit(1)
    for _ in range(3):
        tpl.h(0); tpl.s(0)
    tpl.global_phase = -math.pi / 4
    c2 = QuantumCircuit(QuantumRegister(1, "qr"), global_phase=math.pi / 4)
    for _ in range(2):
        c2.h(0); c2.s(0)
    c3 = QuantumCircuit(QuantumRegister(1, "qr"))
    for _ in range(3):
        c3.h(0); c3.s(0)
    c3.global_phase = math.pi / 3
    for tag, c in (("t2", c2), ("t3", c3)):
        r = TemplateOptimization([tpl])(c)
        out[tag] = {"in_gp": float(c.global_phase), "out_gp": float(r.global_phase),
                    "ops": dict(r.count_ops()),
                    "operator_exact_equal": bool(Operator(c) == Operator(r)),
                    "equiv_mod_phase": bool(Operator(c).equiv(Operator(r))),
                    "fp": struct_fp(r), **oracle_fields(c, r)}
    return out


# ---------------------------------------------------------------- PR 13833 (contract: Sabre final_layout)
def p13833():
    from qiskit.transpiler import CouplingMap
    from qiskit.transpiler.passes import SabreLayout
    qc = QuantumCircuit(3); qc.cx(0, 1); qc.cx(1, 2); qc.cx(2, 0)
    disjoint = CouplingMap([(0, 1), (1, 2), (3, 4), (4, 5)])
    p = SabreLayout(disjoint, seed=2025_02_12, swap_trials=1, layout_trials=1)
    out = p(qc)
    lay = out.layout
    rec = {"len_initial": len(lay.initial_layout), "len_final": len(lay.final_layout)
           if lay.final_layout is not None else None}
    rec["initial_index_layout"] = lay.initial_index_layout(filter_ancillas=False)
    try:
        rec["final_index_layout"] = lay.final_index_layout(filter_ancillas=False)
        rec["final_is_permutation"] = sorted(rec["final_index_layout"]) == list(range(6))
    except Exception as e:  # buggy builds may raise here
        rec["final_index_layout"] = None
        rec["final_index_layout_error"] = f"{type(e).__name__}: {e}"[:200]
        rec["final_is_permutation"] = False
    rec["contract_ok"] = (rec["len_initial"] == rec["len_final"]) and rec["final_is_permutation"]
    try:
        _, cc, sem = repo_oracles()
        rec["repo_check_contracts"] = [[x.kind, x.detail[:120]] for x in cc(qc, out)]
        rec["repo_semantic_equivalent"] = sem(qc, out).equivalent
    except Exception as e:
        rec["repo_oracle_error"] = f"{type(e).__name__}: {e}"[:200]
    rec["fp"] = struct_fp(out)
    return rec


# ---------------------------------------------------------------- PR 13945 (contract: virtual permutation composition)
def p13945():
    from itertools import combinations, permutations
    from qiskit.circuit.library import SwapGate
    from qiskit.circuit.library import UnitaryGate
    from qiskit.transpiler import PassManager
    from qiskit.transpiler.passes import ElidePermutations, Split2QUnitaries
    try:
        from qiskit.transpiler.passes import StarPreRouting
    except Exception:
        StarPreRouting = None
    swapmat = Operator(SwapGate()).data

    def circ():
        qc = QuantumCircuit(5)
        qc.h(0); qc.cx(0, 1); qc.swap(0, 1)
        qc.append(UnitaryGate(swapmat), [1, 2])
        qc.cx(2, 3); qc.swap(3, 4)
        qc.append(UnitaryGate(swapmat), [0, 3])
        qc.cx(1, 4); qc.swap(2, 4)
        return qc

    mk = {"elide": lambda: ElidePermutations(),
          "split": lambda: Split2QUnitaries(split_swap=True)}
    if StarPreRouting is not None:
        mk["star"] = lambda: StarPreRouting()
    res = {}
    for k in range(1, len(mk) + 1):
        for subset in combinations(mk, k):
            for order in permutations(subset):
                key = "+".join(order)
                qc = circ()
                pm = PassManager([mk[n]() for n in order])
                rec = {}
                try:
                    cap = {}
                    o = pm.run(qc, callback=lambda **kw: cap.update(dict(kw["property_set"])))
                    vpl = cap.get("virtual_permutation_layout")
                    rec["vpl"] = layout_idx(vpl, o) if vpl is not None else None
                    rec["fp"] = struct_fp(o)
                    # reference-free contract check: output composed with the claimed virtual permutation
                    # must equal the original operator (convention validated on a correct build, 15/15 pipelines)
                    if vpl is not None:
                        from qiskit.circuit.library import PermutationGate
                        v = [0] * 5
                        for q, i in vpl.get_virtual_bits().items():
                            v[o.find_bit(q).index] = int(i)
                        inv = [v.index(i) for i in range(5)] if sorted(v) == list(range(5)) else None
                        if inv is None:
                            rec["permutation_consistent"] = False
                        else:
                            pq = QuantumCircuit(5); pq.append(PermutationGate(inv), range(5))
                            rec["permutation_consistent"] = bool(Operator(o).compose(Operator(pq)).equiv(Operator(qc)))
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {e}"[:200]
                res[key] = rec
    return res


# ---------------------------------------------------------------- PR 14763 (determinism)
def p14763(repeats=20):
    from qiskit.converters import circuit_to_dag
    from qiskit.transpiler.passes import CommutativeCancellation
    qc = QuantumCircuit(21)
    for _ in range(2):
        for a, b in zip(qc.qubits[:-1], qc.qubits[1:]):
            qc.cz(a, b)
    qc.cz(qc.qubits[-1], qc.qubits[0])
    first = CommutativeCancellation().run(circuit_to_dag(qc))
    has = hasattr(first, "structurally_equal")
    n_struct_diff = n_fp_diff = 0
    from qiskit.converters import dag_to_circuit
    fp0 = json.dumps(struct_fp(dag_to_circuit(first)), sort_keys=True)
    for _ in range(repeats):
        d = CommutativeCancellation().run(circuit_to_dag(qc))
        if has and not first.structurally_equal(d):
            n_struct_diff += 1
        if json.dumps(struct_fp(dag_to_circuit(d)), sort_keys=True) != fp0:
            n_fp_diff += 1
    return {"repeats": repeats, "has_structurally_equal": has,
            "n_structurally_unequal": n_struct_diff if has else None,
            "n_output_fingerprint_unequal": n_fp_diff,
            "fp": json.loads(fp0)}


PROBES = {"15943": p15943, "13833": p13833, "13945": p13945, "14763": p14763}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", required=True, choices=sorted(PROBES))
    ap.add_argument("--label", required=True, choices=["fix", "bug"])
    ap.add_argument("--out", default="results_expansion")
    a = ap.parse_args()
    rec = {"pr": a.pr, "label": a.label, "qiskit": qiskit.__version__}
    try:
        rec["result"] = PROBES[a.pr]()
        rec["status"] = "ok"
    except Exception as e:
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        rec["trace"] = traceback.format_exc()[-800:]
    d = Path(a.out) / f"pr{a.pr}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{a.label}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(a.pr, a.label, rec["status"], rec.get("error", ""))
