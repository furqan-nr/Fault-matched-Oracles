#!/usr/bin/env python3
"""Clean-compilation specificity check of the global-phase tracker (added after review; Paper 1B, Sci Rep version).

Question: does the tracker's contract (compilation preserves the operator INCLUDING global phase; reference =
Operator(P), which includes P.global_phase) hold on correct Qiskit compilations, including circuits with a legitimate
nonzero input global phase?  Reports absence of observed violations within the tested configurations only.

Run:  python scripts/phase_spec_check.py [--out results/phase_spec_check.json]
Needs the Qiskit build under test (reported in the output). Takes about a minute.
"""
import argparse, json, math, os, random, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("FMO_REPO", os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
import qiskit
from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap
from cart.oracles.global_phase import check_global_phase


def rand_circuit(n, depth, rng, phase):
    qc = QuantumCircuit(n, global_phase=phase)
    one = ["h", "x", "y", "z", "s", "sdg", "t", "tdg", "sx"]
    for _ in range(depth):
        r = rng.random()
        if r < 0.35 and n > 1:
            a, b = rng.sample(range(n), 2); qc.cx(a, b)
        elif r < 0.45 and n > 1:
            a, b = rng.sample(range(n), 2); qc.cz(a, b)
        elif r < 0.52 and n > 1:
            a, b = rng.sample(range(n), 2); qc.swap(a, b)
        elif r < 0.60 and n > 1:
            a, b = rng.sample(range(n), 2); qc.cp(rng.uniform(-3, 3), a, b)
        elif r < 0.70:
            getattr(qc, rng.choice(["rx", "ry", "rz", "p"]))(rng.uniform(-3.14, 3.14), rng.randrange(n))
        elif r < 0.75:
            qc.u(rng.uniform(0, 3), rng.uniform(0, 3), rng.uniform(0, 3), rng.randrange(n))
        else:
            getattr(qc, rng.choice(one))(rng.randrange(n))
    return qc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "results", "phase_spec_check.json"))
    a = ap.parse_args()
    res = {"qiskit": qiskit.__version__, "exact": {"total": 0, "preserved": 0, "fault": 0, "not_assessable": 0,
           "max_abs_delta": 0.0, "nonzero_input_phase_total": 0, "by_level": {}, "exceptions": []},
           "sampled": {"total": 0, "preserved": 0, "fault": 0, "not_assessable": 0, "max_abs_delta": 0.0},
           "negative_control": {"total": 0, "detected": 0}}
    phases = [0.0, 0.3, -2.1, math.pi / 7, 3.0]
    bases = {"rz_sx_cx": ["rz", "sx", "x", "cx"], "u_cz": ["u", "cz"], "rx_ry_rz_cx": ["rx", "ry", "rz", "cx"], "none": None}
    topos = {"all": None, "line": "line", "ring": "ring"}
    rng = random.Random(2026)
    t0 = time.time()
    E = res["exact"]
    for n in (3, 4, 5, 6):
        for _trial in range(3):
            for ph in phases:
                qc = rand_circuit(n, 14 + 3 * n, rng, ph)
                for bname, b in bases.items():
                    for tname, t in topos.items():
                        if bname == "none" and tname != "all":
                            continue
                        cm = CouplingMap.from_line(n) if t == "line" else CouplingMap.from_ring(n) if t == "ring" else None
                        for lvl in (0, 1, 2, 3):
                            try:
                                tq = transpile(qc, basis_gates=b, coupling_map=cm, optimization_level=lvl, seed_transpiler=7)
                            except Exception as e:
                                E["exceptions"].append(["transpile_error", n, ph, bname, tname, lvl, str(e)[:80]]); continue
                            r = check_global_phase(qc, tq)
                            d = E["by_level"].setdefault(f"level{lvl}", {"total": 0, "preserved": 0, "fault": 0, "not_assessable": 0})
                            E["total"] += 1; d["total"] += 1
                            if ph != 0.0: E["nonzero_input_phase_total"] += 1
                            if r.equivalent is True:
                                E["preserved"] += 1; d["preserved"] += 1
                                E["max_abs_delta"] = max(E["max_abs_delta"], abs(r.global_phase_delta))
                            elif r.equivalent is False:
                                E["fault"] += 1; d["fault"] += 1; E["exceptions"].append(["FAULT", n, ph, bname, tname, lvl, r.global_phase_delta])
                            else:
                                E["not_assessable"] += 1; d["not_assessable"] += 1; E["exceptions"].append(["NA", n, ph, bname, tname, lvl, str(r.details)])
    # sampled tier (13, 14 qubits)
    rng2 = random.Random(5)
    S = res["sampled"]
    for n in (13, 14):
        for ph in (0.0, 0.37, -2.1):
            qc = rand_circuit(n, 40, rng2, ph)
            for lvl in (1, 3):
                tq = transpile(qc, basis_gates=["rz", "sx", "x", "cx"], coupling_map=CouplingMap.from_line(n),
                               optimization_level=lvl, seed_transpiler=3)
                r = check_global_phase(qc, tq)
                S["total"] += 1
                if r.equivalent is True:
                    S["preserved"] += 1; S["max_abs_delta"] = max(S["max_abs_delta"], abs(r.global_phase_delta))
                elif r.equivalent is False: S["fault"] += 1
                else: S["not_assessable"] += 1
    # negative control
    N = res["negative_control"]
    for n in (3, 4, 5):
        for ph in (0.0, 0.3, -2.1):
            qc = rand_circuit(n, 20, rng2, ph)
            tq = transpile(qc, basis_gates=["u", "cz"], coupling_map=CouplingMap.from_line(n), optimization_level=2, seed_transpiler=1)
            for delta in (0.3, math.pi / 7, 1e-3, -0.6):
                tq2 = tq.copy(); tq2.global_phase += delta
                r = check_global_phase(qc, tq2)
                N["total"] += 1
                wrapped = (delta + math.pi) % (2 * math.pi) - math.pi
                if r.equivalent is False and abs(r.global_phase_delta - wrapped) < 1e-9:
                    N["detected"] += 1
    res["elapsed_s"] = round(time.time() - t0, 1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("qiskit", "sampled", "negative_control")}, indent=1))
    print("exact:", {k: E[k] for k in ("total", "preserved", "fault", "not_assessable", "max_abs_delta", "nonzero_input_phase_total")})


if __name__ == "__main__":
    main()
