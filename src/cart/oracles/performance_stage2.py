"""Stage-2 performance confirmation (METHODOLOGY §2.5, scale-up).

Stage 1 (``oracles/performance.py``) screens a single-sample median slowdown against a fixed
threshold and is exploratory. Stage 2 *confirms* a suspected performance regression from MULTI-RUN
timings using a robust, non-parametric protocol consistent with the effect-size reporting used
elsewhere in the paper: a median slowdown ratio, Cliff's delta and Vargha-Delaney A12 over the
timing samples, and a percentile bootstrap CI for the slowdown ratio.

A regression is *confirmed* only when ALL of the following hold:
  1. the median slowdown ratio meets a pre-declared threshold,
  2. the bootstrap CI of the slowdown ratio excludes zero, and
  3. the Cliff's-delta magnitude is at least a pre-declared floor.

Pre-declare (1)-(3) in ``configs/thresholds.yaml`` under ``performance.stage2`` BEFORE you measure
(leakage-safe); never tune them on the held-out timings. This module has no Qiskit dependency and is
unit-tested without a build.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any

from cart.metrics.curves import cliffs_delta, cliffs_magnitude, vargha_delaney_a12

_MAG_RANK = {"negligible": 0, "small": 1, "medium": 2, "large": 3}


@dataclass
class PerfStage2Result:
    suspected_regression: bool
    median_baseline_s: float | None
    median_candidate_s: float | None
    slowdown_ratio: float                 # (median_cand - median_base) / median_base
    ratio_ci_lo: float | None             # percentile bootstrap CI of the slowdown ratio
    ratio_ci_hi: float | None
    cliffs_delta: float                   # candidate vs baseline timings (>0 = candidate slower)
    cliffs_magnitude: str
    a12_candidate_slower: float           # P(a candidate run is slower than a baseline run)
    threshold: float
    min_magnitude: str
    n_baseline: int
    n_candidate: int
    decision_reason: str
    details: dict[str, Any] = field(default_factory=dict)


def _median_ratio(base: list[float], cand: list[float]) -> float:
    mb = statistics.median(base)
    mc = statistics.median(cand)
    return (mc - mb) / mb if mb > 0 else 0.0


def _bootstrap_ratio_ci(base: list[float], cand: list[float], n_boot: int, alpha: float,
                        seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    nb, nc = len(base), len(cand)
    ratios: list[float] = []
    for _ in range(n_boot):
        rb = [base[rng.randrange(nb)] for _ in range(nb)]
        rc = [cand[rng.randrange(nc)] for _ in range(nc)]
        ratios.append(_median_ratio(rb, rc))
    ratios.sort()
    lo = ratios[int((alpha / 2) * n_boot)]
    hi = ratios[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return lo, hi


def confirm_performance(
    baseline_times: list[float], candidate_times: list[float], *,
    slowdown_threshold: float = 0.20, min_magnitude: str = "small",
    n_boot: int = 2000, alpha: float = 0.05, seed: int = 1234,
) -> PerfStage2Result:
    """Confirm (or not) a performance regression from multi-run baseline/candidate timings."""
    base = [float(x) for x in baseline_times if x is not None and float(x) > 0]
    cand = [float(x) for x in candidate_times if x is not None and float(x) > 0]

    if len(base) < 2 or len(cand) < 2:
        return PerfStage2Result(
            suspected_regression=False,
            median_baseline_s=(statistics.median(base) if base else None),
            median_candidate_s=(statistics.median(cand) if cand else None),
            slowdown_ratio=0.0, ratio_ci_lo=None, ratio_ci_hi=None,
            cliffs_delta=0.0, cliffs_magnitude="negligible", a12_candidate_slower=0.5,
            threshold=slowdown_threshold, min_magnitude=min_magnitude,
            n_baseline=len(base), n_candidate=len(cand),
            decision_reason="insufficient_samples (need >= 2 timed runs per build)",
        )

    mb, mc = statistics.median(base), statistics.median(cand)
    ratio = (mc - mb) / mb if mb > 0 else 0.0
    d = cliffs_delta(cand, base)
    mag = cliffs_magnitude(d)
    a12 = vargha_delaney_a12(cand, base)
    lo, hi = _bootstrap_ratio_ci(base, cand, n_boot, alpha, seed)

    thr_ok = ratio >= slowdown_threshold
    ci_excludes_zero = lo > 0
    mag_ok = _MAG_RANK.get(mag, 0) >= _MAG_RANK.get(min_magnitude, 1)
    suspected = bool(thr_ok and ci_excludes_zero and mag_ok)

    if suspected:
        reason = "confirmed (slowdown >= threshold, CI excludes 0, effect >= floor)"
    else:
        fails = []
        if not thr_ok:
            fails.append(f"slowdown {ratio:.3f} < threshold {slowdown_threshold:.3f}")
        if not ci_excludes_zero:
            fails.append(f"bootstrap CI [{lo:.3f}, {hi:.3f}] includes 0")
        if not mag_ok:
            fails.append(f"effect '{mag}' < floor '{min_magnitude}'")
        reason = "not confirmed: " + "; ".join(fails)

    return PerfStage2Result(
        suspected_regression=suspected,
        median_baseline_s=round(mb, 6), median_candidate_s=round(mc, 6),
        slowdown_ratio=round(ratio, 4), ratio_ci_lo=round(lo, 4), ratio_ci_hi=round(hi, 4),
        cliffs_delta=d, cliffs_magnitude=mag, a12_candidate_slower=a12,
        threshold=slowdown_threshold, min_magnitude=min_magnitude,
        n_baseline=len(base), n_candidate=len(cand), decision_reason=reason,
        details={"n_bootstrap": n_boot, "alpha": alpha, "seed": seed},
    )
