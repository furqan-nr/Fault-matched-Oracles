"""Per-event detection metrics (METHODOLOGY §5.2).

Given an ordered ranking of tests, a per-test CI cost, and a per-test detection flag (whether the
test detects THIS event's fault), compute the detection-vs-budget curve and its summaries. Each
micro-corpus event has a single fault, so detection is a 0/1 step that turns on at the first
detecting test (TTFR), then stays on.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_FRACTIONS = (0.05, 0.10, 0.20, 0.40)
# Budget-fraction grid for the detection-vs-budget figure (51 points over [0, 1]).
CURVE_GRID = tuple(i / 50 for i in range(51))


@dataclass
class EventMetrics:
    detected: bool
    ttfr_cost: float                 # cumulative cost to first detecting test (or full cost if none)
    full_suite_cost: float
    normalized_ttfr: float           # ttfr_cost / full_suite_cost  (1.0 if never detected)
    auc_detection_vs_budget: float   # area under detection(0/1) over budget fraction in [0,1]
    detection_at_fraction: dict[float, int] = field(default_factory=dict)


def event_metrics(ranking: list[str], cost: dict[str, float], detects: dict[str, bool],
                  fractions: tuple[float, ...] = DEFAULT_FRACTIONS) -> EventMetrics:
    full = sum(cost[t] for t in ranking)
    full = full if full > 0 else 1e-9

    cum = 0.0
    ttfr = full          # censored at full cost if never detected
    detected = False
    for t in ranking:
        cum += cost[t]
        if detects.get(t, False):
            ttfr = cum
            detected = True
            break

    norm_ttfr = min(ttfr / full, 1.0)
    # detection is a unit step turning on at norm_ttfr; AUC over [0,1] = 1 - norm_ttfr (0 if never)
    auc = (1.0 - norm_ttfr) if detected else 0.0

    det_at = {}
    for f in fractions:
        budget = f * full
        c = 0.0
        hit = 0
        for t in ranking:
            c += cost[t]
            if c <= budget + 1e-12 and detects.get(t, False):
                hit = 1
                break
            if c > budget + 1e-12:
                break
        det_at[f] = hit

    return EventMetrics(detected=detected, ttfr_cost=ttfr, full_suite_cost=full,
                        normalized_ttfr=norm_ttfr, auc_detection_vs_budget=auc,
                        detection_at_fraction=det_at)


def recall_at_budget(ranking: list[str], cost: dict[str, float], detects: dict[str, bool],
                     budget_s: float) -> int:
    """1 if the fault is detected by the prefix of `ranking` costing <= budget_s, else 0."""
    c = 0.0
    for t in ranking:
        c += cost[t]
        if c > budget_s + 1e-12:
            break
        if detects.get(t, False):
            return 1
    return 0


# --- Aggregation helpers for the expanded held-out report (reviewer must-fix #3) ----------

def win_tie_loss(proposed: dict[str, float], baseline: dict[str, float],
                 tol: float = 1e-9) -> dict[str, int]:
    """Per-event win/tie/loss of `proposed` vs `baseline` by normalized TTFR (lower is better).

    A *win* means the proposed selector reached the fault at a strictly smaller budget fraction
    on that event; a *loss* the reverse; a *tie* within ``tol``. Events absent from either map
    are skipped. No p-values are produced (pilot scale; per METHODOLOGY §5.4).
    """
    win = tie = loss = 0
    for e, pv in proposed.items():
        if e not in baseline:
            continue
        d = pv - baseline[e]
        if d < -tol:
            win += 1
        elif d > tol:
            loss += 1
        else:
            tie += 1
    return {"win": win, "tie": tie, "loss": loss}


def detection_curve(per_event: list[tuple[bool, float]],
                    grid: tuple[float, ...] = CURVE_GRID) -> list[float]:
    """Mean fault-detection rate across events as a function of budget fraction.

    ``per_event`` is a list of ``(detected, normalized_ttfr)`` pairs (one per event). Because each
    micro-corpus event has a single fault, detection is a unit step turning on at ``normalized_ttfr``;
    the curve at budget fraction ``f`` is the fraction of events already detected by ``f``. The result
    is non-decreasing in ``f`` and bounded in [0, 1].
    """
    n = len(per_event) or 1
    out = []
    for f in grid:
        hit = sum(1 for det, nt in per_event if det and nt <= f + 1e-12)
        out.append(round(hit / n, 6))
    return out


def aggregate_seeds(values: list[float]) -> dict[str, float | None]:
    """Median / min / max of a per-seed metric (e.g. random over many seeds), per reviewer #3."""
    if not values:
        return {"median": None, "min": None, "max": None}
    return {"median": round(statistics.median(values), 4),
            "min": round(min(values), 4), "max": round(max(values), 4)}


# --- Non-parametric effect sizes + bootstrap CIs (EMSE statistical-rigour norms) -----------
# Dependency-free implementations (no scipy): Cliff's delta and Vargha–Delaney A12 are the
# standard effect sizes for comparing randomized/algorithm outputs in software engineering.

def cliffs_delta(a: list[float], b: list[float]) -> float:
    """Cliff's delta in [-1, 1]: (#a>b - #a<b) / (|a|·|b|). >0 means a tends to exceed b."""
    if not a or not b:
        return 0.0
    gt = lt = 0
    for x in a:
        for y in b:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    return round((gt - lt) / (len(a) * len(b)), 4)


def cliffs_magnitude(d: float) -> str:
    """Romano et al. thresholds for |Cliff's delta|."""
    ad = abs(d)
    if ad < 0.147:
        return "negligible"
    if ad < 0.33:
        return "small"
    if ad < 0.474:
        return "medium"
    return "large"


def vargha_delaney_a12(a: list[float], b: list[float]) -> float:
    """Vargha–Delaney A12 in [0, 1] = P(a>b) + 0.5·P(a=b). 0.5 means no effect."""
    if not a or not b:
        return 0.5
    gt = eq = 0
    for x in a:
        for y in b:
            if x > y:
                gt += 1
            elif x == y:
                eq += 1
    return round((gt + 0.5 * eq) / (len(a) * len(b)), 4)


def bootstrap_ci(xs: list[float], n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 0) -> dict[str, float | None]:
    """Percentile bootstrap CI for the mean of xs (dependency-free)."""
    if not xs:
        return {"mean": None, "lo": None, "hi": None}
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(n_boot):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"mean": round(sum(xs) / n, 4), "lo": round(lo, 4), "hi": round(hi, 4)}
