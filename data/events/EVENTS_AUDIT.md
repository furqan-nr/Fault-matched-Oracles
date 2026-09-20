# Events Audit, Pilot Ledger (reconciled)

Audited event ledger for the micro corpus, reconciled to the approved decisions. Machine-readable:
`data/events/events.csv` and `data/events/events.json`. Provenance backlog:
`data/events/PROVENANCE_BACKLOG.md`. METHODOLOGY.md is unchanged.

Release window: Qiskit 2.x (band 2.1 → latest stable; anchor `2.4.2`). All historical candidates
are in-window dev commits.

## Cohorts (never pooled in headline results)
- **`fix_boundary`** (`event_kind=fix_boundary_differential`, `pair_orientation=reverse_fix_boundary`):
  `baseline = fix commit` (good), `candidate = buggy parent`, `event_date = fix commit timestamp`,
  `change_metadata_sha = fix commit`. Framed as **fault-revealing test prioritization at fix
  boundaries**, NOT as true forward regression-inducing changes.
- **`forward_regression`** (`event_kind=forward_regression`, `pair_orientation=forward`): `baseline =
  last-good parent`, `candidate = introducing commit`.
- **`mutation`** (`event_kind=controlled_mutation`): semantics defined by the operator.

## Verification status (honest)
I cannot build Qiskit from source or run Benchpress here (no Rust; that is your laptop). Historical
events therefore remain **`blocked`**, SHAs and evidence are pinned, but each is only `verified`
once its exact source SHAs build locally AND the fault triggers through the planned test/oracle path.
**H4 also requires local reproduction before counting as verified.** Mutations are `verified`
in-sandbox (Phase 2).

## Ledger (14 events: 5 historical + 9 mutation)

*EMSE expansion:* the mutation cohort was expanded from 4 to 9 operators (and the corpus width-capped
at ≤ 8 qubits, 32 units) to give the selection comparison statistical footing. See also the
repository-mining observability dataset `data/observability_mining.csv` (26 real transpiler bug-fixes
classified by manifestation channel; ≈ 38% fall in output-invisible channels).

### fix_boundary cohort
| event_id | fault_type | candidate (buggy) → baseline (good) | evidence | status |
|---|---|---|---|---|
| hist-elide-permutations-mapping | semantic | `7c3890da` → `96fda188` | PR #14603 | **rejected** (production-unobservable) |
| hist-final-layout-composition | semantic | `14df5941` → `dfcc5c6c` | PR #14919 | blocked |
| hist-vf2layout-determinism-1q | quality | `056c6413` → `d33ef533` | PR #14730 | blocked |
| hist-vf2layout-panic-1p0 | **functional** | `f0fae6f3` → `0b2cdf2b` | PR #16285 | blocked |

### forward_regression cohort
| event_id | fault_type | baseline (good) → candidate (buggy, introduced) | evidence | status |
|---|---|---|---|---|
| hist-vf2postlayout-noop | performance | `a18e1516` → `a8d23667` | PR #14120 / issue #14867 | blocked |

### mutation cohort (verified, Phase 2)
`disable_optimization_loop`, `drop_vf2_post_layout`, `downgrade_routing`, `insert_redundant_cx_pair`,
`drop_optimization_stage`, `force_opt_level_1`, `force_opt_level_0`, `downgrade_layout_trivial`,
`insert_redundant_x_pair` on the 2.4.2 base (`5a1cf315`); all semantics-preserving **quality** faults
(9 operators). 8 of 9 are detected by the black-box oracle on the ≤8-qubit corpus; only
`drop_vf2_post_layout` is not.

## Functional event (decision 2)
**Chosen:** historical crash **#16285** "Fix panic on `1.0` error in VF2Layout" (functional,
fix_boundary). Time-boxed search yielded this in-window crash fix; preferred over a mutation.
**Documented fallback** (used only if #16285 does not reproduce locally): the
`incomplete_basis_translation` mutation operator, drops the 1q target basis (`['cx']` only) so the
translation stage cannot express 1q gates and transpilation fails with a natural `TranspilerError`
(no artificial raise; verified to raise in-sandbox). Affected units: any with single-qubit gates
(all pilot families). Oracle evidence: the engine records the natural exception as `functional_fail`.

## Fault-type coverage
| Reported group | fault_type | historical | mutation |
|---|---|---|---|
| Correctness | semantic | H1, H2 |, |
| Correctness | functional | H5 (#16285) | fallback only |
| Quality | quality | H3 | 9 mutations |
| Performance | performance | H4 |, |

All four fault types covered. Total **14 events** (5 historical + 9 mutation).

## Temporal split (illustrative, cutoff 2026-01-01)
train: H1, H2, H3, H4 (2025). test: H5 (2026-05-27), 9 mutations (2026-06). Group-level; no group
straddles. Finalize `configs/cutoff.yaml` after historical verification.

## Local validation results (so far)
- **H1 (ElidePermutations), REJECTED (production-unobservable).** Built buggy+fixed from source;
  the targeted trigger returned `pass` on the buggy candidate through the full preset PM + semantic
  oracle (backends `none` and `line`, opt3). The fault corrupts the `virtual_permutation_layout`
  *property*, not the layout-applied output unitary, so the black-box production oracle cannot see
  it. Per the production-pipeline rule it is **not counted**; moved to the backlog for a possible
  property-level / isolated-pass oracle in a clearly-labelled retrospective track (deviation).
  This is a deliberate rigor outcome: faults the selector could not observe in real CI are not
  credited.
- **H4 (VF2PostLayout no-op), BLOCKED (perf below threshold).** Built buggy+fixed; all `pass` on
  4 small units AND on a 16-unit retry (incl. large opt-3 circuits). The no-op overhead stays under
  the 20% Stage-1 screen; single-sample CPU timing is under-powered vs the 3-run median in §2.5.
  Exploratory; deferred to Phase 6 (3-run median + controlled hardware).
- **H3 (VF2Layout determinism), BLOCKED (not reproduced).** Built buggy+fixed. A first determinism
  oracle (op-counts+depth) passed; a **stronger fingerprint oracle** (gate order + qubit indices +
  `final_layout`) was then implemented and the buggy build **still passed**. PR #14730's
  non-determinism is tied to a **noisy `Target`** (`GenericBackendV2` noise scoring) that our
  coupling-map-only backend does not exercise. Retrospective trigger needs a noisy Target.
- **H2 (final_layout), H5 (functional #16285):** not built/run; H2 expected to share H1's
  layout-property masking, H5's panic is input-specific.

### Honest synthesis
Across the historical set, the pilot's production black-box oracles on a laptop verify **0** events
so far: H1 rejected (property fault, not in the unitary), H3 blocked (oracle too coarse), H4 blocked
(perf under-powered). The **mutation cohort (9 quality faults) remains the verified backbone.** This
is itself a credible pilot finding: black-box semantic/perf oracles under-detect real
internal/property/timing regressions, which motivates (a) the targeted-trigger + retrospective
design and (b) the Phase-6 scale-up with stronger oracles and controlled-hardware timing. Per the
§5.4 claim-scope rule (0 verified forward-regression events), results stay strictly pilot-scoped.

### A bug found & fixed during validation
The H4 `--unit-limit 16` retry crashed: the semantic oracle built a full 2^18 operator (512 GiB) for
an 18-qubit circuit. Fixed: the exact operator oracle is now capped at ≤12 qubits; larger circuits
fall to structural (memory-safe). The 13–22q sampled-SV tier is a documented deferred limitation.

## External-review fixes (R1–R4) applied
- **R1:** cohorts explicit (`event_kind`/`pair_orientation`/`evaluation_cohort`/`change_metadata_sha`);
  forward / fix_boundary / mutation reported separately. H1–H3 + H5 are `fix_boundary` (not forward);
  H4 is the only `forward_regression`. Fix-boundary results are NOT framed as CI prediction.
- **R2:** targeted triggers tagged `test_provenance=extracted_from_fix`, `available_before_candidate=false`
  → excluded from the **Primary CI evaluation**; used only in the **Secondary retrospective** evaluation.
- **R3:** `configs/stage_map.yaml` frozen (`frozen: true`) before held-out; training-only refinement.
- **R4:** with only **one** verified forward_regression possible (H4), no headline temporal-generalization
  claim is permitted, results are **pilot evidence**, per event, per cohort (METHODOLOGY §5.4).

## Status of work
- `events.json` reconciled with real SHAs + cohort fields (historical remain skipped by the
  in-process Phase-2 engine because `candidate_sha != baseline_sha`).
- A **minimal per-event from-source venv runner** is implemented to validate one fix-boundary event,
  H4, and the functional event on your laptop (`cart historical-run`). Full Phase-2 collection and
  Phase 6 are NOT started.
