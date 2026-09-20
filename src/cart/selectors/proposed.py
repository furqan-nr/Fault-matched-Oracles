"""Proposed transparent selector — risk_score (METHODOLOGY §4.1-4.3).

risk_score(test | event) =
    (eps + change_stage_match)
  * circuit_backend_sensitivity
  * impact_prior                 # severity prior (NOT detectability)
  * oracle_confidence            # detectability (NOT severity)
  / expected_cost
  * novelty_multiplier           # diversity, stateful during greedy selection

Interpretable heuristic, NOT a calibrated probability (P-hat reserved for Phase 6 ML).
Budgeted selection reserves 10-20% of budget for stage-independent exploration (§4.2) and uses a
neutral cold-start fallback for history (§4.3). Uses ONLY pre-execution information.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from cart.manifest.circuits import build
from cart.manifest.backends import coupling_map_for
from cart.features.connectivity import connectivity_pressure, two_qubit_density
from cart.selectors.context import SelectionContext
from cart.selectors.cost_model import expected_cost
from cart.selectors.baselines import _change_stage_match

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Pre-declared component weights.
CIRCUIT_CRITICALITY = {"ghz": 1.0, "qft": 1.5, "qaoa_linear": 1.3, "random_clifford": 1.2}
ORACLE_CONFIDENCE = {"unitary": 1.0, "sampled_sv": 0.8, "property": 0.5, "structural": 0.3}
NOVELTY_DECAY = 0.5


def _config():
    b = yaml.safe_load((_REPO_ROOT / "configs" / "budgets.yaml").read_text())
    eps = float(b.get("risk_score_epsilon", 0.05))
    return eps, b.get("tiers", {})


@lru_cache(maxsize=256)
def _features(family: str, n: int, backend: str) -> tuple[int, float]:
    circ = build(family, n, seed=1234, measured=False)
    cmap = coupling_map_for(backend, n)
    return connectivity_pressure(circ, cmap), two_qubit_density(circ)


@dataclass
class _Components:
    csm: float
    cbs: float
    impact_prior: float
    oracle_confidence: float
    cost: float


def _components(ctx: SelectionContext, event_id: str, test_id: str, eps: float) -> _Components:
    m = ctx.test_meta(test_id)
    pressure, twoq = _features(m.circuit_family, m.n_qubits, m.backend_id)
    csm = eps + _change_stage_match(ctx, event_id, test_id)
    cbs = (1.0 + pressure) * (1.0 + twoq) * (1.0 + m.n_qubits / 30.0)
    hist = 1.0 + ctx.prior_failure_rate(test_id, ctx.event(event_id).event_date, exclude_event=event_id)
    impact = CIRCUIT_CRITICALITY.get(m.circuit_family, 1.0) * (1.0 + pressure) * hist
    oc = ORACLE_CONFIDENCE.get(m.oracle_type, 0.5)
    return _Components(csm, cbs, impact, oc, expected_cost(ctx, event_id, test_id))


def _combo(ctx, test_id):
    m = ctx.test_meta(test_id)
    return (m.circuit_family, m.backend_id)


def _novelty(combo, counts: dict) -> float:
    return NOVELTY_DECAY ** counts.get(combo, 0)


def proposed_selector(ctx: SelectionContext, event_id: str, budget_s: float, *,
                      seed: int = 0, reserve_frac: float | None = None,
                      ablate: tuple[str, ...] = (), eps_override: float | None = None) -> list[str]:
    """`ablate` disables risk_score components for ablation studies; recognised names:
    'novelty', 'change_stage', 'oracle_confidence', 'impact_prior'. `eps_override` and
    `reserve_frac` support sensitivity sweeps. All re-use cached labels (no transpilation)."""
    eps, tiers = _config()
    if eps_override is not None:
        eps = float(eps_override)
    if reserve_frac is None:
        reserve_frac = 0.15
    ab = set(ablate)
    comps = {t: _components(ctx, event_id, t, eps) for t in ctx.candidate_test_ids()}
    counts: dict = {}
    selected: list[str] = []
    spent = 0.0
    main_budget = budget_s * (1.0 - reserve_frac)

    def score(t, explore: bool) -> float:
        c = comps[t]
        nv = 1.0 if "novelty" in ab else _novelty(_combo(ctx, t), counts)
        imp = 1.0 if "impact_prior" in ab else c.impact_prior
        oc = 1.0 if "oracle_confidence" in ab else c.oracle_confidence
        base = c.cbs * imp * oc / max(c.cost, 1e-9) * nv
        csm = 1.0 if "change_stage" in ab else c.csm
        return base if explore else (csm * base)

    # main allocation: full risk_score
    remaining = set(comps)
    while True:
        fit = [t for t in remaining if comps[t].cost <= main_budget - spent + 1e-12]
        if not fit:
            break
        best = max(fit, key=lambda t: (score(t, explore=False), t))
        selected.append(best); spent += comps[best].cost
        counts[_combo(ctx, best)] = counts.get(_combo(ctx, best), 0) + 1
        remaining.discard(best)

    # exploration reserve: ignore change_stage_match; favor novelty/sensitivity
    while True:
        fit = [t for t in remaining if comps[t].cost <= budget_s - spent + 1e-12]
        if not fit:
            break
        best = max(fit, key=lambda t: (score(t, explore=True), t))
        selected.append(best); spent += comps[best].cost
        counts[_combo(ctx, best)] = counts.get(_combo(ctx, best), 0) + 1
        remaining.discard(best)

    # diversity constraint: ensure >=1 representative per circuit family, budget permitting
    fams_present = {ctx.test_meta(t).circuit_family for t in selected}
    for t in sorted(remaining, key=lambda t: comps[t].cost):
        fam = ctx.test_meta(t).circuit_family
        if fam not in fams_present and comps[t].cost <= budget_s - spent + 1e-12:
            selected.append(t); spent += comps[t].cost; fams_present.add(fam)

    return selected
