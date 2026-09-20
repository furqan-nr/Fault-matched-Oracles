#!/usr/bin/env python3
"""verify_15024_contract.py — #15024 register-preservation contract/metadata verifier.

PR #15024 ("Preserve registers in output TranspileLayout") fixes a contract/metadata regression: the
buggy build drops the input circuit's registers from the output ``TranspileLayout``, while the compiled
circuit stays functionally correct — so a black-box output-equivalence oracle is BLIND.

The trigger and observable are taken **directly from the fix's own regression test**
(``test/python/transpiler/test_preset_passmanagers.py::test_layout_registers_preserved``), not invented
from the PR title — the lesson of the earlier inert generic triggers (#14939, and the first pass at this
one). The upstream test:

    a = QuantumRegister(2, "a"); b = AncillaRegister(1, "b")   # ancilla, listed FIRST
    qc = QuantumCircuit(b, a); qc.x(0)
    qc_t = transpile(qc, initial_layout=[0, 1, 2], optimization_level=level)   # level in 0..3
    assert qc_t.layout.initial_layout.get_registers() == {a, b}

The discriminating observable is ``initial_layout.get_registers()`` — the register SET stored on the
Layout, which the buggy build drops (Paper 1 recorded exactly this in
``label_source_validation.csv``: ``regression_test_asserts_on = layout.initial_layout.get_registers``).
The per-virtual-bit register membership used before is derived from the circuit's own qubits and is
identical on both builds, which is why the first gate returned a false negative.

Same ``--baseline-python`` / ``--candidate-python`` / ``--out`` interface. Acceptance, exit codes, and JSON
shape are unchanged: register signature DIFFERS between builds WHILE the output oracle stays blind →
exit 0; blind but identical → exit 2 (stop); a build errors → exit 3.

GATE (FORWARD_PAIR_RUNBOOK.md Round 2): run at the FIX BOUNDARY first (``sv-15024-fix`` = baseline/good,
``sv-15024-bug`` = candidate/buggy, both 2.3.0.dev0, zero builds). Only on a positive are the forward-pair
venvs built and run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cart.labels.historical_runner import _venv_python  # noqa: E402

# Self-contained probe run INSIDE each from-source venv (PYTHONPATH=src set by the caller). Mirrors the
# upstream regression test: AncillaRegister first, explicit initial_layout, swept optimization levels.
_PROBE = r'''
import argparse, json, traceback
from pathlib import Path


def build_trigger():
    from qiskit import QuantumCircuit, QuantumRegister, AncillaRegister
    a = QuantumRegister(2, "a")
    b = AncillaRegister(1, "b")          # ancilla register, listed FIRST (matches the fix's test)
    qc = QuantumCircuit(b, a)
    qc.x(0)
    return qc, a, b


def registers_signature(tqc):
    """The #15024 observable: initial_layout.get_registers() as a sorted, comparable signature."""
    layout = getattr(tqc, "layout", None)
    il = getattr(layout, "initial_layout", None) if layout is not None else None
    if il is None or not hasattr(il, "get_registers"):
        return None
    try:
        regs = il.get_registers()
    except Exception as exc:
        return "__error__:" + type(exc).__name__
    return sorted([[getattr(r, "name", "?"), int(len(r)), type(r).__name__] for r in regs])


def virtual_bit_registers(original, tqc):   # secondary/reference field (the old, inert primary signal)
    layout = getattr(tqc, "layout", None)
    il = getattr(layout, "initial_layout", None) if layout is not None else None
    if il is None or not hasattr(il, "get_virtual_bits"):
        return None
    out = []
    for q in il.get_virtual_bits().keys():
        try:
            loc = original.find_bit(q)
            if getattr(loc, "registers", None):
                reg, idx = loc.registers[0]
                out.append([getattr(reg, "name", "?"), int(idx)]); continue
        except Exception:
            pass
        out.append(["<loose>", -1])
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opt-levels", default="0,1,2,3")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"status": "ok"}
    try:
        import qiskit
        from qiskit import transpile
        out["qiskit_version"] = qiskit.__version__
        original, reg_a, reg_b = build_trigger()
        levels = {}
        for opt in [int(x) for x in a.opt_levels.split(",") if x.strip() != ""]:
            tqc = transpile(original, initial_layout=[0, 1, 2],
                            optimization_level=opt, seed_transpiler=a.seed)
            rec = {"get_registers": registers_signature(tqc),
                   "virtual_bit_registers": virtual_bit_registers(original, tqc)}
            try:
                from cart.oracles.semantic import check_semantic
                sem = check_semantic(original, tqc, coupling_map=None, basis_gates=["cx", "rz", "sx", "x"])
                rec["output_equivalent"] = sem.equivalent      # True => output oracle BLIND
            except Exception as exc:
                rec["output_equivalent"] = None
                rec["semantic_error"] = (type(exc).__name__ + ": " + str(exc))[:200]
            levels[str(opt)] = rec
        out["levels"] = levels
    except Exception as exc:
        out["status"] = "error"
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)[:400]
        out["traceback"] = traceback.format_exc()[-1200:]
    Path(a.out).write_text(json.dumps(out, indent=2, default=str))


main()
'''


def _run_probe(python_exe: str, *, opt_levels: str, seed: int, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    probe_py = work / "probe_15024.py"
    probe_py.write_text(_PROBE)
    result = work / "result.json"
    cmd = [str(python_exe), str(probe_py), "--opt-levels", opt_levels, "--seed", str(seed), "--out", str(result)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=1200)
    return json.loads(result.read_text())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="#15024 register-preservation contract verifier.")
    p.add_argument("--event", default="fwd-tlayout-registers-15024")
    p.add_argument("--pr", default="15024")
    p.add_argument("--baseline-python", default=None, help="GOOD/fixed build (sv-15024-fix or e364cd96)")
    p.add_argument("--candidate-python", default=None, help="BUGGY build (sv-15024-bug or ccc2c77b)")
    p.add_argument("--opt-levels", default="0,1,2,3", help="sweep these levels; fires at any = detection")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out", default=str(_REPO_ROOT / "results" / "fwd-tlayout-15024"))
    args = p.parse_args(argv)

    bpy = args.baseline_python or _venv_python("sv-15024-fix") or _venv_python("fwd-tlayout-15024-base")
    cpy = args.candidate_python or _venv_python("sv-15024-bug") or _venv_python("fwd-tlayout-15024-cand")
    if not bpy or not cpy:
        raise SystemExit("baseline/candidate venvs not found; pass --baseline-python / --candidate-python "
                         "(fix boundary: sv-15024-fix / sv-15024-bug; see FORWARD_PAIR_RUNBOOK.md Round 2).")

    print("# #15024 register-preservation contract verification (upstream regression-test trigger)")
    print(f"# trigger: AncillaRegister b[1] first + a[2], x(0), initial_layout=[0,1,2], opt sweep {args.opt_levels}")
    print("# baseline(good/fixed) vs candidate(buggy)\n")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bw = _run_probe(bpy, opt_levels=args.opt_levels, seed=args.seed, work=tmp / "base")
        cw = _run_probe(cpy, opt_levels=args.opt_levels, seed=args.seed, work=tmp / "cand")

        rec: dict = {"schema": "contract_register_15024/v1", "event_id": args.event, "pr": args.pr,
                     "trigger": {"registers": [["a", 2, "QuantumRegister"], ["b", 1, "AncillaRegister"]],
                                 "circuit": "QuantumCircuit(b, a); x(0)", "initial_layout": [0, 1, 2],
                                 "opt_levels": args.opt_levels, "observable": "initial_layout.get_registers()"},
                     "qiskit_version": {"baseline": bw.get("qiskit_version"), "candidate": cw.get("qiskit_version")},
                     "worker_status": {"baseline": bw.get("status"), "candidate": cw.get("status")},
                     "baseline_signature": bw.get("levels"), "candidate_signature": cw.get("levels")}

        if bw.get("status") != "ok" or cw.get("status") != "ok":
            rec["verdict"] = "inconclusive"
            rec["reason"] = "a build failed to transpile the trigger (not a refutation)"
            rec["errors"] = {"baseline": bw.get("error"), "candidate": cw.get("error")}
            _emit(out_root, rec)
            print("INCONCLUSIVE — a build errored on the trigger (not a refutation):")
            print(f"  baseline : {bw.get('error_type')}: {bw.get('error')}")
            print(f"  candidate: {cw.get('error_type')}: {cw.get('error')}")
            return 3

        base_lv, cand_lv = bw["levels"], cw["levels"]
        common = sorted(set(base_lv) & set(cand_lv), key=int)
        # fires at ANY optimization level: the get_registers() signature diverges between builds
        divergent_levels = [f"opt{lv}" for lv in common
                            if base_lv[lv].get("get_registers") != cand_lv[lv].get("get_registers")]
        register_diverges = bool(divergent_levels)
        check_levels = [lv for lv in common if f"opt{lv}" in divergent_levels] or common
        output_blind = all(cand_lv[lv].get("output_equivalent") is True for lv in check_levels)
        fault_detected = register_diverges and output_blind

        rec["output_equivalent"] = {"baseline": {lv: base_lv[lv].get("output_equivalent") for lv in common},
                                    "candidate": {lv: cand_lv[lv].get("output_equivalent") for lv in common}}
        rec["divergent_register_fields"] = divergent_levels
        rec["register_diverges"] = register_diverges
        rec["output_oracle_blind"] = output_blind
        rec["fault_detected"] = fault_detected
        if fault_detected:
            rec["verdict"] = "positive"
            rec["note"] = ("initial_layout.get_registers() diverges between builds while the output oracle "
                           "stays blind — the #15024 contract fault is reproduced (promotable at the forward "
                           "boundary)")
        elif not output_blind:
            rec["verdict"] = "inconclusive"
            rec["note"] = ("outputs not equivalent (output oracle NOT blind) — semantic difference, not a pure "
                           "contract/metadata fault; check the trigger")
        else:
            rec["verdict"] = "negative_here"
            rec["note"] = ("output blind but get_registers() identical across builds at every level — the "
                           "detector does NOT fire. Per the runbook gate: STOP; do not build the forward pair. "
                           "If this holds with the upstream trigger faithfully reproduced, record #15024 as "
                           "not forward-verifiable with the current oracle family (per-event claim-scope).")
        _emit(out_root, rec)

        for lv in common:
            print(f"  opt{lv}: baseline get_registers={base_lv[lv].get('get_registers')}  "
                  f"output_equiv={base_lv[lv].get('output_equivalent')}")
            print(f"          candidate get_registers={cand_lv[lv].get('get_registers')}  "
                  f"output_equiv={cand_lv[lv].get('output_equivalent')}")
        print(f"\ndivergent levels: {divergent_levels or 'none'}")
        print(f"register_diverges={register_diverges}  output_oracle_blind={output_blind}  "
              f"=> fault_detected={fault_detected}")
        print(f"verdict: {rec['verdict']} — {rec['note']}")
        return 0 if fault_detected else (2 if output_blind else 3)


def _emit(out_root: Path, rec: dict) -> None:
    out = out_root / f"contract_register_15024-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(rec, indent=2, default=str))
    print(f"raw: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
