# Reproducibility package

This archive accompanies the manuscript **"Fault-Class-Matched Test Oracles for Output-Invisible
Quantum Transpiler Faults"** (Nasir, Shah, Alam; prepared for submission to *ACM Transactions on
Quantum Computing*).

- Repository: https://github.com/furqan-nr/Fault-matched-Oracles
- Archive (DOI): [10.5281/zenodo.23241990](https://doi.org/10.5281/zenodo.23241990)
- License: MIT (see `LICENSE`)

This repository is the reproduction artifact only; the manuscript and its figures are maintained
separately. It is independent of, and does not duplicate, the companion prevalence study's own
repository (https://github.com/furqan-nr/quantum-observability), which this paper cites once for
its measured invisible-fault rate.

## What is here

```
src/cart/oracles/     this paper's oracle implementations (contract_differ, metamorphic,
                       global_phase, semantic) and the mutation operators in
                       src/cart/events/mutations.py; the rest of src/cart/ is shared
                       harness infrastructure the scripts import at run time
scripts/               26 verification/evaluation entry points (see below)
results/               already-executed evidence every reported number traces to
environment/           build/setup protocol and locked harness requirements
data/events/           H1-H5 historical-event ledger
data/mining_validation/ curated mining-study files this paper's own claims cite
```

## Requirements

Python 3.11 for the from-source-build tier (matches the harness lock); Qiskit 2.x (anchor build
2.4.2) is enough for every script marked "anchor Qiskit" below. No package install of this
repository itself is needed — every script inserts `src/` onto `sys.path` at the top and runs
directly from the repository root, e.g. `python scripts/channel_matched_eval.py`. `pytket` is
needed only for the tket transfer script. A Rust toolchain and the from-source build protocol in
`environment/setup/` are needed only if you want to rebuild one of the nine real faults yourself
rather than read its already-saved evidence.

## 1. Mutant-family evaluations (Table 5) — anchor Qiskit, no build, minutes to run

```bash
python scripts/channel_matched_eval.py      # writes results/channel_matched_eval.json
python scripts/heldout_oracle_eval.py       # writes results/heldout_oracle_eval.json
python scripts/contract_mutant_eval.py      # writes results/contract_mutant_eval.json
python scripts/determinism_mutant_eval.py   # writes results/determinism_mutant_eval.json
python scripts/determinism_mutant_eval_v2.py   # v2 stronger func fingerprint (layout-normalized unitary mod global phase); writes results/determinism_mutant_eval_v2.json
#   Fingerprint note (v1.1.1): the functional fingerprint now (i) uses a tolerance-stable global-phase pivot
#   (first entry whose magnitude exceeds half the maximum, instead of argmax, which flipped between
#   equal-magnitude entries of QFT unitaries) and (ii) compares each run's unitary with a reference compiled
#   before mutation via Operator.equiv. Expected: qft4/5/6 raw_distinct=2, func_distinct=1; ghz4/5/6 no-op; controls raw-stable.
```

Expected (already saved in the `results/*.json` files above): the contract/metadata and
global-phase mutant families both reach 1.00 sensitivity and 1.00 specificity across their mutant
population; `heldout_oracle_eval.json` records zero false positives on 54 clean-baseline oracle
calls for the contract checker and the global-phase tracker, and zero on 27 for MR-1, with the
6/6 synthetic global-phase mutants all output-blind and all detected. `determinism_mutant_eval.json`
reports the determinism mutation as constructible on 3 of 6 test circuits (the QFT family; GHZ has
no inherent qubit permutation for the mutation to disturb), all 3 detected while 6/6 clean controls
stay quiet — this is the source of the paper's reported 95% CI 0.44-1.00 at n=3: the wide interval
is a direct consequence of only three circuits being constructible, not an observed failure.

## 2. False-positive sweep (contract/metadata channel) — anchor Qiskit, no build

```bash
python scripts/contract_differ_sweep.py --widths 4,6,8 --opts 1,2,3 --seeds 25
python scripts/contract_differ_sweep.py --self-test   # proves the differ is not trivially blind
```

Expected: a clean sweep across the requested (width, optimization level, coupling map, seed)
configurations with zero contract violations on a released Qiskit — the already-saved evidence for
the full 675-configuration sweep reported in the paper is in `results/contract_differ/`.

## 3. Cost and scaling measurement (Table 6) — anchor Qiskit, no build

```bash
python scripts/cost_scaling_eval.py     # writes results/cost_scaling_eval.json
```

Expected: the contract checker's cost stays essentially flat in circuit width (metadata/list-level
check only), the global-phase tracker is comparably cheap within its own exact tier, and MR-1 is
measurably the most expensive oracle in the family within the exact (n <= 12) tier because it
composes an appended-permutation operator the same way the output-equivalence baseline does, plus
one more gate. Thread-pinning (`RAYON_NUM_THREADS=1`, `OMP_NUM_THREADS=1`) matters for reproducing
the exact timings; see the script's own docstring.

## 4. tket cross-SDK transfer (RQ4) — needs `pip install pytket`, anchor Qiskit otherwise

```bash
python scripts/tket_global_phase_port.py     # writes results/tket_global_phase_port.json
```

Expected (already saved in `results/tket_global_phase_port.json`): sensitivity 1.00 (36/36
synthetic phase mutants detected and output-blind) and specificity 1.00 (6/6 clean runs silent, 0
false positives), every recovered phase matching its injected offset to double-precision accuracy —
the same GHZ/QFT family and phase offsets used on the Qiskit side, re-derived against tket's own
`CompilationUnit.initial_map`/`final_map` rather than transliterated. This is a synthetic-mutant
replication of the global-phase mechanism only; it does not replay any of the seven real tket faults
the companion prevalence study identifies, and it is not the contract/metadata channel that study
reports as tket's actually-dominant one.

## 5. Release-wheel retro-detection breadth study — pip-installs two Qiskit releases, no compiler

```bash
python scripts/retro_detect_release.py     # writes into results/retro_detect/
```

Expected: `retro_detected=False` for all six targeted fixes. `data/mining_validation/RETRO_DETECT_NOTES.md`
documents why this is a structural inapplicability rather than a mechanism failure — every mined
fix in the current sample lands its buggy-parent and fix commit inside the same Qiskit release, so
no pair of released wheels ever brackets the bug. The already-saved evidence is in
`results/retro_detect/`.

## 6. The nine real, from-source-verified faults (Table 4) — the expensive tier

Each of the nine faults (three per channel: contract/metadata `#14603, #14919, #15024`; global
phase `#14956, #16201, #16215`; determinism `#14730, #16237, #15040`) was verified by building the
buggy and fixed Qiskit revisions from source into throwaway venvs and running the matching
`verify_*.py` script, whose trigger is derived from the fix's own regression test (§4.7 of the
manuscript's "trigger-derivation lesson"):

```
scripts/verify_h1_isolated.py        scripts/verify_h1_property.py       scripts/verify_14919_routing.py
scripts/verify_h4_perf.py            scripts/verify_16201.py             scripts/verify_16237.py
scripts/verify_n4_global_phase.py    scripts/verify_15024_contract.py    scripts/verify_15040_dag_order.py
scripts/verify_16215_router_phase.py scripts/verify_16402_cc_phase.py    scripts/verify_16215_forward.py
```

(`verify_16215_forward.py` is the earlier, superseded generic-trigger script for #16215, kept for
the trigger-derivation narrative — it is a QFT-based probe that would very likely have missed the
fault; `verify_16215_router_phase.py` is the fix-test-derived script that actually found it.
`verify_16402_cc_phase.py` is included for transparency: its own from-source result was negative
— global phase 0.0 on both builds with the tested basis/rep count — so #16402 is discussed in the
manuscript as an open, not-yet-promoted candidate, not one of the nine.)

Rebuilding any of these from scratch needs the full environment protocol in
`environment/setup/SETUP.md` (Python 3.11, a Rust toolchain, and `environment/setup/build_qiskit_event.sh
<tag> <event_id>` per revision you build) and the two-build (`--baseline-python` / `--candidate-python`)
interface each `verify_*.py` script documents in its own header. This is genuinely expensive (each
fault needs two from-source Qiskit builds) and is not required to check the reported numbers: every
one of the nine faults' results is already saved as JSON under `results/source_validation/` and the
per-fault `results/sv-*/` directories (e.g. `results/sv-15024-fixboundary-v2/contract_register_15024-20260805T122704Z.json`
for #15024), and `results/bisect-*/` documents every automated-bisection attempt on these faults —
none converged, which is why the paper reports them as manually source-traced rather than bisected.

`scripts/bisect_regression.py`, `scripts/add_forward_event.py`, `scripts/validate_ledger.py`, and
`scripts/source_validate_mining.py` are the pipeline utilities used to produce `data/events/` and
`results/source_validation/` in the first place; they are included for transparency and are not
needed to check an already-reported number.

## H4 performance-regression protocol

`results/phase0-*/`, `results/phase3-*/`, `results/phase5-*/`, and `results/analyze-*/` are the
staged (9-repeats-per-unit, 2000-sample bootstrap CI) protocol runs behind the H4 performance-event
row in the historical-events table (`data/events/events.csv`/`.json`); `scripts/verify_h4_perf.py`
is the corresponding verifier.

## Notes

- Every number reported in the manuscript traces to a file in `results/`, `data/events/`, or
  `data/mining_validation/` in this archive; none is re-derived from data outside it.
- Scripts that need a from-source Qiskit build hardcode the specific fix/parent commit SHAs they
  verify in their own header — see each script's docstring before rerunning it.

## Review-response strengthener scripts (B2–B4, 2026-10-07)
- `python scripts/cost_scaling_eval_v2.py`   # B4: cost across GHZ, QFT, random (anchor env) -> results/cost_scaling_eval_v2.json
- `python scripts/heldout_oracle_eval.py`    # B2: independent-operator (non-circular) specificity (anchor env) -> results/heldout_oracle_eval.json
- `python scripts/tket_contract_port.py`     # B3: contract checker ported to tket, synthetic mutant (pytket venv) -> results/tket_contract_port.json
# B3 real-fault mapping (static, non-executed): docs/TKET_CONTRACT_FAULT_MAP.md

## Table / claim to script map (manuscript revision of 2026-10-08)

| Manuscript item | Script(s) | Output | Environment |
|---|---|---|---|
| Table 4, nine real faults (Level 1 / Level 3) | section 6 above (per-fault verifiers, e.g. `verify_h1_isolated.py`, `verify_15024_contract.py`, `verify_16237.py`, `determinism_eval_v2.py`) | `results/` per fault | from-source builds |
| Table 5, mutant families | `contract_mutant_eval.py`, `channel_matched_eval.py`, `determinism_mutant_eval_v2.py` | `results/*.json` | anchor Qiskit 2.4.2 |
| Section 6.3, held-out specificity (54 calls) | `heldout_oracle_eval.py` | `results/heldout_oracle_eval.json` | anchor Qiskit |
| Section 6.3, adversarial checks (5 cases) | `adversarial_validation_bundle.py` | `results/adversarial_validation_bundle.json` | anchor Qiskit |
| Section 4.2, composition-order probe | `composition_order_probe.py` | `results/composition_order_probe.json` (2.4.2), `results/composition_order_probe_qiskit2.5.2.json` | anchor Qiskit / 2.5.2 |
| Table 6, cost (GHZ) and QFT/random confirmation | `cost_scaling_eval.py`, `cost_scaling_eval_v2.py` | `results/cost_scaling_eval*.json` | anchor Qiskit; absolute ms are machine-dependent, ordering is the claim |
| Table 7, cross-SDK | `tket_global_phase_port.py`, `tket_contract_port.py` | `results/tket_*.json` | pytket 2.18.1 venv |
| tket real-fault mapping (static) | `docs/TKET_CONTRACT_FAULT_MAP.md` | n/a | n/a |

Clean-run check (2026-10-08, Linux, Python 3.10, qiskit 2.4.2, numpy 2.2.6): `contract_mutant_eval.py`
(36/36, 6/6), `channel_matched_eval.py` (36/36 phase, 15 clean calls), `heldout_oracle_eval.py` (0/54, 6/6),
`composition_order_probe.py` and `adversarial_validation_bundle.py` (all five cases pass) reproduce the
reported counts. The pinned `environment/requirements.lock` requires Python 3.11 (numpy 2.4.x); the
check above used the anchor Qiskit wheel on Python 3.10 and is not a run of that lock.
