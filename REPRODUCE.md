# Reproducibility package

This archive accompanies the manuscript **"Detecting quantum transpiler faults that corrupt layout metadata, global phase or reproducibility while the compiled output stays correct"**
(Nasir, Shah, Alam; prepared for submission to *Scientific Reports*; this is release v1.2.1).

- Repository: https://github.com/furqan-nr/Fault-matched-Oracles
- Archive (DOI): [10.5281/zenodo.23245090](https://doi.org/10.5281/zenodo.23245090) (release v1.1.1). The DOI of release v1.2.1 is added here once the release is published on Zenodo.
- License: MIT (see `LICENSE`)

This repository is the reproduction artifact only; the manuscript text is maintained separately,
and its two figures are redrawn here by `scripts/make_figures.py`. It is independent of, and does not duplicate, the companion prevalence study's own
repository (https://github.com/furqan-nr/quantum-observability), which this paper cites once for
its measured invisible-fault rate.

## What is here

```
src/cart/oracles/     this paper's oracle implementations (contract_differ, metamorphic,
                       global_phase, semantic) and the mutation operators in
                       src/cart/events/mutations.py; the rest of src/cart/ is shared
                       harness infrastructure the scripts import at run time
scripts/               verification/evaluation entry points and the figure script (see below)
results/               already-executed evidence every reported number traces to
environment/           build/setup protocol and locked harness requirements
expansion/ harvest/    post hoc replication and prospective harvest (scripts, protocol, saved results)
figures/               Figures 1 and 2 (PNG and vector PDF) as drawn by scripts/make_figures.py
docs/                  static tket real-fault mapping
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

## 1. Mutant-family evaluations (SI Table S5) — anchor Qiskit, no build, minutes to run

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

## 3. Cost and scaling measurement (SI Table S6) — anchor Qiskit, no build

```bash
python scripts/cost_scaling_eval.py     # writes results/cost_scaling_eval.json
```

Expected: the contract checker's cost stays essentially flat in circuit width (metadata/list-level
check only), the global-phase tracker is comparably cheap within its own exact tier, and MR-1 is
measurably the most expensive oracle in the family within the exact (n <= 12) tier because it
composes an appended-permutation operator the same way the output-equivalence baseline does, plus
one more gate. Thread-pinning (`RAYON_NUM_THREADS=1`, `OMP_NUM_THREADS=1`) matters for reproducing
the exact timings; see the script's own docstring.

## 4. tket cross-SDK transfer (SI Table S7) — needs `pip install pytket`, anchor Qiskit otherwise

```bash
python scripts/tket_global_phase_port.py     # writes results/tket_global_phase_port.json
```

Expected (already saved in `results/tket_global_phase_port.json`): sensitivity 1.00 (36/36
synthetic phase mutants detected and output-blind) and specificity 1.00 (6/6 clean runs silent, 0
false positives), every recovered phase matching its injected offset to double-precision accuracy —
the same GHZ/QFT family and phase offsets used on the Qiskit side, re-derived against tket's own
`CompilationUnit.initial_map`/`final_map` rather than transliterated. This is a synthetic-mutant
replication of the global-phase mechanism only. The contract-checker port is `scripts/tket_contract_port.py`
(62/62 transposition mutants detected, 6/6 clean compilations silent; `results/tket_contract_port.json`).
Neither port replays any of the seven real tket faults the companion prevalence study identifies
(static mapping in `docs/TKET_CONTRACT_FAULT_MAP.md`).

## 5. Release-wheel retro-detection breadth study — pip-installs two Qiskit releases, no compiler

```bash
python scripts/retro_detect_release.py     # writes into results/retro_detect/
```

Expected: `retro_detected=False` for all six targeted fixes. `data/mining_validation/RETRO_DETECT_NOTES.md`
documents why this is a structural inapplicability rather than a mechanism failure — every mined
fix in the current sample lands its buggy-parent and fix commit inside the same Qiskit release, so
no pair of released wheels ever brackets the bug. The already-saved evidence is in
`results/retro_detect/`.

## 6. The nine real, from-source-verified faults (Table 2 and SI Table S4) — the expensive tier

Each of the nine faults (three per channel: contract/metadata `#14603, #14919, #15024`; global
phase `#14956, #16201, #16215`; determinism `#14730, #16237, #15040`) was verified by building the
buggy and fixed Qiskit revisions from source into throwaway venvs and running the matching
`verify_*.py` script, whose trigger is derived from the fix's own regression test (SI Section S4.7,
"trigger derivation"):

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

## Additional scripts: cost across circuit families, held-out specificity, tket contract port
- `python scripts/cost_scaling_eval_v2.py`   # cost across GHZ, QFT, random (anchor env) -> results/cost_scaling_eval_v2.json
- `python scripts/heldout_oracle_eval.py`    # independent-operator (non-circular) specificity (anchor env) -> results/heldout_oracle_eval.json
- `python scripts/tket_contract_port.py`     # contract checker ported to tket, synthetic mutant (pytket venv) -> results/tket_contract_port.json
# real-fault mapping (static, non-executed): docs/TKET_CONTRACT_FAULT_MAP.md
- `python scripts/determinism_eval_v2.py`   # determinism runner on #14730 with the stronger functional fingerprint (SI S4.6); `determinism_eval.py` is the earlier version, kept for the record -> results/determinism_eval*.json
- `python scripts/diag_determinism_qft4.py`   # shows the swapped pair in the qft4 determinism mutant is disjoint and unitary-preserving (SI mutant populations)
- `PYTHONPATH=src python scripts/repro_fixedseed_nondeterminism.py`   # minimal reproducer of fixed-seed layout-metadata variation (SI S4.6); compare Qiskit 2.4.2 and 2.5.x

## Table / claim to script map (Scientific Reports manuscript, v1.2.1)

Table and section numbers refer to the main text and to the Supplementary Information (SI) of the manuscript.

| Manuscript item | Script(s) | Output | Environment |
|---|---|---|---|
| Table 1 and SI S0, prevalence evidence | none here: measured in the companion prevalence study (https://github.com/furqan-nr/quantum-observability); the source-label validation it cites is in `data/mining_validation/label_source_validation.csv` | n/a | n/a |
| Table 2 and SI Table S4, nine historical faults | section 6 above (per-fault verifiers, e.g. `verify_h1_isolated.py`, `verify_15024_contract.py`, `verify_16237.py`, `determinism_eval_v2.py`) | `results/source_validation/`, `results/sv-*/`, `results/verify_*.json` | from-source builds |
| Table 3 and SI Tables S4b, S4c, post hoc replication and harvest | `expansion/` (see section 7 below) and `harvest/` (`harvest_screen.py`, `probe_harvest.py`, `run_harvest.ps1`) | `expansion/results_expansion/`, `harvest/results_harvest/`, `harvest/harvest_population_frozen.csv` | from-source builds |
| Table 4, mutant families (36 + 36 mutants, determinism 3/3) | `contract_mutant_eval.py`, `channel_matched_eval.py`, `determinism_mutant_eval_v2.py` | `results/*.json` | anchor Qiskit 2.4.2 |
| Table 4, held-out specificity (54 calls) | `heldout_oracle_eval.py` | `results/heldout_oracle_eval.json` | anchor Qiskit |
| Table 4, 675-configuration sweep | `contract_differ_sweep.py` | `results/contract_differ/` | anchor Qiskit |
| Table 4, adversarial checks (5 cases) | `adversarial_validation_bundle.py` | `results/adversarial_validation_bundle.json` | anchor Qiskit |
| Table 4, clean compilations (phase), 2,400 + 12, and SI S10.1-S10.2 | `phase_spec_check.py` | `results/phase_spec_check.json` | anchor Qiskit 2.4.2 |
| SI S4.2, composition-order probe | `composition_order_probe.py` | `results/composition_order_probe.json` (2.4.2), `results/composition_order_probe_qiskit2.5.2.json` | anchor Qiskit / 2.5.2 |
| Results, simulated consequences (phase estimation, readout) and SI S10.3 | `consequence_demo.py` | `results/consequence_demo.json` | anchor Qiskit 2.4.2 |
| Figure 2 and SI Table S6, cost (GHZ) and QFT/random confirmation | `cost_scaling_eval.py`, `cost_scaling_eval_v2.py`; the figure by `make_figures.py` | `results/cost_scaling_eval*.json`, `figures/fig2_cost.png`, `figures/fig2_cost.pdf` | anchor Qiskit; absolute ms are machine-dependent, ordering is the claim |
| Table 5 and SI Table S7, second SDK | `tket_global_phase_port.py`, `tket_contract_port.py` | `results/tket_*.json` | pytket 2.18.1 venv |
| tket real-fault mapping (static) | `docs/TKET_CONTRACT_FAULT_MAP.md` | n/a | n/a |
| Figure 1 (three-stage overview with the simulated consequences) | `make_figures.py` (reads `results/consequence_demo.json`) | `figures/fig1_channels.png`, `figures/fig1_channels.pdf` | numpy, matplotlib |

Clean-run check (2026-10-08, Linux, Python 3.10, qiskit 2.4.2, numpy 2.2.6): `contract_mutant_eval.py`
(36/36, 6/6), `channel_matched_eval.py` (36/36 phase, 15 clean calls), `heldout_oracle_eval.py` (0/54, 6/6),
`composition_order_probe.py` and `adversarial_validation_bundle.py` (all five cases pass) reproduce the
reported counts. The pinned `environment/requirements.lock` requires Python 3.11 (numpy 2.4.x); the
check above used the anchor Qiskit wheel on Python 3.10 and is not a run of that lock.

## 7. Post hoc replication (SI Table S4b) and prospective harvest (SI Table S4c) - from-source builds, Windows PowerShell

Added in v1.2.0 (post hoc replication) and v1.2.1 (harvest). The nine faults of Table 2 are untouched, and the oracle code is identical between v1.2.0 and v1.2.1. Both need Python 3.11, git and a Rust toolchain.

**Post hoc replication (SI Table S4b).** `expansion/` holds the build and probe scripts and the saved results for four candidate PRs (#13945, #13833, #15943, #14763). The paper reports three of them; #13833 was merged before the Qiskit 2.1 window and is excluded from Table 3 and SI Table S4b (its results are kept for completeness).

```powershell
cd expansion
powershell -ExecutionPolicy Bypass -File .\resolve_shas.ps1     # clones Qiskit once, resolves fix/parent SHAs
powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1       # builds fix+parent per PR, runs probe.py, prints verdicts
```

Saved evidence: `expansion/results_expansion/pr<N>/{fix,bug}.json` and `expansion_summary.json`. Only #15943 is detected by an unchanged oracle component; #14763 is detected by the DAG structural-equality mechanism already used as the #15040 adapter; #13945 is detected only by a check written after the fault was observed (see `probe.py` and the manuscript).

**Prospective harvest (SI Table S4c).** `harvest/` holds protocol 1B-H v2 (`PROTOCOL_1B_HARVEST.md`), the mechanical screen (`harvest_screen.py`) and its frozen output (`harvest_population_frozen.csv`, sha256 in the adjacent file), the build and probe scripts, and the saved results for the four harvested PRs (#15683, #16336, #16880, #16920). `RUN_HARVEST.md` gives the commands. The builds reuse `expansion/build_event.ps1` and the Qiskit clone in `expansion/_qiskit`.

```powershell
cd harvest
powershell -ExecutionPolicy Bypass -File .\run_harvest.ps1
```

Saved evidence: `harvest/results_harvest/pr<N>/{fix,bug}.json` and `harvest_summary.json`. All three built PRs reproduce on their triggers and none falls in the three channels as an output-invisible fault; #15683 is a typo-only change and was not built. Section 8 of the protocol records the run notes, including the Rust toolchain workaround.

## 8. Clean-compilation phase check and downstream-use simulations - anchor Qiskit, no build, minutes to run

Added in v1.2.1. Both scripts use the anchor Qiskit wheel (2.4.2) and the oracle code of `src/cart/oracles/` unchanged.

```
python scripts/phase_spec_check.py        # -> results/phase_spec_check.json
python scripts/consequence_demo.py        # -> results/consequence_demo.json
```

- `phase_spec_check.py` compiles 2,400 correct random circuits (3-6 qubits, five input global phases of which four are nonzero, four basis settings, three topologies, optimization levels 0-3), plus 12 circuits of 13-14 qubits for the sampled tier, and runs the global-phase tracker; it also injects 36 phase offsets as a negative control. Reported in the manuscript's Table 4 and Supplementary Section S10.1-S10.2.
- `consequence_demo.py` runs two statevector simulations with injected discrepancies of the size seen in two historical faults (0.3 rad for #16215, pi/7 rad for #16201): six-qubit phase estimation through a compiled, controlled gate, and readout through a recorded final layout with two entries transposed. The phase-estimation estimate is the most likely discrete outcome k/64 of the counting register; the continuous phase is 0.25 + offset/(2 pi), and both are recorded in the JSON. These simulations do not run the buggy builds and use no hardware. Reported in the Results subsection "Simulated consequences for phase estimation and readout" and Supplementary Section S10.3.

## 9. Figures - numpy and matplotlib only, seconds to run

```
python -m pip install numpy matplotlib   # drawn with matplotlib 3.10; not part of the pinned harness lock
python scripts/make_figures.py        # -> figures/fig1_channels.{png,pdf}, figures/fig2_cost.{png,pdf}
```

Both figures are drawn by code from stored result files, with no pasted images: Figure 1 reads `results/consequence_demo.json` (and stops with an error if its closed-form phase-estimation distribution disagrees with the probabilities stored there), and Figure 2 reads `results/cost_scaling_eval.json`. The PNG is 300 dpi and the PDF is vector. Sans-serif lettering uses Arial if installed and otherwise Liberation Sans or DejaVu Sans, so pixels can differ slightly between machines while content and layout are the same.
