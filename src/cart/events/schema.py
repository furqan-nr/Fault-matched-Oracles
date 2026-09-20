"""Event table schema (METHODOLOGY §1.1–1.3, §1.6).

The dataset unit is a *change event*, not a commit. The primary evaluation unit throughout all
phases is the ``(event_id, test_id)`` pair.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any


class FaultSource(str, Enum):
    historical = "historical"
    mutation = "mutation"


class FaultType(str, Enum):
    functional = "functional"   # compilation failure / crash / invalid output
    semantic = "semantic"       # wrong unitary / output
    quality = "quality"         # 2Q-count or depth degradation
    performance = "performance" # runtime / memory degradation
    contract_metadata = "contract_metadata"  # corrupted layout/permutation contract (output-invisible)
    determinism = "determinism"              # non-determinism across fixed seeds (output-invisible)


class TrainOrTest(str, Enum):
    train = "train"
    test = "test"


@dataclass(frozen=True)
class Event:
    event_id: str
    baseline_sha: str
    candidate_sha: str
    fault_id: str
    fault_source: FaultSource
    fault_type: FaultType
    event_environment_id: str
    split_group_id: str
    event_date: str                       # ISO date; rules in §1.1
    train_or_test: TrainOrTest
    # change metadata (modified pass stages / modules / diff) used by change_stage_match (§4.1).
    change_metadata: dict[str, Any] = field(default_factory=dict)
    # mutation-only: operator family + parameters (None for historical).
    mutation_family: str | None = None
    mutation_params: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    # cohort tagging (METHODOLOGY pilot decision): keep fix-boundary and forward-regression
    # cohorts separate; never pool them in headline results.
    event_kind: str = ""                 # forward_regression | fix_boundary_differential | controlled_mutation
    pair_orientation: str = ""           # forward | reverse_fix_boundary
    evaluation_cohort: str = ""          # forward_regression | fix_boundary | mutation
    change_metadata_sha: str = ""        # commit whose diff defines change_metadata (fix commit for fix-boundary)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fault_source"] = self.fault_source.value
        d["fault_type"] = self.fault_type.value
        d["train_or_test"] = self.train_or_test.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(
            event_id=d["event_id"],
            baseline_sha=d["baseline_sha"],
            candidate_sha=d["candidate_sha"],
            fault_id=d["fault_id"],
            fault_source=FaultSource(d["fault_source"]),
            fault_type=FaultType(d["fault_type"]),
            event_environment_id=d["event_environment_id"],
            split_group_id=d["split_group_id"],
            event_date=d["event_date"],
            train_or_test=TrainOrTest(d["train_or_test"]),
            change_metadata=d.get("change_metadata", {}),
            mutation_family=d.get("mutation_family"),
            mutation_params=d.get("mutation_params", {}),
            notes=d.get("notes", ""),
            event_kind=d.get("event_kind", ""),
            pair_orientation=d.get("pair_orientation", ""),
            evaluation_cohort=d.get("evaluation_cohort", ""),
            change_metadata_sha=d.get("change_metadata_sha", ""),
        )


# Canonical field order for tabular export.
EVENT_FIELDS = (
    "event_id", "baseline_sha", "candidate_sha", "fault_id", "fault_source", "fault_type",
    "event_environment_id", "split_group_id", "event_date", "train_or_test",
    "mutation_family", "notes",
)
