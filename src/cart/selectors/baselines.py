"""Five baseline selectors (METHODOLOGY §3).

All observe the same per-event budget and use only pre-execution information (SelectionContext).
Each returns an ordered list of selected test_ids whose cumulative expected_cost <= budget.
"""
from __future__ import annotations

import random
from typing import Callable

from cart.selectors.context import SelectionContext
from cart.selectors.cost_model import expected_cost


def _within_budget(ctx: SelectionContext, event_id: str, ordered: list[str], budget_s: float) -> list[str]:
    """Greedily keep tests in order while cumulative expected_cost <= budget."""
    chosen, spent = [], 0.0
    for t in ordered:
        c = expected_cost(ctx, event_id, t)
        if spent + c <= budget_s:
            chosen.append(t)
            spent += c
    return chosen


def random_selector(ctx, event_id, budget_s, *, seed=0):
    ids = ctx.candidate_test_ids()
    rng = random.Random(seed)
    order = ids[:]
    rng.shuffle(order)
    return _within_budget(ctx, event_id, order, budget_s)


def cheapest_first(ctx, event_id, budget_s, **_):
    ids = ctx.candidate_test_ids()
    order = sorted(ids, key=lambda t: ctx.baseline_cost(event_id, t))
    return _within_budget(ctx, event_id, order, budget_s)


def diversity_only(ctx, event_id, budget_s, **_):
    """Greedy coverage across (circuit_family, backend_id); then cheapest of the rest."""
    ids = ctx.candidate_test_ids()
    by_cost = sorted(ids, key=lambda t: ctx.baseline_cost(event_id, t))
    seen_combo, first_pass, rest = set(), [], []
    for t in by_cost:
        m = ctx.test_meta(t)
        combo = (m.circuit_family, m.backend_id)
        (first_pass if combo not in seen_combo else rest).append(t)
        seen_combo.add(combo)
    return _within_budget(ctx, event_id, first_pass + rest, budget_s)


def history_only(ctx, event_id, budget_s, **_):
    """Rank by historical failure rate from events strictly before this event_date (§4.3)."""
    ev = ctx.event(event_id)
    ids = ctx.candidate_test_ids()
    order = sorted(
        ids,
        key=lambda t: (
            -ctx.prior_failure_rate(t, ev.event_date, exclude_event=event_id),
            ctx.baseline_cost(event_id, t),     # tie-break: cheaper first
        ),
    )
    return _within_budget(ctx, event_id, order, budget_s)


def _change_stage_match(ctx, event_id, test_id) -> float:
    modified = set(ctx.event(event_id).change_metadata.get("modified_pass_stages", []))
    if not modified:
        return 0.0
    test_stages = set(ctx.test_meta(test_id).declared_pass_stages)
    return len(modified & test_stages) / len(modified)


def change_stage(ctx, event_id, budget_s, **_):
    """Prefer tests exercising the modified pass stage; tie-break by cheaper cost."""
    ids = ctx.candidate_test_ids()
    order = sorted(
        ids,
        key=lambda t: (-_change_stage_match(ctx, event_id, t), ctx.baseline_cost(event_id, t)),
    )
    return _within_budget(ctx, event_id, order, budget_s)


BASELINES: dict[str, Callable] = {
    "random": random_selector,
    "cheapest_first": cheapest_first,
    "diversity_only": diversity_only,
    "history_only": history_only,
    "change_stage": change_stage,
}


def run_baseline(name: str, ctx: SelectionContext, event_id: str, budget_s: float, *, seed: int = 0):
    if name not in BASELINES:
        raise KeyError(f"unknown baseline {name!r}; known: {sorted(BASELINES)}")
    return BASELINES[name](ctx, event_id, budget_s, seed=seed)
