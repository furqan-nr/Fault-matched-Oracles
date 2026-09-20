"""Event table I/O + split-group helpers (METHODOLOGY §1.2, §1.6, §5.1)."""
from __future__ import annotations

import json
from pathlib import Path

from cart.events.schema import Event, TrainOrTest

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TABLE = _REPO_ROOT / "data" / "events" / "events.json"


def compute_split_group_id(base_revision: str, mutation_family: str | None) -> str:
    """split_group_id = base_revision + mutation_family (§1.6).

    Historical events (mutation_family is None) group by base_revision alone; each historical
    event is typically its own group. Mutation variants from the same operator on the same base
    share a group and must stay on one side of the temporal split.
    """
    base = base_revision[:12]
    return f"{base}+{mutation_family}" if mutation_family else base


def load_events(path: str | Path = DEFAULT_TABLE) -> list[Event]:
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Event.from_dict(d) for d in data["events"]]


def save_events(events: list[Event], path: str | Path = DEFAULT_TABLE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "event_table/v1",
        "n_events": len(events),
        "events": [e.to_dict() for e in events],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def assign_splits_group_level(events: list[Event], cutoff_date: str) -> list[Event]:
    """Assign train/test at split_group_id level (§1.6, §5.1).

    A group is 'test' if ANY member has event_date >= cutoff_date (a straddling group goes wholly
    to test — the conservative choice). Returns new Event objects with train_or_test set.
    """
    group_is_test: dict[str, bool] = {}
    for e in events:
        is_test = e.event_date >= cutoff_date
        group_is_test[e.split_group_id] = group_is_test.get(e.split_group_id, False) or is_test

    out: list[Event] = []
    for e in events:
        tot = TrainOrTest.test if group_is_test[e.split_group_id] else TrainOrTest.train
        out.append(Event.from_dict({**e.to_dict(), "train_or_test": tot.value}))
    return out
