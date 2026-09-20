# Retro-detection feasibility — build-free vs from-source

Checked (2026-07-04) whether the mined output-invisible fixes can be retro-detected from pip WHEELS
(build-free) by diffing the release that shipped the bug against the release that shipped the fix.

**Result: none of the 6 sampled invisible-channel fixes are wheel-retro-detectable.** For each, the
fix commit AND its parent first appear in the SAME release (Qiskit fixes these fast, within one release
cycle), so the buggy state was never released:

| PR | channel | fix_release | parent_release | wheel-retro-detectable? |
|----|---------|-------------|----------------|--------------------------|
| 14956 | global_phase | 2.2.0 | 2.2.0 | no |
| 15040 | determinism | 2.3.0 | 2.3.0 | no |
| 15024 | contract_metadata | 2.3.0 | 2.3.0 | no |
| 16215 | global_phase | 2.5.0 | 2.5.0 | no |
| 16237 | determinism | 2.5.0 | 2.5.0 | no |
| 16201 | global_phase | 2.5.0 | 2.5.0 | no |

**Implication:** retro-detection of these fixes REQUIRES from-source builds of the parent (buggy) and
fix commits — i.e., it goes through `scripts/source_validate_mining.py` (P3), which needs the Rust
build. There is no build-free shortcut for within-release fixes. `scripts/retro_detect_release.py`
remains useful only for the subset of mined fixes (if any) where the bug PERSISTED across a release
boundary (parent_release < fix_release); none of the current invisible sample qualifies.

**Canonical trigger source:** each fix PR adds its own regression test (e.g. #16201 ->
test/python/transpiler/test_unroll_forloops.py, +37 lines). Extract the circuit from that added test
to author the exact bug-exercising trigger, rather than guessing.

## Addendum (2026-09-12): mechanism bug fixed, conclusion above unchanged

Separately from the release-boundary finding above, `scripts/retro_detect_release.py`'s `worker()` had
never forwarded a targeted unit's `--isolated-pass` requirement to `historical_worker.py` (unlike
`source_validate_mining.py`, which already threads `isolated=isolated` correctly) — so #14956's
pass-specific fault, masked by the full preset pipeline and only visible when `CommutativeCancellation`
runs in isolation, could never have been reproduced by this script even on the right wheels. Fixed:
`worker()` now accepts an `isolated` kwarg and appends `--isolated-pass <name>`; `retro_detect_targets.csv`
gained an `isolated_pass` column, with #14956's row wired to `trig-gp14956-cc-2pi`/`CommutativeCancellation`
(mirroring `source_validation_targets.csv`'s already-confirmed row) and a `wheel_bracketed=no` column
recording this note's finding for all six rows. This fix does not change the table above: the deeper
problem is that no pair of released wheels brackets any of these six bugs in the first place, regardless
of whether the isolated-pass flag is threaded through correctly. `Paper 1B/paper/build_1b.js` §6.6
reports both facts (mechanism fixed; release-wheel approach still structurally inapplicable to this
sample) as the honest B-10 finding.
