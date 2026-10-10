Harvest folder (Paper 1B). Files: PROTOCOL_1B_HARVEST.md (rules), harvest_screen.py (the screen), harvest_population_frozen.csv
(+ .sha256), exclusion_1A_union.csv (PRs 1A already coded), data_use_ledger.csv (one role per PR; harvest PRs are barred from Paper 2; window = Qiskit 2.1.0 to main 2026-10-08).
Re-run: python harvest_screen.py --repo <Qiskit clone> --out harvest_population_frozen.csv  (needs a full or blobless clone of Qiskit/qiskit).

Provenance. Protocol 1B-H v2 was committed in the author's working repository (commit 863fa662, tag `harvest-protocol-v2`) before any fix diff was read. This directory is a copy. Results are in `results_harvest/` (see section 8 of the protocol). The oracle code used is identical to tag v1.2.0 of this repository.
