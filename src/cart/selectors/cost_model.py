"""Expected CI cost for selection (METHODOLOGY §2.2 total cost; §4.1 expected_cost).

expected_cost = baseline_cost_s + estimated_oracle_cost(oracle_type)

baseline_cost_s comes from test_profile_baseline (pre-execution, on the baseline). The oracle
cost estimate is a small pre-declared per-tier constant (the actual oracle cost is only known
after running, so selection uses an estimate; refine from prior runs at scale-up).
"""
from __future__ import annotations

from cart.selectors.context import SelectionContext

# Pre-declared oracle-cost estimates (seconds), by oracle tier.
ORACLE_COST_EST = {
    "unitary": 0.05,
    "sampled_sv": 0.20,
    "property": 0.05,
    "structural": 0.01,
}


def expected_cost(ctx: SelectionContext, event_id: str, test_id: str) -> float:
    base = ctx.baseline_cost(event_id, test_id)
    oracle_type = ctx.test_meta(test_id).oracle_type
    return base + ORACLE_COST_EST.get(oracle_type, 0.05)
