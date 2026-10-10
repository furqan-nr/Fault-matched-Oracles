#!/usr/bin/env python3
"""Apply the fixed definitions of PROTOCOL_1B_HARVEST.md Sec. 5 to the fix/parent probe results.
  python compare_harvest.py --dir results_harvest
Prints one line per PR: reproduced? output-invisible? channel? (detection class is assigned afterwards, by hand, against oracle tag v1.2.0)."""
import argparse, json
from pathlib import Path

def load(d, pr, lab):
    f = Path(d) / f"pr{pr}" / f"{lab}.json"
    if not f.exists():
        return None
    r = json.loads(f.read_text())
    return r.get("result"), r

def v16920(fx, bg):
    reproduced = bool(fx.get("equals_expected")) and not bg.get("equals_expected", False)
    if bg.get("ran") is False:
        vis = "visible (parent crashed)"
    elif bg.get("outcome_preserved") is False:
        vis = "visible (measured outcome of the parent output differs from the input)"
    else:
        vis = "invisible (outcome preserved)"
    return reproduced, vis, "out of scope (property asserted: which qubit is measured; not layout/permutation metadata, global phase, or run-to-run stability)", \
        [f"fix outcome {fx.get('output_outcome')}, bug outcome {bg.get('output_outcome')}, input outcome {bg.get('input_outcome')}",
         f"fix equals_expected={fx.get('equals_expected')} bug equals_expected={bg.get('equals_expected')}",
         f"bug output ops {bg.get('output_ops')} expected {bg.get('expected_ops')}"]

def v16880(fx, bg):
    notes, fixok, bugbad = [], True, []
    for p, t in fx.items():
        fixok &= bool(t.get("equal"))
    for p, t in bg.items():
        if not t.get("equal"):
            bugbad.append(p)
        notes.append(f"{p}: fix equal={fx[p].get('equal')} (pauli {fx[p].get('input_pauli')}->{fx[p].get('output_pauli')}); bug equal={t.get('equal')} (pauli {t.get('input_pauli')}->{t.get('output_pauli')})")
    reproduced = fixok and bool(bugbad)
    vis = "visible (parent output measures a different signed Pauli than the input)" if bugbad else "n/a"
    return reproduced, vis, "out of scope (property asserted: sign of a Pauli-product measurement is preserved)", notes

def v16336(fx, bg):
    reproduced = bool(fx.get("seed_is_1234")) and not bool(bg.get("seed_is_1234"))
    notes = [f"seed seen by SabreLayout.run: fix {fx.get('seed_seen')} ({fx.get('seed_seen_type')}), bug {bg.get('seed_seen')} ({bg.get('seed_seen_type')})"]
    for k in ["env_vs_env_equal", "env_vs_explicit1234_equal", "env_vs_explicit1_equal", "explicit1234_vs_explicit1_equal", "explicit1234_run_to_run_equal"]:
        notes.append(f"{k}: fix={fx.get(k)} bug={bg.get(k)}")
    notes.append(f"repo check_semantic on env run: fix={fx.get('repo_semantic_equivalent_env_run')} bug={bg.get('repo_semantic_equivalent_env_run')} ({bg.get('repo_semantic_strength')})")
    vis = "invisible to output equivalence (output is a valid, equivalent circuit for any seed)"
    return reproduced, vis, "out of scope under the literal rule (property asserted: the seed value reaching the layout pass; not run-to-run or ordering stability). Supplementary seed-honouring result in notes.", notes

V = {"16920": v16920, "16880": v16880, "16336": v16336}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", default="results_harvest"); a = ap.parse_args()
    summary = {}
    for pr, fn in V.items():
        fx, bg = load(a.dir, pr, "fix"), load(a.dir, pr, "bug")
        if not fx or not bg or fx[0] is None or bg[0] is None:
            print(f"#{pr}: MISSING/FATAL results", fx and fx[1].get("fatal"), bg and bg[1].get("fatal")); continue
        rep, vis, chan, notes = fn(fx[0], bg[0])
        summary[pr] = {"reproduced": rep, "invisibility": vis, "channel": chan, "notes": notes,
                       "fix_version": fx[1]["qiskit"], "bug_version": bg[1]["qiskit"]}
        print(f"#{pr} [fix {fx[1]['qiskit']} / parent {bg[1]['qiskit']}]\n  reproduced: {rep}\n  invisibility: {vis}\n  channel: {chan}")
        for n in notes: print("   -", n)
    print("#15683: not built; typo/comment-only change -> out of scope (not a defect fix)")
    Path(a.dir, "harvest_summary.json").write_text(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
