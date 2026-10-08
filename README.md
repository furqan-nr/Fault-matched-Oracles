# Fault-Class-Matched Test Oracles for Output-Invisible Quantum Transpiler Faults

Reproducibility package for **"Fault-Class-Matched Test Oracles for Output-Invisible Quantum
Transpiler Faults"** (Nasir, Shah, Alam; prepared for submission to *ACM Transactions on
Quantum Computing*). This repository holds the oracle implementations, every
verification and evaluation script, the already-executed evidence each reported number traces to,
and the environment/build protocol needed to rebuild any of it from source.

- **Repository:** https://github.com/furqan-nr/Fault-matched-Oracles
- **Archive (DOI):** [10.5281/zenodo.23245090](https://doi.org/10.5281/zenodo.23245090)
- **License:** MIT (see `LICENSE`)

This is a **companion, independent artifact** to the empirical prevalence study behind it
("An Empirical Study of Equivalence-Invisible Bug Fixes in Quantum Transpilers", preprint
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
families built to each channel's own invariant, and on a native port of the global-phase mechanism
to pytket/tket.

## What's inside

- `src/cart/` — the shared oracle/harness library the scripts below import. This paper's own
  contribution is `src/cart/oracles/` (`contract_differ.py`, `metamorphic.py`, `global_phase.py`,
  `semantic.py` — the output-equivalence baseline the family is compared against) and
  `src/cart/events/mutations.py` (the mutation operators behind the synthetic mutant families).
  The rest of the package (`manifest/`, `labels/`, `features/`, `gates/`, `metrics/`, `selectors/`,
  `cli.py`) is shared harness infrastructure the scripts depend on at import time but that is not
  itself part of this paper's reported contribution.
- `scripts/` — every verification and evaluation script behind a reported number (26 files); see
  `REPRODUCE.md` for which ones you can re-run directly and which need a from-source Qiskit build.
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

    # Release-wheel retro-detection breadth study (pip-installs two Qiskit releases per fix, no compiler)
    python scripts/retro_detect_release.py

    # The nine real, from-source-verified faults themselves are the expensive tier: each needs two
    # from-source Qiskit builds (baseline + candidate). Their already-executed evidence is in
    # results/source_validation/ and results/sv-*/ and needs no rebuild to inspect; see REPRODUCE.md
    # for the full per-fault rebuild protocol using environment/setup/.

See `REPRODUCE.md` for the full protocol, expected output for each command, and exactly which
result file every reported number traces to. Citation metadata is in `CITATION.cff`.
