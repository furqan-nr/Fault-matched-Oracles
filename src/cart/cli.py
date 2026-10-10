"""cart command-line entrypoints used by this reproduction archive.

`events` builds/validates the historical-event table (data/events/); `historical-run` runs one historical
event through per-event from-source virtual environments. The cost-aware test-selection harness that once
shared this module belongs to a different study and is not part of this archive.
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cart", description="Historical-event table and from-source event runs for the fault-matched oracles")
    sub = p.add_subparsers(dest="command")

    ev = sub.add_parser("events", help="build/validate the historical-event table")
    ev.add_argument("action", choices=["build", "validate"])
    ev.add_argument("--table", default=None, help="path to events.json (default: data/events/events.json)")
    ev.add_argument("--cutoff", default=None, help="cutoff_date for group-level split assignment")
    ev.add_argument("--require-ready", action="store_true", help="require real SHAs")

    hr = sub.add_parser("historical-run", help="Run one historical event via per-event from-source venvs")
    hr.add_argument("--event", required=True)
    hr.add_argument("--unit-limit", type=int, default=4)
    hr.add_argument("--candidate-basis", default=None,
                    help="comma list overriding candidate basis (functional fixture, e.g. 'cx')")
    hr.add_argument("--use-targeted", action="store_true",
                    help="run the event's targeted regression-trigger unit(s) instead of generic units")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.command:
        build_parser().print_help()
        return 0
    if args.command == "events":
        return _cmd_events(args)
    if args.command == "historical-run":
        return _cmd_historical_run(args)
    raise SystemExit(f"'{args.command}' is not available in this archive")


def _cmd_historical_run(args) -> int:
    from cart.labels.historical_runner import run_historical
    cb = args.candidate_basis.split(",") if args.candidate_basis else None
    s = run_historical(args.event, unit_limit=args.unit_limit, candidate_basis=cb,
                       use_targeted=args.use_targeted)
    print(f"event {s['event_id']}: {s['n_records']} records | label_counts={s['label_counts']}")
    print("raw:", s["raw_artifact"])
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
