# The seven real tket output-invisible contract faults vs. the ported checker

Source: `data/mining_validation/tket_worksheet_R2.csv`, rows adjudicated
`manifestation_channel = contract_metadata`, `observable_by_output_oracle = no`, `in_scope_bugfix = yes`
(the same seven behind 1A's "7 of 21 = 33%" tket figure). They are mapped here to the invariant the
ported contract checker (`scripts/tket_contract_port.py`) enforces: the recorded CompilationUnit maps
(initial_map / final_map) must reconcile the routed circuit with the original up to a global phase.
This is a STATIC mapping (what clause each fault would exercise), not an executed from-source result —
replaying these needs building tket's C++ at each historical commit, which is out of scope. The
executed evidence in the paper is the synthetic contract-mutant demonstration the port runs.

| PR | tket commit | subject | why output-invisible | checker clause exercised |
|----|-------------|---------|----------------------|--------------------------|
| 2072 | 8077ff57b964 | GreedyPauliSimp ignores the implicit qubit permutation | pass dropped the circuit's implicit qubit permutation; applied output still correct | recorded permutation no longer matches the circuit's action -> map reconciliation fails |
| 1632 | 510d4a8d99cd | symbol sub doesn't preserve opgroup | opgroup annotation lost; compiled circuit correct | metadata-preservation clause (recorded annotation vs circuit) |
| 1441 | 5139818f59bc | FlattenRelabelRegistersPass mishandles register/wire metadata | register/wire bookkeeping wrong; output correct | register/wire-identity clause |
| 945 | fcf22dc660c6 | phase poly box custom registers | PhasePolyBox conversion mishandled custom-register qubit mapping | map (qubit-identity) reconciliation |
| 861 | 81f2869ecfee | flatten register should update classical expressions | classical-reference metadata not updated; applied circuit correct | metadata-preservation clause (classical refs) |
| 285 | 92fc286e6b2d | single-qubit labelling | placement labelling missed single-qubit-only qubits | initial placement (initial_map) validity/coverage |
| 146 | 61b2d7500ff0 | wire swap handling in phase poly box creation | implicit wire swap not tracked; output correct | recorded permutation vs circuit's wire swap -> reconciliation fails |

All seven share the structure the checker targets: a recorded piece of layout/permutation/register
metadata diverges from what the circuit actually does, while the executed output stays correct. PRs
2072 and 146 (implicit-permutation / wire-swap tracking) are the closest match to the exact invariant
the synthetic mutant corrupts (a transposed final-map entry).
