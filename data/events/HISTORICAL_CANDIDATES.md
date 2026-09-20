# Historical Regression Candidates (Qiskit 2.x)

Real, documented transpiler regressions in the selected window (Qiskit 2.x), to be converted into
historical events. **These are leads, not finalized events.** Before an event is Phase-2-ready you
must confirm the exact *introducing* commit (the `candidate_sha`) and its parent (the
`baseline_sha`) from the Qiskit git history / the fixing PR, and build both from source
(`build_qiskit_event`). Until then the seed table carries `TBD-*` SHAs and validation runs in
non-ready mode.

Source basis: Qiskit 2.1 / 2.2 SDK release notes (see Sources). Confirm the precise issue/PR and
SHAs against the Qiskit repository.

| Seed event_id | Symptom | Reported group / fault_type | Stage | Present in → Fixed in |
|---|---|---|---|---|
| `hist-elide-permutations-mapping` | ElidePermutations did not update the qubit mapping with PermutationGates → **incorrect circuits** | Correctness / `semantic` | optimization | ≤ 2.1.x → 2.2.0 |
| `hist-routing-permutation-multilayout` | `TranspileLayout.routing_permutation` returned a wrong permutation after more than one pass set `final_layout` | Correctness / `semantic` | layout | ≤ 2.1.x → 2.2.0 |
| `hist-vf2layout-nondeterminism` | `VF2Layout` non-deterministic even with a fixed seed when active qubits had only single-qubit ops | Quality / `quality` | layout | 2.1.x → fixed in 2.1.x patch |
| `hist-vf2postlayout-noop` | `VF2PostLayout` added to optimization_level=3 but its output was never applied (runtime cost, no benefit) | Performance / `performance` | optimization | 2.1.0 → reverted in 2.1.x |

These give a correctness + quality + performance spread. The four seed **mutation** events
(`mut-*`) are all `quality` and supplement coverage per §1.4 (mutations fill gaps, do not replace
historical events). A genuine **functional** (crash) fault is not yet represented, add one from a
historical crash regression, or a crashing mutation, before finalizing.

## Finalization checklist (per historical event)
1. Find the fixing PR/issue in the Qiskit repo; identify the commit that *introduced* the bug.
2. `candidate_sha` = introducing commit; `baseline_sha` = its parent (last known-good).
3. `event_date` = candidate commit timestamp (§1.1). Update `split_group_id` = `baseline_sha[:12]`.
4. Assign a unique `event_environment_id`; build baseline+candidate via `build_qiskit_event`.
5. Re-run `cart events validate --require-ready` (must pass with real SHAs).

## Seed-split caveat
With the current dates, the four historical leads fall before 2026 and the four mutations on the
2.4.2 base fall in 2026-06, so a 2026-01-01 cutoff puts all historicals in train and all mutations
in test. **Finalize `configs/cutoff.yaml` only after the full dated event set exists**, so both
splits contain a historical/mutation mix.

## Sources
- [Qiskit SDK 2.2 release notes](https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/2.2)
- [Qiskit SDK 2.1 release notes](https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/2.1)
- [Qiskit releases](https://github.com/Qiskit/qiskit/releases)
