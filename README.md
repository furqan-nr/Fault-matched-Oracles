# Fault-matched oracles for output-invisible quantum transpiler faults: reproducibility package

Reproducibility package for **"Detecting quantum transpiler faults that corrupt layout metadata, global phase or reproducibility while the compiled output stays correct"**
(Nasir, Shah, Alam; prepared for submission to *Scientific Reports*; this is release v1.2.1). This repository holds the oracle implementations, every
verification and evaluation script, the already-executed evidence each reported number traces to,
and the environment/build protocol needed to rebuild any of it from source.

- **Repository:** https://github.com/furqan-nr/Fault-matched-Oracles
- **Archive (DOI):** [10.5281/zenodo.23245090](https://doi.org/10.5281/zenodo.23245090) (release v1.1.1). The DOI of release v1.2.1 is added here once the release is published on Zenodo.
- **License:** MIT (see `LICENSE`)

This is a **companion, independent artifact** to the empirical prevalence study behind it
("What output-equivalence oracles miss: an empirical study of equivalence-invisible bug fixes in quantum transpilers", preprint
arXiv:2609.13839, repository https://github.com/furqan-nr/quantum-observability). That companion
paper is cited here once, for the invisible-fault rate its mining study measures; none of its own
mining/coding data or scripts are duplicated in this repository, and none of this repository's
oracle code or fault-verification evidence is duplicated in that one.

Quantum compilers such as Qiskit's transpiler are usually checked with an **output-equivalence
oracle**: compare the compiled circuit's execution behaviour against a reference, modulo global
phase. The companion study above shows that check is systematically incomplete: roughly 28% of
merged Qiskit transpiler bug-fixes repair a fault that corrupts layout/permutation metadata, drops
a global phase, or breaks run-to-run determinism while the executed output stays correct — invisible
to an output-equivalence oracle by construction. This repository is the solution side: a family of
**fault-class-matched, layout-aware, width-tiered oracles** — a layout/permutation contract checker
and a contract-level metamorphic relation (MR-1) for the metadata channel, a global-phase tracker
for the phase channel, and a determinism runner for the reproducibility channel — verified from
source on nine real, merged Qiskit transpiler regressions (three per channel), on synthetic mutant
families built to each channel's own invariant, and on native pytket/tket ports of the global-phase tracker and the contract checker (synthetic faults
only).

## What's inside

- `src/cart/` — the oracle library and the minimal harness the scripts below import. This paper's own
  contribution is `src/cart/oracles/` (`contract_differ.py`, `metamorphic.py`, `global_phase.py`,
  `semantic.py` — the output-equivalence baseline the family is compared against, plus the
  determinism and layout-property helpers) and `src/cart/events/mutations.py` (the mutation operators
  behind the synthetic mutant families). `metrics/curves.py` supplies the effect-size helpers used by the H4 performance check; `events/`, `labels/` and `manifest/` hold the historical-event
  table, the per-event from-source runner and the circuit manifests the scripts import at run time;
  `cli.py` exposes `events` and `historical-run`.
- `scripts/` — every verification and evaluation script behind a reported number, including the
  clean-compilation phase check (`phase_spec_check.py`), the downstream-use simulations
  (`consequence_demo.py`) and the figure script (`make_figures.py`); see `REPRODUCE.md` for which ones
  you can re-run directly and which need a from-source Qiskit build.
- `expansion/` — the post hoc replication on further faults (build and probe scripts, saved results).
- `harvest/` — the prospective harvest of later fixes: frozen protocol, the mechanical screen and its
  frozen output, probe scripts and saved results.
- `figures/` — Figures 1 and 2 of the manuscript (PNG and vector PDF) as drawn by `scripts/make_figures.py`.
- `docs/` — the static mapping of the tket real faults to the contract checker.
- `results/` — the already-executed evidence: `results/source_validation/` and the `results/sv-*/`
  directories (from-source build outputs and register/phase/DAG diffs for the nine real faults plus
  three investigated-but-not-promoted candidates), `results/bisect-*/` (every attempted automated
  bisection — none converged, which is why the paper reports these faults as manually source-traced,
  not bisected), `results/phase*/` and `results/analyze-*/` (the H4 performance-regression staged
  protocol), `results/retro_detect/` (the release-wheel breadth study), `results/contract_differ/`
  (the 675-configuration false-positive sweep), and the `*_eval.json` summaries for the mutant
  families, held-out oracle evaluation, cost/scaling measurement, and tket transfer.
- `environment/` — `ENV.md` (locked build decisions), `requirements.*` (the harness lockfile),
  `setup/` (build/setup scripts and instructions for rebuilding any from-source Qiskit event).
- `data/events/` — the H1–H5 historical-event ledger (`events.csv`/`.json`) with its audit trail
  and provenance backlog, cited for the paper's historical-events table.
- `data/mining_validation/` — the specific mining-study files this paper's own claims depend on:
  `label_source_validation.csv` and `source_validation_targets.csv` (which candidate faults were
  source-checked and why), `retro_detect_targets.csv`/`RETRO_DETECT_NOTES.md` (the release-wheel
  breadth study's target list and the structural reason it found no bracketing release),
  `tket_worksheet_R1.csv`/`_R2.csv` and `cross_sdk_adjudication.csv` (the 7/21 = 33% tket
  replication-rate figure cited for the transfer result). This is a curated subset, not the full
  mining corpus — the companion prevalence study's own repository is the authoritative source for
  the mining/coding evidence itself.

## Reproduce the headline results

    # Contract/metadata + global-phase mutant families and false-positive sweep (anchor Qiskit, no build)
    python scripts/channel_matched_eval.py
    python scripts/heldout_oracle_eval.py
    python scripts/contract_mutant_eval.py
    python scripts/determinism_mutant_eval.py
    python scripts/contract_differ_sweep.py --widths 4,6,8 --opts 1,2,3 --seeds 25

    # Cost/scaling measurement across the family's own width tiers (anchor Qiskit, no build)
    python scripts/cost_scaling_eval.py

    # tket cross-SDK transfer of the global-phase mechanism (needs pytket installed)
    python scripts/tket_global_phase_port.py
    python scripts/tket_contract_port.py

    # Clean-compilation phase check (2,400 correct compilations) and downstream-use simulations
    python scripts/phase_spec_check.py
    python scripts/consequence_demo.py

    # Figures 1 and 2 (numpy and matplotlib only; reads results/consequence_demo.json and results/cost_scaling_eval.json)
    python scripts/make_figures.py

    # Release-wheel retro-detection breadth study (pip-installs two Qiskit releases per fix, no compiler)
    python scripts/retro_detect_release.py

    # The nine real, from-source-verified faults themselves are the expensive tier: each needs two
    # from-source Qiskit builds (baseline + candidate). Their already-executed evidence is in
    # results/source_validation/ and results/sv-*/ and needs no rebuild to inspect; see REPRODUCE.md
    # for the full per-fault rebuild protocol using environment/setup/.

See `REPRODUCE.md` for the full protocol, expected output for each command, and exactly which
result file every reported number traces to. Citation metadata is in `CITATION.cff`.
