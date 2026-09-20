"""Property / layout (contract-metadata) oracle — retrospective track.

Black-box output-equivalence oracles cannot observe contract/metadata-channel faults. H1
(ElidePermutations, PR #14603) is the canonical case: the buggy pass corrupts the
``virtual_permutation_layout`` property while leaving the layout-applied output unitary correct, so
the exact-unitary oracle reports EQUIVALENT on the buggy build.

This oracle compares the transpiler LAYOUT CONTRACT recorded on the transpiled circuit between the
baseline (good) and candidate (buggy) builds. A divergence on the permutation/layout fields is the
H1 signal. It is a deliberate DEVIATION from the production output oracle and must live only in the
Secondary retrospective evaluation, never the Primary CI claim (see PROVENANCE_BACKLOG.md).

``extract_layout_props`` runs inside the per-event venv (needs the live ``TranspileLayout``);
``compare_layout_props`` is pure and unit-tested without Qiskit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Compared in priority order. ``virtual_permutation_layout`` is the field H1 corrupts; it may not be
# exposed identically across the 2.x band, so its extraction is best-effort and the robust,
# always-available contract fields are compared alongside it.
LAYOUT_FIELDS = (
    "virtual_permutation_layout",
    "routing_permutation",
    "final_index_layout",
    "initial_index_layout",
)


@dataclass
class PropertyOracleResult:
    strength: str                         # always "property"
    equivalent: bool | None               # True=identical contract; False=divergent (fault); None=no data
    divergent_fields: list[str]
    details: dict[str, Any] = field(default_factory=dict)


def _to_jsonable(v: Any) -> Any:
    """Best-effort conversion of a layout/permutation value to a stable, JSON-serialisable form."""
    if hasattr(v, "get_physical_bits"):  # qiskit Layout
        try:
            return sorted((int(p), int(getattr(q, "index", q)))
                          for p, q in v.get_physical_bits().items())
        except Exception:
            return str(v)
    if isinstance(v, dict):
        try:
            return sorted((str(k), str(val)) for k, val in v.items())
        except Exception:
            return str(v)
    try:
        return [int(x) for x in v]
    except (TypeError, ValueError):
        try:
            return list(v)
        except TypeError:
            return str(v)


def extract_layout_props(transpiled: Any) -> dict[str, Any]:
    """Pull the layout/permutation contract from a transpiled circuit. Call INSIDE the per-event
    venv (where the live ``TranspileLayout`` is available). Returns JSON-serialisable values."""
    props: dict[str, Any] = {}
    layout = getattr(transpiled, "layout", None)
    if layout is None:
        return props

    for name in ("final_index_layout", "initial_index_layout", "routing_permutation"):
        fn = getattr(layout, name, None)
        if callable(fn):
            try:
                props[name] = list(fn())
            except Exception as exc:  # signature differences across the 2.x band
                props[name] = f"__error__:{type(exc).__name__}"

    # H1-specific, best-effort: the corrupted property may live on the layout or the circuit object.
    for obj in (layout, transpiled):
        vpl = getattr(obj, "virtual_permutation_layout", None)
        if vpl is not None:
            props["virtual_permutation_layout"] = _to_jsonable(vpl)
            break
    return props


def compare_layout_props(baseline_props: dict[str, Any],
                         candidate_props: dict[str, Any]) -> PropertyOracleResult:
    """Pure comparison (no Qiskit). Any divergence on a compared field means the candidate's layout
    contract differs from the baseline's, i.e. a property-channel fault is detected."""
    compared = [f for f in LAYOUT_FIELDS if f in baseline_props or f in candidate_props]
    if not compared:
        return PropertyOracleResult("property", None, [],
                                    {"reason": "no layout contract captured on either build"})
    divergent = [f for f in compared if baseline_props.get(f) != candidate_props.get(f)]
    return PropertyOracleResult(
        "property", len(divergent) == 0, divergent,
        {"compared_fields": compared,
         "baseline": {f: baseline_props.get(f) for f in compared},
         "candidate": {f: candidate_props.get(f) for f in compared}},
    )
