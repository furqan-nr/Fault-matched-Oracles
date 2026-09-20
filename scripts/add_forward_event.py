#!/usr/bin/env python3
"""Add a forward_regression event to the ledger from a known INTRODUCING commit (no bisection).

For "feature added then reverted/fixed" regressions the introducing commit is named in the PR/issue
(or found with one `git blame`/`git log -S` on the fix's changed file). Given that commit, this
script resolves the parent (last-known-good baseline) and the commit date via git, then splices a
forward_regression event into data/events/events.json. You then build the two venvs and verify.

It does NOT bisect and does NOT need network beyond a clone you already have (reuses an existing
per-event qiskit clone for git history).

Example (a circuit-quality regression, PR #14667):
  python scripts/add_forward_event.py \
      --event-id hist-vf2layout-maxtrials --env-id hist-vf2maxtrials-14667 \
      --fault-type quality --pr 14667 --pass-stage layout \
      --reference "Restore correct max_trials behaviour for VF2Layout pass" \
      --introducing-sha <INTRODUCING_COMMIT_SHA>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVENTS = _REPO_ROOT / "data" / "events" / "events.json"
_EVENTS_CSV = _REPO_ROOT / "data" / "events" / "events.csv"
_DEFAULT_CLONE = _REPO_ROOT / "environment" / "_builds" / "hist-vf2post-14120-base" / "qiskit"

_FAULT_SLUG = {"quality": "quality", "performance": "perf", "functional": "crash", "semantic": "semantic",
               "contract_metadata": "contract", "determinism": "determinism"}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}\n"
                         f"(is {repo} a qiskit clone with the commit fetched? try: git -C \"{repo}\" fetch --all --tags)")
    return r.stdout.strip()



def _gate_and_mirror(args, event):
    """Enforce the verification gate, then keep events.csv in step with events.json."""
    import csv as _csv
    if args.verified_from:
        d = json.loads(Path(args.verified_from).read_text())
        if not (d.get("fault_detected") is True):
            raise SystemExit(f"refusing to promote: {args.verified_from} does not report fault_detected=true")
        event["reproducibility_status"] = "verified"
    if str(event.get("reproducibility_status", "")).lower() == "blocked":
        print("!! status is 'blocked' - the ledger validator will reject this event.\n"
              "   Pass --verified-from <verifier.json> (or --status verified) only if a forward run "
              "reported fault_detected=true.")
    with open(_EVENTS_CSV, newline="", encoding="utf-8") as fh:
        header = next(_csv.reader(fh))
    with open(_EVENTS_CSV, "a", newline="", encoding="utf-8") as fh:
        _csv.writer(fh, lineterminator="\n").writerow([str(event.get(c, "") or "") for c in header])
    print(f"  mirrored row into {_EVENTS_CSV.name} ({len(header)} fields)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Splice a forward_regression event into the ledger.")
    p.add_argument("--event-id", required=True)
    p.add_argument("--env-id", required=True, help="event_environment_id (venvs go to _builds/<env-id>-base|-cand)")
    p.add_argument("--fault-type", required=True, choices=["quality", "performance", "functional", "semantic", "contract_metadata", "determinism"])
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--reference", required=True, help="short human description (PR title)")
    p.add_argument("--introducing-sha", required=True, help="the commit that INTRODUCED the regression (candidate)")
    p.add_argument("--baseline-sha", default=None, help="override; default = introducing^ (parent)")
    p.add_argument("--pass-stage", default="optimization", help="comma list of modified_pass_stages")
    p.add_argument("--repo", default=str(_DEFAULT_CLONE), help="path to an existing qiskit clone for git history")
    p.add_argument("--status", default="blocked",
                   choices=["blocked", "verified", "reproduced", "confirmed"],
                   help="stays 'blocked' unless you have a positive verification run")
    p.add_argument("--verified-from", default=None,
                   help="path to a verifier JSON with fault_detected=true; sets status=verified")
    p.add_argument("--cutoff", default=None, help="YYYY-MM-DD; default from configs/cutoff.yaml")
    args = p.parse_args(argv)

    repo = Path(args.repo)
    cand = _git(repo, "rev-parse", args.introducing_sha)
    base = args.baseline_sha or _git(repo, "rev-parse", f"{args.introducing_sha}^")
    date = _git(repo, "show", "-s", "--format=%cs", cand)            # commit date YYYY-MM-DD

    cutoff = args.cutoff
    if cutoff is None:
        try:
            import yaml
            cutoff = (yaml.safe_load((_REPO_ROOT / "configs" / "cutoff.yaml").read_text()) or {}).get("cutoff_date")
        except Exception:
            cutoff = None
    split = ("test" if (cutoff and date >= cutoff) else "train")

    stages = [s.strip() for s in args.pass_stage.split(",") if s.strip()]
    event = {
        "event_id": args.event_id,
        "baseline_sha": base,
        "candidate_sha": cand,
        "fault_id": f"qiskit-pr-{args.pr}-{_FAULT_SLUG[args.fault_type]}",
        "fault_source": "historical",
        "fault_type": args.fault_type,
        "event_environment_id": args.env_id,
        "split_group_id": base[:12],
        "event_date": date,
        "train_or_test": split,
        "change_metadata": {"kind": "historical", "modified_pass_stages": stages,
                            "pr": args.pr, "reference": args.reference},
        "mutation_family": None,
        "mutation_params": {},
        "notes": f"Forward regression candidate (PR #{args.pr}); verify locally by building base/cand and "
                 f"running the matching oracle. Pending verification.",
        "reproducibility_status": args.status,
        "event_kind": "forward_regression",
        "pair_orientation": "forward",
        "evaluation_cohort": "forward_regression",
        "change_metadata_sha": cand,
    }

    text = _EVENTS.read_text()
    if f'"event_id": "{args.event_id}"' in text:
        raise SystemExit(f"event_id {args.event_id!r} already present in the ledger; choose another.")
    block = "\n".join("    " + ln for ln in json.dumps(event, indent=2).splitlines())
    idx = text.rfind("\n  ]")
    if idx < 0:
        raise SystemExit("could not locate the events array close in events.json")
    new = text[:idx] + ",\n" + block + text[idx:]
    new = re.sub(r'"n_events":\s*\d+', lambda m: f'"n_events": {len(json.loads(text)["events"]) + 1}', new, count=1)
    json.loads(new)  # validate
    _EVENTS.write_text(new)
    _gate_and_mirror(args, event)

    print(f"added forward_regression event '{args.event_id}'")
    print(f"  candidate (buggy)   = {cand}")
    print(f"  baseline  (good)    = {base}   (= introducing^)")
    print(f"  event_date          = {date}  -> {split} side (cutoff {cutoff})")
    print("\nNext — build the two revisions, then verify:")
    print(f"  .\\environment\\setup\\build_qiskit_event.ps1 -Sha {base} -EventEnvId {args.env_id}-base -Force")
    print(f"  .\\environment\\setup\\build_qiskit_event.ps1 -Sha {cand} -EventEnvId {args.env_id}-cand -Force")
    if args.fault_type == "performance":
        print(f"  python scripts\\verify_h4_perf.py --event {args.event_id}")
    else:
        print(f"  python -m cart.cli historical-run --event {args.event_id} --unit-limit 32")
        print("  # detected if label_counts shows quality_regression / functional_fail / semantic_fail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
