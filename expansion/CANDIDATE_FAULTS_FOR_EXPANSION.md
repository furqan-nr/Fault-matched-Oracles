> **Status (2026-10-08).** The four Tier A candidates below were attempted from source with the scripts in this
> folder. All four reproduce as output-invisible; only #15943 is detected by an unchanged oracle (see
> `results_expansion/expansion_summary.json` and manuscript Table 4b). The expectation written below that each
> generic oracle would fire was therefore only partly borne out. The Table 4 headline counts are unchanged.

# Candidate real faults for expanding Paper 1B Table 4

Source: 1A mining corpus (`Post BASR/data/mining_validation/labels_final_68.csv`,
`pr_characterization_raw_104.csv`, `source_validation_targets.csv`,
`label_source_validation.csv`, `tket_provisional_coded.csv`). Read-only; nothing in
those files was changed. This note just cross-references them against Table 4.

Adjudicated output-invisible fixes in the 68-PR corpus: 19 (= 27.9%).
Already in Table 4 (9): #14603 #14919 #15024 (contract); #14956 #16201 #16215 (phase);
#14730 #16237 #15040 (determinism).
Remaining identified-but-not-reproduced (10 Qiskit) + the tket set below.

## Tier A — cheap wins (Qiskit, on-channel, a GENERIC oracle already exists; same
## from-source protocol used for the nine; no new mechanism needed)

| PR | Channel | Fix (title) | Detector that should fire | Fix size |
|----|---------|-------------|---------------------------|----------|
| #13945 | contract/metadata | Fix composing virtual permutation layouts for ElidePermutations and StarPreRouting | contract checker / MR-1 (same area as #14603) | 4 files, +125/-2 |
| #13833 | contract/metadata | Fix tracking of routing permutation in Sabre with disjoint backends | contract checker / MR-1 | 3 files, +43/-0 |
| #15943 | global phase | Fix TemplateOptimization dropping the global_phase on substitution | global-phase tracker (same as #14956) | 5 files, +106/-2 |
| #14763 | determinism | Fix non-determinism in CommutativeCancellation | determinism runner (same as #14730/#16237) | 5 files, +52/-22 |

Each maps onto a mechanism already built and validated. Work per fault: build the two
Qiskit revisions from source, rebuild the trigger from the fix's own regression test
(per 4.7), run the existing oracle. Adding these would take Table 4 from 9 to ~13.
Merged Qiskit fixes carry a regression test by convention; confirm by reading each PR.

## Tier B — medium (need a targeted adapter or already have one inconclusive attempt;
## SHAs already recorded in source_validation_targets.csv)

| PR | Channel | Note |
|----|---------|------|
| #14939 | contract/metadata | Generic trigger already came back blind; needs an isolated-pass differential like #14603. fix 6fb956f / parent 2577bc1 already recorded. |
| #16402 | global phase | One trigger (2pi accumulation) returned 0.0 on both builds = inconclusive, not disconfirming. Needs a different gate/repeat count from its regression test. (This is the "tenth candidate" already named in 6.1.) |
| #14938 | contract/metadata | "VF2 layout allocation with idle qubits" — idle/ancilla qubits make the contract checker skip K1/K2, so this may be an ABSTENTION/limitation case rather than a clean detection. Useful as a boundary test. |

## Tier C — poor fit for the current oracle family (invisible per 1A coding, but the
## channel is not one of the three the oracles target; would need a new mechanism)

| PR | Channel-as-coded | Why it does not map |
|----|------------------|---------------------|
| #13910 | contract/metadata | "Propagate DAGCircuit.name in ApplyLayout" — a name-propagation bug, not a layout-permutation invariant the checker tests. |
| #14041 | contract/metadata | "deepcopy/pickle of DAGCircuit variable IO nodes" — serialization correctness, outside the three channels. |
| #15137 | contract/metadata | "HLS for custom gate calibrations" — calibration metadata, outside the three channels. |

These three support 1A's prevalence story but not 1B's detection claim; better left
as "fault class exists, outside current oracle scope" than forced into Table 4.

## Tier D — cross-SDK real faults (tket): highest value, highest cost
Replaying even one from source upgrades RQ4 from synthetic to REAL cross-SDK, but needs
building tket's C++ at historical commits. Identified output-invisible tket fixes
(contract-dominant), closest to the ported contract checker:
- tket #2072 — greedy pauli simp ignores the qubit permutation of the original circuit
- tket #146  — fix wire swap handling in phase poly box
- tket #1632 — symbol sub doesn't preserve opgroup
- tket #1441 — FlattenRelabelRegistersPass
(#2072 and #146 are already named in 6.5 / docs/TKET_CONTRACT_FAULT_MAP.md as the
closest match to the invariant the synthetic tket mutant corrupts.)

## Recommendation
Pre-submission or first-revision: add the four Tier-A faults (same protocol, existing
oracles). Hold Tier B and one Tier-D tket replay as the substantive answer if a reviewer
presses on evaluation scale. Leave Tier C out and let 1A carry those.
