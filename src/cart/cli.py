"""cart command-line entrypoints.

Phase 0 is implemented (`manifest`). Later phases are wired incrementally per
PROJECT_PLAN.md, respecting phase order.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cart", description="Cost-aware regression testing for Qiskit transpilation")
    sub = p.add_subparsers(dest="command")

    m = sub.add_parser("manifest", help="Phase 0: build static manifest + instrumentation smoke profile")
    m.add_argument("--out-data", default=str(_REPO_ROOT / "data" / "manifest_static"))
    m.add_argument("--out-results", default=None, help="results/<run_id> dir (default: timestamped)")
    m.add_argument("--smoke-limit", type=int, default=6)
    m.add_argument("--no-smoke", action="store_true", help="build static manifest only")
    m.add_argument("--profile", choices=["pilot", "costhet"], default="pilot",
                   help="'pilot' = default n<=18 grid; 'costhet' = cost-heterogeneous corpus (Paper 2 / B1)")

    ev = sub.add_parser("events", help="Phase 1: build/validate the event table")
    ev.add_argument("action", choices=["build", "validate"])
    ev.add_argument("--table", default=None, help="path to events.json (default: data/events/events.json)")
    ev.add_argument("--cutoff", default=None, help="cutoff_date for group-level split assignment")
    ev.add_argument("--require-ready", action="store_true", help="require real SHAs (pre-Phase-2 gate)")
    gt = sub.add_parser("ground-truth", help="Phase 2: per-event baseline profile + oracle labels")
    gt.add_argument("--out-root", default=str(_REPO_ROOT / "data"), help="data root (raw/derived/profile_baseline)")
    gt.add_argument("--unit-limit", type=int, default=8, help="number of manifest test units to use")
    gt.add_argument("--max-qubits", type=int, default=None,
                    help="keep only test units with n_qubits <= this (caps compute; e.g. 8 drops the "
                         "expensive 12-qubit line-topology units)")
    gt.add_argument("--cost-repeats", type=int, default=5,
                    help="clean process_time runs (1 warmup discarded) for the baseline_cost_s median "
                         "+ dispersion; B1 §5 pre-declared >=5 for the frozen cost calibration")
    sel = sub.add_parser("select", help="Phase 3: run baseline selectors per event")
    sel.add_argument("--baseline", default="all", help="baseline name or 'all'")
    sel.add_argument("--tier", default="pr", choices=["pr", "nightly", "release"])
    sel.add_argument("--budget", type=float, default=None, help="override budget seconds")
    sel.add_argument("--seed", type=int, default=0)
    sel.add_argument("--out-results", default=None)
    evl = sub.add_parser("evaluate", help="Phase 5: metrics + validity gates")
    evl.add_argument("--split", default="all", choices=["all", "train", "test"])
    evl.add_argument("--random-seeds", type=int, default=20,
                     help="number of seeds to aggregate the random baseline over (median/range)")
    evl.add_argument("--out-results", default=None)

    an = sub.add_parser("analyze", help="Ablation + sensitivity of risk_score over cached labels (no transpilation)")
    an.add_argument("--split", default="all", choices=["all", "train", "test"])
    an.add_argument("--out-results", default=None)

    hr = sub.add_parser("historical-run", help="Run one historical event via per-event from-source venvs")
    hr.add_argument("--event", required=True)
    hr.add_argument("--unit-limit", type=int, default=4)
    hr.add_argument("--candidate-basis", default=None,
                    help="comma list overriding candidate basis (functional fixture, e.g. 'cx')")
    hr.add_argument("--use-targeted", action="store_true",
                    help="run the event's targeted regression-trigger unit(s) instead of generic units")
    return p


def _cmd_manifest(args: argparse.Namespace) -> int:
    from cart.manifest.static_manifest import (
        build_static_manifest, enumerate_test_units, enumerate_costhet_units, validate_circuits_constructible,
    )
    from cart.manifest.smoke_profile import run_smoke_profile

    profile = getattr(args, "profile", "pilot")
    units = enumerate_costhet_units() if profile == "costhet" else enumerate_test_units()
    n_families = validate_circuits_constructible(units)
    manifest_path = build_static_manifest(args.out_data, units=units)
    print(f"static manifest [{profile}]: {manifest_path}  ({len(units)} units, {n_families} family/width combos constructible)")

    if not args.no_smoke:
        results_dir = args.out_results or str(
            _REPO_ROOT / "results" / f"phase0-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}" / "smoke_profile"
        )
        smoke_path = run_smoke_profile(units, results_dir, limit=args.smoke_limit)
        print(f"smoke profile:   {smoke_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.command:
        build_parser().print_help()
        return 0
    if args.command == "manifest":
        return _cmd_manifest(args)
    if args.command == "events":
        return _cmd_events(args)
    if args.command == "ground-truth":
        return _cmd_ground_truth(args)
    if args.command == "select":
        return _cmd_select(args)
    if args.command == "evaluate":
        return _cmd_evaluate(args)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "historical-run":
        return _cmd_historical_run(args)
    raise SystemExit(f"'{args.command}' not implemented yet — see PROJECT_PLAN.md for phase order.")


def _cmd_analyze(args) -> int:
    import json
    import yaml
    from datetime import datetime, timezone
    from pathlib import Path
    from cart.metrics.evaluate import run_ablation, run_sensitivity

    cutoff = (yaml.safe_load((_REPO_ROOT / "configs" / "cutoff.yaml").read_text()) or {}).get("cutoff_date")
    abl = run_ablation(cutoff_date=cutoff, split=args.split)
    sen = run_sensitivity(cutoff_date=cutoff, split=args.split)

    print("=== Ablation (proposed risk_score; mean AUC by source) ===")
    for variant, by_src in abl["variants"].items():
        cells = "  ".join(f"{s}: AUC={m['mean_AUC']} nTTFR={m['mean_normalized_TTFR']}"
                          for s, m in by_src.items())
        print(f"  {variant:>20}: {cells}")
    print("=== Sensitivity (mutation-source mean AUC over reserve × epsilon) ===")
    for g in sen["grid"]:
        mut = g["result"].get("mutation", {})
        print(f"  reserve={g['reserve_frac']} eps={g['epsilon']}: AUC={mut.get('mean_AUC')}")

    out = args.out_results or str(_REPO_ROOT / "results" /
                                 f"analyze-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}" / "analysis.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"ablation": abl, "sensitivity": sen}, indent=2))
    print(f"analysis: {out}")
    return 0


def _cmd_historical_run(args) -> int:
    from cart.labels.historical_runner import run_historical
    cb = args.candidate_basis.split(",") if args.candidate_basis else None
    s = run_historical(args.event, unit_limit=args.unit_limit, candidate_basis=cb,
                       use_targeted=args.use_targeted)
    print(f"event {s['event_id']}: {s['n_records']} records | label_counts={s['label_counts']}")
    print("raw:", s["raw_artifact"])
    return 0


def _cmd_evaluate(args) -> int:
    import json
    import yaml
    from datetime import datetime, timezone
    from cart.metrics.evaluate import evaluate
    from cart.gates.validity import run_all_gates

    cutoff = (yaml.safe_load((_REPO_ROOT / "configs" / "cutoff.yaml").read_text()) or {}).get("cutoff_date")
    gates = run_all_gates()
    report = evaluate(cutoff_date=cutoff, split=args.split, random_seeds=args.random_seeds)
    report["validity_gates"] = gates

    print("=== Validity gates ===")
    for g in gates["gates"]:
        print(f"  [{'PASS' if g['passed'] else 'FAIL'}] {g['name']}: {g['detail']}")
    print(f"all gates passed: {gates['all_passed']}")
    print(f"=== Metrics (split={args.split}) | oracle FP rate={report['oracle_false_positive_rate']} "
          f"| random seeds={report['random_seeds']} ===")
    for source, sels in report["by_source"].items():
        print(f"-- source: {source} ({sels.get('proposed', {}).get('n_events', '?')} events) --")
        for name, m in sels.items():
            print(f"  {name:>15}: recall@20%={m['recall@20%']} nTTFR={m['mean_normalized_TTFR']} "
                  f"AUC={m['mean_AUC_detection_vs_budget']} overhead={m['mean_selection_overhead_s']}s")
        rms = report["random_multiseed"].get(source, {})
        if rms:
            a = rms["mean_AUC_detection_vs_budget"]
            print(f"  random over {rms['n_seeds']} seeds: AUC median={a['median']} "
                  f"[min {a['min']}, max {a['max']}]")
        print(f"  win/tie/loss (proposed vs):")
        for base, w in report["win_tie_loss"].get(source, {}).items():
            print(f"      vs {base:>14}: {w['win']}/{w['tie']}/{w['loss']}")

    out = args.out_results or str(_REPO_ROOT / "results" /
                                 f"phase5-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}" / "evaluation.json")
    from pathlib import Path
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2))
    print(f"report: {out}")
    return 0 if gates["all_passed"] else 1


def _cmd_select(args) -> int:
    import json
    import yaml
    from datetime import datetime, timezone
    from cart.selectors.context import SelectionContext
    from cart.selectors.baselines import BASELINES
    from cart.selectors.proposed import proposed_selector
    from cart.selectors.cost_model import expected_cost

    selectors = {**BASELINES, "proposed": proposed_selector}

    ctx = SelectionContext.load()
    if not ctx.events:
        print("no events; seed data/events/events.json first.")
        return 1

    if args.budget is not None:
        budget_s = args.budget
    else:
        tiers = yaml.safe_load((_REPO_ROOT / "configs" / "budgets.yaml").read_text())["tiers"]
        budget_s = tiers[args.tier]["budget_s"]
        if budget_s is None:
            budget_s = float("inf")

    names = list(selectors) if args.baseline == "all" else [args.baseline]
    rows = []
    for event_id in ctx.events:
        for name in names:
            sel = selectors[name](ctx, event_id, budget_s, seed=args.seed)
            spent = sum(expected_cost(ctx, event_id, t) for t in sel)
            rows.append({"event_id": event_id, "baseline": name, "n_selected": len(sel),
                         "budget_s": budget_s, "spent_s": spent, "selected": sel})

    out = args.out_results or str(_REPO_ROOT / "results" /
                                 f"phase3-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}" / "selections.json")
    from pathlib import Path
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"schema": "selections/v1", "tier": args.tier,
                                     "budget_s": budget_s, "n_rows": len(rows), "rows": rows}, indent=2))
    print(f"selections: {out}  ({len(rows)} event x baseline rows, budget={budget_s}s)")
    return 0


def _cmd_ground_truth(args) -> int:
    from cart.events.table import load_events
    from cart.manifest.static_manifest import units_for
    from cart.labels.ground_truth import run_ground_truth

    events = load_events()
    if not events:
        print("no events; seed data/events/events.json first.")
        return 1
    units = units_for(args.out_root)   # use the generated manifest (costhet if built), else pilot default
    if args.max_qubits is not None:
        units = [u for u in units if u.n_qubits <= args.max_qubits]
        print(f"width cap: keeping {len(units)} units with n_qubits <= {args.max_qubits}")
    summary = run_ground_truth(events, units, args.out_root, unit_limit=args.unit_limit,
                               cost_repeats=args.cost_repeats)
    print(f"records: {summary['n_records']} | label_counts: {summary['label_counts']}")
    print(f"events skipped: {summary['n_events_skipped']}")
    for s in summary["skipped"]:
        print(f"  SKIP: {s}")
    print(f"labels:   {summary['labels_path']}")
    print(f"profiles: {summary['profiles_path']}")
    return 0


def _cmd_events(args) -> int:
    from cart.events.table import DEFAULT_TABLE, load_events, save_events
    from cart.events.validate import validate_events

    table = args.table or DEFAULT_TABLE
    events = load_events(table)
    if not events:
        print(f"no events found at {table}. Seed it first (data/events/events.json).")
        return 1

    if args.action == "validate":
        rep = validate_events(events, require_ready=args.require_ready)
        print(f"events: {rep.n_events} | counts: {rep.counts}")
        for w in rep.warnings:
            print(f"  WARN: {w}")
        for e in rep.errors:
            print(f"  ERROR: {e}")
        print("VALID" if rep.ok else "INVALID")
        return 0 if rep.ok else 1

    # build: (re)assign group-level split if a cutoff is given, then re-save + validate
    if args.cutoff:
        from cart.events.table import assign_splits_group_level
        events = assign_splits_group_level(events, args.cutoff)
        save_events(events, table)
        print(f"assigned group-level split at cutoff {args.cutoff}; saved {table}")
    rep = validate_events(events, require_ready=args.require_ready)
    print(f"events: {rep.n_events} | counts: {rep.counts} | {'VALID' if rep.ok else 'INVALID'}")
    for e in rep.errors:
        print(f"  ERROR: {e}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
