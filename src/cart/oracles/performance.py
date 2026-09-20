"""Performance screening (METHODOLOGY §2.5) — Stage 1 only, EXPLORATORY for the pilot.

Single-laptop timing is noisy; this stage only screens median slowdown against a pre-declared
threshold. Stage-2 confirmation (bootstrap CI / Hodges-Lehmann) is reserved for scale-up.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerfResult:
    suspected_regression: bool          # exploratory flag only
    median_baseline_s: float
    median_candidate_s: float
    slowdown_ratio: float               # (cand-base)/base
    threshold: float
    exploratory: bool = True
    details: dict[str, Any] = field(default_factory=dict)


def screen_performance(baseline_times: list[float], candidate_times: list[float],
                       slowdown_threshold: float = 0.20) -> PerfResult:
    mb = statistics.median(baseline_times)
    mc = statistics.median(candidate_times)
    ratio = (mc - mb) / mb if mb > 0 else 0.0
    return PerfResult(
        suspected_regression=ratio >= slowdown_threshold,
        median_baseline_s=mb, median_candidate_s=mc,
        slowdown_ratio=ratio, threshold=slowdown_threshold,
        details={"n_baseline": len(baseline_times), "n_candidate": len(candidate_times)},
    )
