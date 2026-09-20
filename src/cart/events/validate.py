"""Event-table validation (METHODOLOGY §1.2–1.4, §1.6).

Structural/leakage checks only — these verify the dataset is well-formed and leakage-safe.
They are NOT outcome thresholds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from cart.events.schema import Event, FaultSource
from cart.events.mutations import MUTATION_OPERATORS
from cart.events.table import compute_split_group_id

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ValidationReport:
    n_events: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_events(events: list[Event], *, require_ready: bool = False) -> ValidationReport:
    """Validate the event table.

    require_ready=False: structural checks suitable while the dataset is still being assembled
      (historical SHAs may be placeholders like 'TBD-...').
    require_ready=True: also require real SHAs everywhere (pre-Phase-2 gate).
    """
    rep = ValidationReport(n_events=len(events))

    ids: dict[str, int] = {}
    fault_ids: dict[str, int] = {}
    group_sides: dict[str, set[str]] = {}

    n_hist = n_mut = 0
    for e in events:
        ids[e.event_id] = ids.get(e.event_id, 0) + 1
        fault_ids[e.fault_id] = fault_ids.get(e.fault_id, 0) + 1

        if e.fault_source == FaultSource.historical:
            n_hist += 1
        else:
            n_mut += 1

        # date format
        if not _ISO_DATE_RE.match(e.event_date):
            rep.errors.append(f"{e.event_id}: event_date not ISO (YYYY-MM-DD): {e.event_date!r}")

        # split_group_id must match the canonical rule
        expected_group = compute_split_group_id(e.baseline_sha, e.mutation_family)
        if e.split_group_id != expected_group:
            rep.errors.append(
                f"{e.event_id}: split_group_id {e.split_group_id!r} != expected {expected_group!r}"
            )

        # mutation-specific rules
        if e.fault_source == FaultSource.mutation:
            if not e.mutation_family:
                rep.errors.append(f"{e.event_id}: mutation event missing mutation_family")
            elif e.mutation_family not in MUTATION_OPERATORS:
                rep.errors.append(f"{e.event_id}: unknown mutation_family {e.mutation_family!r}")
            if e.baseline_sha != e.candidate_sha:
                rep.warnings.append(
                    f"{e.event_id}: mutation baseline_sha != candidate_sha "
                    "(mutations usually share one build)"
                )
        else:  # historical
            if e.mutation_family:
                rep.errors.append(f"{e.event_id}: historical event must not set mutation_family")

        # SHA checks
        for fld in ("baseline_sha", "candidate_sha"):
            val = getattr(e, fld)
            if require_ready and not _SHA_RE.match(val):
                rep.errors.append(f"{e.event_id}: {fld} not a real SHA (got {val!r})")
            elif not require_ready and not (_SHA_RE.match(val) or val.startswith("TBD")):
                rep.warnings.append(f"{e.event_id}: {fld} placeholder {val!r}")

        if not e.event_environment_id:
            rep.errors.append(f"{e.event_id}: missing event_environment_id")

        # split-group integrity: a group must be entirely train or entirely test (§1.6/§5.1)
        group_sides.setdefault(e.split_group_id, set()).add(e.train_or_test.value)

    for eid, c in ids.items():
        if c > 1:
            rep.errors.append(f"duplicate event_id: {eid} ({c}x)")
    for fid, c in fault_ids.items():
        if c > 1:
            rep.errors.append(f"duplicate fault_id: {fid} ({c}x)")
    for g, sides in group_sides.items():
        if len(sides) > 1:
            rep.errors.append(f"split_group_id {g!r} spans both train and test (leakage): {sides}")

    rep.counts = {
        "historical": n_hist,
        "mutation": n_mut,
        "distinct_fault_ids": len(fault_ids),
        "split_groups": len(group_sides),
    }

    # §1.4 dataset-size + composition guidance (warnings, not hard errors)
    if not (8 <= len(events) <= 12):
        rep.warnings.append(f"micro corpus target is 8-12 events; have {len(events)}")
    if n_hist == 0:
        rep.warnings.append("no historical events; methodology prefers historical (mutations only fill gaps)")

    return rep
