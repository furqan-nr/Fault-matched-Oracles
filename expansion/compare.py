#!/usr/bin/env python3
"""Diff fix-vs-bug probe results and print the Paper-1B candidate verdicts.
  python compare.py --dir results_expansion
Verdict per PR: blind (output-side evidence identical/equivalent on the BUGGY build)
and detect (channel-matched signal differs between FIX and BUG)."""
import argparse, json, math
from pathlib import Path

def load(d, pr, lab):
    f = Path(d) / f"pr{pr}" / f"{lab}.json"
    return json.loads(f.read_text()) if f.exists() else None

def close_mod(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi) < 1e-9

def v15943(fx, bg):
    det, blind, notes = False, True, []
    for t, fv in fx.items():
        bv = bg[t]
        if not fv["operator_exact_equal"]:
            notes.append(f"{t}: FIX not exactly operator-equal (trigger suspect)")
        if fv["operator_exact_equal"] and not bv["operator_exact_equal"]:
            det = True
        blind &= bool(bv["equiv_mod_phase"])
        notes.append(f"{t}: REPO gp_oracle fix/bug={fv.get('gp_oracle_equivalent')}/{bv.get('gp_oracle_equivalent')} "
                     f"semantic_oracle bug={bv.get('semantic_oracle_equivalent')}")
        notes.append(f"{t}: gp in={bv['in_gp']:.4f} fix_out={fv['out_gp']:.4f} bug_out={bv['out_gp']:.4f} "
                     f"exact_eq fix/bug={fv['operator_exact_equal']}/{bv['operator_exact_equal']} "
                     f"mod-phase-eq bug={bv['equiv_mod_phase']}")
    return det, blind, notes

def v13833(fx, bg):
    det = bool(fx["contract_ok"]) and not bool(bg["contract_ok"])
    blind = fx["fp"] == bg["fp"]
    notes_repo = f"REPO check_contracts fix={fx.get('repo_check_contracts')} bug={bg.get('repo_check_contracts')} semantic bug={bg.get('repo_semantic_equivalent')}"
    return det, blind, [notes_repo, f"fix final={fx.get('final_index_layout')} bug final={bg.get('final_index_layout')} "
                        f"bug len(initial/final)={bg['len_initial']}/{bg['len_final']} bug_err={bg.get('final_index_layout_error')}"]

def v13945(fx, bg):
    # reference-free: a pipeline is a contract violation if its claimed virtual permutation does not
    # reproduce the original operator. Detect = some pipeline consistent on FIX but inconsistent on BUG.
    viol = [k for k in fx if fx[k].get("permutation_consistent") is True and bg[k].get("permutation_consistent") is False]
    fix_bad = [k for k in fx if fx[k].get("permutation_consistent") is False]
    diff = [k for k in fx if fx[k].get("vpl") != bg[k].get("vpl")]
    det = bool(viol)
    blind = det and all(fx[k].get("fp") == bg[k].get("fp") for k in viol)
    return det, blind, [f"violating pipelines on BUG (consistent on FIX): {viol}",
                        f"pipelines where vpl differs fix-vs-bug: {diff}",
                        f"pipelines inconsistent on FIX (should be empty): {fix_bad}"]

def v14763(fx, bg):
    det = (bg["n_structurally_unequal"] or 0) > 0 and (fx["n_structurally_unequal"] or 0) == 0
    blind = bg["n_output_fingerprint_unequal"] == 0
    return det, blind, [f"bug: {bg['n_structurally_unequal']}/{bg['repeats']} structurally unequal, "
                        f"{bg['n_output_fingerprint_unequal']}/{bg['repeats']} output-fingerprint unequal; "
                        f"fix: {fx['n_structurally_unequal']}/{fx['repeats']}"]

V = {"15943": ("phase", v15943), "13833": ("contract", v13833),
     "13945": ("contract", v13945), "14763": ("determinism", v14763)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", default="results_expansion")
    a = ap.parse_args(); rows = []
    for pr, (ch, fn) in V.items():
        fx, bg = load(a.dir, pr, "fix"), load(a.dir, pr, "bug")
        if not fx or not bg:
            print(f"PR {pr}: missing fix/bug probe output"); continue
        if fx["status"] != "ok" or bg["status"] != "ok":
            print(f"PR {pr} [{ch}]: probe error  fix={fx.get('error')}  bug={bg.get('error')}")
            rows.append({"pr": pr, "channel": ch, "verdict": "probe_error"}); continue
        det, blind, notes = fn(fx["result"], bg["result"])
        v = "REPRODUCED: invisible + detected" if (det and blind) else \
            "detected but NOT output-blind" if det else "NOT detected by this trigger"
        print(f"\nPR {pr} [{ch}]  fix={fx['qiskit']} bug={bg['qiskit']}\n  detect={det} blind={blind} => {v}")
        for n in notes: print("   ", n)
        rows.append({"pr": pr, "channel": ch, "detect": det, "blind": blind, "verdict": v, "notes": notes})
    (Path(a.dir) / "expansion_summary.json").write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {Path(a.dir)/'expansion_summary.json'}")
