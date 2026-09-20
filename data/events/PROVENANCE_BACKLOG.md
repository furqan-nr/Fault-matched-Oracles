# Provenance Backlog, true introducing-commit tracing (post-pilot)

The fix-boundary events (H1–H3, H5) use `baseline = fix commit`, `candidate = buggy parent`
(`reverse_fix_boundary`). For the pilot this is accepted and kept in a separate cohort. After the
pilot, the most promising of these should be upgraded to **true forward regressions** by tracing the
commit that *introduced* the fault via `git bisect` / `git blame`, then setting
`baseline = introducing_commit^` (last good) and `candidate = introducing_commit`.

## Observability backlog (rejected-for-pilot, retrospective track)
- **H1 (ElidePermutations, PR #14603), REJECTED as production-unobservable.** Local from-source
  validation: the targeted trigger returns `pass` on the buggy build through the full preset PM +
  semantic (unitary) oracle, because the fault corrupts the `virtual_permutation_layout` *property*
  rather than the layout-applied output unitary. To use H1 retrospectively, add a **property-level
  oracle** (compare `TranspileLayout` / `routing_permutation`) or an **isolated-pass** harness
  (`PassManager([ElidePermutations()])` as in the PR test), both are deviations from the
  production transpile+oracle pipeline and require explicit approval, and would live only in the
  Secondary retrospective evaluation (never the Primary CI claim).

## Prioritized candidates for tracing (true introducing commit)
1. **H1, ElidePermutations mapping (PR #14603, semantic).** Highest value: a clear correctness
   regression with a deterministic oracle. Trace the commit that introduced the PermutationGate
   mishandling in `qiskit/transpiler/passes/optimization/elide_permutations`.
   - Suggested: `git log --follow -p -- qiskit/transpiler/passes/optimization/elide_permutations*`
     and `git bisect` between the PermutationGate-support commit and the parent of `96fda188`.
2. **H3, VF2Layout non-determinism with 1q gates (PR #14730, quality).** Second priority: a
   reproducibility fault useful for a determinism case study. Trace via `git blame` on the seed/edge
   handling in `vf2_layout` touched by the fix.

## Procedure (per candidate, post-pilot)
1. Identify the fix PR's changed lines; `git blame` them at the parent to find the prior logic.
2. `git bisect start <buggy_parent> <last-known-good-release-tag>` with a scripted reproduction as
   the bisect test, to find the introducing commit `I`.
3. Record `baseline = I^`, `candidate = I`, `event_date = I` timestamp, `pair_orientation = forward`,
   `evaluation_cohort = forward_regression`; move the event out of the fix-boundary cohort.
4. Re-run the per-event runner to confirm the fault reproduces in the forward orientation.

H4 (#14120) is already a true forward regression and needs no tracing.
