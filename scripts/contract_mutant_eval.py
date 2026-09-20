#!/usr/bin/env python3
"""Contract/metadata-channel synthetic mutant family (B-1, PLAN_1B.md G1a).

Companion to channel_matched_eval.py's global-phase mutant family (6 phase offsets x 6 circuits).
Here the "offset" analogue is one of 6 PERMUTATION-VALID corruption modes applied to the transpiled
circuit's recorded `routing_permutation` metadata (leaving `initial_index_layout`/`final_index_layout`
and every actual gate untouched). Each mode produces a genuine permutation of range(n) (so the plain
"is this a permutation" contract check, C2, never fires) that no longer composes correctly with
initial_index_layout to produce final_index_layout (C3) -- the same shape of contract violation as the
two real, source-verified faults this channel is built on (#14603, #14919: valid-looking layout metadata
that does not compose/undo correctly). Because only the METADATA object is swapped and the compiled
circuit's actual instructions are never touched, the output-equivalence oracle stays blind by
construction on every mutant.

Checks run per (circuit, corruption mode): contract checker (C2/C3), metamorphic MR-1 (permutation-free
GHZ circuits only, same precondition as elsewhere in this study), and global-phase tracker (expected to
stay quiet -- confirms the mutation does not leak into a different channel). A clean-baseline run per
circuit (no corruption) gives the specificity denominator.

Run from repo root:  python scripts/contract_mutant_eval.py
Writes results/contract_mutant_eval.json.

NOTE: authored without a local Qiskit install available to the authoring session (no network egress
to PyPI from that sandbox) -- please run this once and skim the printed summary for sanity before
trusting the numbers in the paper; report back anything that looks off (e.g. a mode raising instead of
producing a clean violation) so the script can be fixed rather than the result quietly misreported.
"""
import contextlib, json, math, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.transpiler import CouplingMap

from cart.events.mutations import baseline_transpiler
from cart.oracles.semantic import check_semantic
from cart.oracles.contract_differ import check_contracts
from cart.oracles.metamorphic import check_permutation_consistency
from cart.oracles.global_phase import check_global_phase

BASIS = ["cx", "rz", "sx", "x"]


def circuits():
    out = []
    for n in (4, 5, 6):
        g = QuantumCircuit(n); g.h(0)
        for i in range(n - 1): g.cx(i, i + 1)
        out.append((f"ghz{n}", g, True))              # True => permutation-free, MR-1 applies
        q = QuantumCircuit(n); q.compose(QFT(n), inplace=True)
        out.append((f"qft{n}", q, False))              # QFT bit-reversal => MR-1 out of precondition
    return out


def cfg_for(n):
    return dict(coupling_map=CouplingMap.from_line(n), basis_gates=list(BASIS),
                optimization_level=3, seed_transpiler=1234)


def _swap(lst, i, j):
    lst = list(lst); lst[i], lst[j] = lst[j], lst[i]
    return lst


def _rotate(lst, k):
    n = len(lst); k %= n
    return lst[k:] + lst[:k]


# Six permutation-valid corruption modes -- the "offsets" for this channel. Each is a bijection of
# range(n), so C2 (valid-permutation) never fires; only C3 (composition) and MR-1 should.
CORRUPTIONS = {
    "swap_first_two":   lambda p: _swap(p, 0, 1),
    "swap_last_two":    lambda p: _swap(p, len(p) - 2, len(p) - 1),
    "rotate_left_1":    lambda p: _rotate(p, 1),
    "rotate_left_2":    lambda p: _rotate(p, 2),
    "reverse_all":      lambda p: list(reversed(p)),
    "swap_middle_pair": lambda p: _swap(p, len(p) // 2 - 1, len(p) // 2),
}


class _CorruptedLayout:
    """Delegates everything to the real layout except routing_permutation(), which returns a
    corrupted-but-still-valid permutation. initial_index_layout/final_index_layout pass through
    unchanged, so C2 never fires and the corruption is isolated to the composition/MR-1 checks."""

    def __init__(self, orig_layout, corrupted_routing):
        self._orig = orig_layout
        self._corrupted_routing = list(corrupted_routing)

    def initial_index_layout(self, *a, **k):
        return list(self._orig.initial_index_layout(*a, **k))

    def final_index_layout(self, *a, **k):
        return list(self._orig.final_index_layout(*a, **k))

    def routing_permutation(self, *a, **k):
        return list(self._corrupted_routing)

    def __getattr__(self, name):
        return getattr(self._orig, name)


@contextlib.contextmanager
def _patched_layout(circuit, replacement):
    """Temporarily override type(circuit).layout to return `replacement` for this one instance
    (by identity), delegating to the real property for every other instance. Needed because
    QuantumCircuit.layout has no setter in Qiskit 2.x, so plain attribute assignment is refused."""
    cls = type(circuit)
    orig = cls.layout

    def _getter(self):
        return replacement if self is circuit else orig.fget(self)

    cls.layout = property(_getter)
    try:
        yield
    finally:
        cls.layout = orig


def any_detect(d):
    return any(v is True for v in d.values())


def run_checks(orig, transpiled, cm, mr1_ok):
    r = {}
    try:
        r["contract"] = len(check_contracts(orig, transpiled, coupling_map=cm, basis_gates=BASIS)) > 0
    except Exception as e:
        r["contract"] = f"err:{type(e).__name__}"
    if mr1_ok:
        try:
            r["mr1"] = (check_permutation_consistency(orig, transpiled).holds is False)
        except Exception as e:
            r["mr1"] = f"err:{type(e).__name__}"
    else:
        r["mr1"] = None
    try:
        r["global_phase"] = (check_global_phase(orig, transpiled).equivalent is False)
    except Exception as e:
        r["global_phase"] = f"err:{type(e).__name__}"
    return r


def main():
    rows = []
    for cname, circ, mr1_ok in circuits():
        n = circ.num_qubits
        cm = CouplingMap.from_line(n)
        cfg = cfg_for(n)
        base_t = baseline_transpiler(cfg)(circ)
        sem_base = check_semantic(circ, base_t, coupling_map=cm, basis_gates=BASIS)

        # ---- clean baseline: specificity denominator ----
        clean = run_checks(circ, base_t, cm, mr1_ok)
        rows.append({"kind": "clean_baseline", "circuit": cname,
                     "output_blind": (sem_base.equivalent is True),
                     "any_matched_fired": any_detect(clean), "detail": clean})

        # ---- corruption modes: sensitivity ----
        layout = getattr(base_t, "layout", None)
        if layout is None or not callable(getattr(layout, "routing_permutation", None)):
            rows.append({"kind": "mutant", "circuit": cname, "error": "no routing_permutation on baseline"})
            continue
        try:
            orig_rp = list(layout.routing_permutation())
        except Exception as e:
            rows.append({"kind": "mutant", "circuit": cname, "error": f"routing_permutation raised {type(e).__name__}"})
            continue

        for mode, fn in CORRUPTIONS.items():
            corrupted_rp = fn(orig_rp)
            corrupted_layout = _CorruptedLayout(layout, corrupted_rp)
            # QuantumCircuit.layout is a read-only property in Qiskit 2.x (no setter), so the
            # corrupted metadata is substituted via a temporary class-level property override,
            # scoped to this one circuit instance by identity, rather than instance assignment.
            with _patched_layout(base_t, corrupted_layout):
                sem = check_semantic(circ, base_t, coupling_map=cm, basis_gates=BASIS)
                det = run_checks(circ, base_t, cm, mr1_ok)
            rows.append({"kind": "mutant", "circuit": cname, "mode": mode,
                         "output_blind": (sem.equivalent is True),
                         "any_matched_fired": any_detect(det), "detail": det,
                         "corrupted_routing_permutation": corrupted_rp, "original_routing_permutation": orig_rp})

    mutants = [r for r in rows if r["kind"] == "mutant" and "detail" in r]
    clean_rows = [r for r in rows if r["kind"] == "clean_baseline"]
    n_mut = len(mutants)
    n_hit = sum(1 for r in mutants if r["any_matched_fired"] is True)
    n_blind = sum(1 for r in mutants if r["output_blind"])
    n_clean_fp = sum(1 for r in clean_rows if r["any_matched_fired"] is True)
    n_spurious_gp = sum(1 for r in mutants if r["detail"].get("global_phase") is True)

    def wilson(k, n, z=1.96):
        if n == 0: return (0.0, 0.0)
        p = k / n; d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return (round(max(0, c - h), 3), round(min(1, c + h), 3))

    summary = {
        "mutant_runs": n_mut, "circuits": len(circuits()), "modes": len(CORRUPTIONS),
        "sensitivity_hits": n_hit, "sensitivity": round(n_hit / n_mut, 3) if n_mut else None,
        "sensitivity_ci95": wilson(n_hit, n_mut),
        "output_equivalence_blind_on_mutants": n_blind,
        "specificity_runs": len(clean_rows),
        "false_positives_on_clean_baseline": n_clean_fp,
        "specificity": round(1 - n_clean_fp / len(clean_rows), 3) if clean_rows else None,
        "specificity_ci95": wilson(len(clean_rows) - n_clean_fp, len(clean_rows)),
        "spurious_global_phase_firings_on_mutants": n_spurious_gp,
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "contract_mutant_eval.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, default=str))

    print("=" * 66)
    print("CONTRACT/METADATA-CHANNEL SYNTHETIC MUTANT FAMILY")
    print(f"{summary['circuits']} circuits x {summary['modes']} corruption modes = {n_mut} mutant runs")
    print(f"sensitivity: {n_hit}/{n_mut} = {summary['sensitivity']} (95% CI {summary['sensitivity_ci95']})")
    print(f"output-equivalence oracle blind on: {n_blind}/{n_mut} mutants")
    print(f"specificity: {len(clean_rows) - n_clean_fp}/{len(clean_rows)} = {summary['specificity']} "
          f"(95% CI {summary['specificity_ci95']})  [false positives: {n_clean_fp}]")
    print(f"spurious global-phase firings on mutants (should be 0): {n_spurious_gp}")
    errs = [r for r in rows if "error" in r]
    if errs:
        print(f"\n{len(errs)} row(s) errored -- inspect before trusting the summary:")
        for r in errs[:6]: print("  ", r)
    print("wrote results/contract_mutant_eval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
