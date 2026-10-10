#!/usr/bin/env python3
"""Paper 1B harvest probe (protocol 1B-H v2). Run with the python of ONE Qiskit build (fix or parent).
Triggers are transcribed from each fix PR's own regression test (protocol Sec. 5, max 2 attempts per PR).

  <build-python> probe_harvest.py --pr 16920 --label fix --out results_harvest
Writes <out>/pr<PR>/<label>.json.  compare_harvest.py then diffs fix vs bug.
PR 15683 (typo/comment-only) has no probe: it is reported as 'out of scope (not a defect fix)'.
"""
import argparse, json, math, os, sys, traceback
from pathlib import Path
import numpy as np
import qiskit
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit import Qubit


def repo_oracles():
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.dirname(here)
    default = cand if os.path.isdir(os.path.join(cand, "src", "cart")) else r"D:\CUSIT PhD\Fault matched Oracles"
    repo = os.environ.get("FMO_REPO", default)
    sys.path.insert(0, os.path.join(repo, "src"))
    from cart.oracles.semantic import check_semantic
    from cart.oracles.global_phase import check_global_phase
    from cart.oracles.contract_differ import check_contracts
    return check_semantic, check_global_phase, check_contracts


def ops_of(qc):
    return [[i.operation.name, [qc.find_bit(q).index for q in i.qubits],
             [qc.find_bit(c).index for c in i.clbits]] for i in qc.data]


def basis_sim(qc):
    """Classical outcome of a circuit made only of x / swap / measure on |0..0> (deterministic)."""
    st = [0] * qc.num_qubits
    cl = [None] * qc.num_clbits
    for i in qc.data:
        n = i.operation.name
        q = [qc.find_bit(b).index for b in i.qubits]
        c = [qc.find_bit(b).index for b in i.clbits]
        if n == "x":
            st[q[0]] ^= 1
        elif n == "swap":
            st[q[0]], st[q[1]] = st[q[1]], st[q[0]]
        elif n == "measure":
            cl[c[0]] = st[q[0]]
        elif n == "barrier":
            pass
        else:
            return {"unsupported": n}
    return {"clbits": cl}


# ------------------------------------------------------------------ PR 16920 (OptimizeSwapBeforeMeasure, anonymous qubit)
def p16920():
    from qiskit.transpiler import PassManager
    from qiskit.transpiler.passes import OptimizeSwapBeforeMeasure
    out = {}
    try:
        sem, _, _ = repo_oracles()
    except Exception as e:
        sem = None
        out["_repo_oracle_error"] = f"{type(e).__name__}: {e}"[:200]
    anon = Qubit()
    qr = QuantumRegister(2, "q")
    cr = ClassicalRegister(1, "c")
    qc = QuantumCircuit([anon], qr, cr)
    qc.x(qr[1])
    qc.swap(qr[0], qr[1])
    qc.measure(qr[0], cr[0])
    exp = QuantumCircuit([anon], qr, cr)
    exp.x(qr[1])
    exp.measure(qr[1], cr[0])
    out["input_ops"] = ops_of(qc)
    out["input_outcome"] = basis_sim(qc)
    try:
        res = PassManager([OptimizeSwapBeforeMeasure()]).run(qc)
        out["ran"] = True
        out["output_ops"] = ops_of(res)
        out["output_outcome"] = basis_sim(res)
        out["equals_expected"] = (res == exp)
        out["expected_ops"] = ops_of(exp)
        out["outcome_preserved"] = out["output_outcome"] == out["input_outcome"]
        out["output_equals_input"] = (res == qc)
        if sem is not None:
            try:
                r = sem(qc, res)
                out["repo_semantic_equivalent"] = r.equivalent
                out["repo_semantic_strength"] = r.strength
            except Exception as e:
                out["repo_semantic_error"] = f"{type(e).__name__}: {e}"[:200]
    except Exception as e:
        out["ran"] = False
        out["error"] = f"{type(e).__name__}: {e}"[:300]
    return out


# ------------------------------------------------------------------ PR 16880 (LitinskiTransformation PPM sign)
def p16880():
    from qiskit.quantum_info import Pauli
    from qiskit.circuit.library import PauliProductMeasurement
    from qiskit.transpiler.passes import LitinskiTransformation
    out = {}
    for p in ["Z", "-Z", "X", "-X", "Y", "-Y"]:
        t = {}
        try:
            qc = QuantumCircuit(1, 1)
            qc.append(PauliProductMeasurement(Pauli(p)), [0], [0])
            qct = LitinskiTransformation(use_ppr=True)(qc)
            t["ran"] = True
            t["equal"] = (qc == qct)
            t["input_ops"] = [i.operation.name for i in qc.data]
            t["output_ops"] = [i.operation.name for i in qct.data]
            def sign(c):
                for i in c.data:
                    if i.operation.name == "pauli_product_measurement":
                        p = i.operation.pauli
                        p = p() if callable(p) else p
                        return str(p)
                return None
            t["input_pauli"] = sign(qc)
            t["output_pauli"] = sign(qct)
        except Exception as e:
            t["ran"] = False
            t["error"] = f"{type(e).__name__}: {e}"[:300]
        out[p] = t
    return out


# ------------------------------------------------------------------ PR 16336 (QISKIT_TRANSPILER_SEED)
def p16336():
    from unittest import mock
    from qiskit import transpile
    from qiskit.transpiler import CouplingMap
    from qiskit.transpiler.passes import SabreLayout
    out = {}
    try:
        sem, _, _ = repo_oracles()
    except Exception as e:
        sem = None
        out["_repo_oracle_error"] = f"{type(e).__name__}: {e}"[:200]

    # --- attempt 1: the PR's own test shape (record the seed SabreLayout.run sees) ---
    seen = []
    orig_run = SabreLayout.run

    def rec(self, dag):
        seen.append(self.seed)
        return orig_run(self, dag)

    qc3 = QuantumCircuit(3)
    qc3.cx(0, 1); qc3.cx(1, 2); qc3.cx(2, 0)
    with mock.patch.dict(os.environ, {"QISKIT_TRANSPILER_SEED": "1234"}):
        with mock.patch.object(SabreLayout, "run", rec):
            try:
                transpile(qc3, coupling_map=CouplingMap.from_line(3), optimization_level=1)
            except Exception as e:
                out["test_shape_error"] = f"{type(e).__name__}: {e}"[:200]
    out["seed_seen"] = [repr(s) for s in seen]
    out["seed_seen_type"] = [type(s).__name__ for s in seen]
    out["seed_is_1234"] = bool(seen) and all(s == 1234 and not isinstance(s, bool) for s in seen)

    # --- supplementary: is the env seed honoured end-to-end? (larger circuit where the seed matters) ---
    def circ():
        import random
        r = random.Random(7)
        qc = QuantumCircuit(16)
        for _ in range(120):
            a, b = r.sample(range(16), 2)
            qc.cx(a, b)
            qc.h(r.randrange(16))
        return qc
    cm = CouplingMap.from_grid(4, 4)

    def run(seed=None, env=None):
        e = dict(os.environ)
        e.pop("QISKIT_TRANSPILER_SEED", None)
        if env is not None:
            e["QISKIT_TRANSPILER_SEED"] = str(env)
        with mock.patch.dict(os.environ, e, clear=True):
            kw = dict(coupling_map=cm, optimization_level=1)
            if seed is not None:
                kw["seed_transpiler"] = seed
            res = transpile(circ(), **kw)
        return res

    def sig(c):
        return [[i.operation.name, [c.find_bit(q).index for q in i.qubits]] for i in c.data]

    env_a = run(env=1234)
    env_b = run(env=1234)
    exp_1234 = run(seed=1234)
    exp_1 = run(seed=1)
    exp_1234b = run(seed=1234)
    out["explicit1234_run_to_run_equal"] = sig(exp_1234) == sig(exp_1234b)
    out["env_vs_env_equal"] = sig(env_a) == sig(env_b)
    out["env_vs_explicit1234_equal"] = sig(env_a) == sig(exp_1234)
    out["env_vs_explicit1_equal"] = sig(env_a) == sig(exp_1)
    out["explicit1234_vs_explicit1_equal"] = sig(exp_1234) == sig(exp_1)
    out["depth_env/exp1234/exp1"] = [env_a.depth(), exp_1234.depth(), exp_1.depth()]
    if sem is not None:
        try:
            r = sem(circ(), env_a, coupling_map=cm)
            out["repo_semantic_equivalent_env_run"] = r.equivalent
            out["repo_semantic_strength"] = r.strength
        except Exception as e:
            out["repo_semantic_error"] = f"{type(e).__name__}: {e}"[:200]
    return out


PROBES = {"16920": p16920, "16880": p16880, "16336": p16336}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", required=True)
    ap.add_argument("--label", required=True, choices=["fix", "bug"])
    ap.add_argument("--out", default="results_harvest")
    a = ap.parse_args()
    d = Path(a.out) / f"pr{a.pr}"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"pr": a.pr, "label": a.label, "qiskit": qiskit.__version__}
    try:
        rec["result"] = PROBES[a.pr]()
    except Exception:
        rec["fatal"] = traceback.format_exc()[-1500:]
    (d / f"{a.label}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(json.dumps(rec, indent=1, default=str)[:3500])


if __name__ == "__main__":
    main()
