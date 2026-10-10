# Protocol 1B-H v2: Qiskit 2.x fault harvest for Paper 1B (not coded by 1A)

Written 2026-10-08. Status: DRAFT until committed and tagged `harvest-protocol-v2`. Supersedes v1, which used a pre-2.0 window and is withdrawn (section 7). Nothing below was decided
after reading any fix diff or PR page. The screen reads commit metadata, changed-file names, and a keyword
grep over the added lines of test files. No human has read any of those diffs.

## 1. Role and boundaries
- **Role.** These PRs form the *1B harvest*: extra real faults on which the oracle family of Paper 1B is evaluated.
- **No prevalence claim.** This harvest says nothing about how common output-invisible fixes are. That figure comes
  only from Paper 1A (19/68 = 28%, and 29/104). 1A's corpus, labels and files are not changed by this protocol.
- **Paper 2.** Every harvest PR is reserved for 1B and must not appear in Paper 2's corpus, tuning, or held-out
  data (`data_use_ledger.csv`, role `1B-harvest`). Paper 2's own events (11399, 13094, 14120, 14603, 14730, 14778, 14904, 14919, 14939, 15024, 16215, 16285) are on the exclusion list, and
  the ledger check shows harvest and Paper 2 sets are disjoint.
- **Not coded by 1A.** PRs that 1A coded or screened, the PRs already used in Paper 1B (Tables 4 and 4b), and Paper 2's reserved events
  (123 PR numbers in `exclusion_1A_union.csv`) are removed from the population. 69 of them fall inside the window.

## 2. Population (mechanical, frozen)
- **Source.** Commits on `main` (first-parent) of github.com/Qiskit/qiskit, squash-merged with a `(#N)` suffix.
- **Window.** Merged 2025-06-18 (Qiskit 2.1.0 release; the study window is the band 2.1 to latest, per RELEASE_WINDOW_DECISION.md) to 2026-10-08 (`main` at commit
  9f1a0b20a338eeafe05eb0f5f9449c4886e1c815). Earlier releases, including 2.0.x, are out of scope.
- **Screens, in order**
  - S0: not a backport, not in 1A's union.
  - S1: subject starts with "fix".
  - S2: touches `qiskit/transpiler/`, `crates/accelerate/` or `crates/transpiler/`.
  - S3: touches a file under `test/` (a regression test exists).
  - Harvest = S1 and S2 and S3 and (S4 or S5).
  - S4: the subject matches layout, permut, rout(e|ing), swap, phase, determinis, non-determin, ordering, reproducib, seed, virtual.
  - S5: added lines of changed test files match global_phase, final_layout, initial_layout, final_index_layout,
    initial_index_layout, virtual_permutation, routing_permutation, structurally_equal, non-determin, determinis, PYTHONHASHSEED.
- **Implementation.** `harvest_screen.py`. Output `harvest_population_frozen.csv`, sha256
  `80da826744a8e9bb5ae109319bd1b06d9212c8fb8f0432d5bd7a6799d41b830d` (18 rows pass S1 to S3; 4 pass the keyword rule).
- **Funnel.** 1111 commits, 2 backports, 69 excluded (1A, Paper 1B, Paper 2), 180 S1, 29 S2, 18 S3, 4 harvest (S4 = 3, S5 = 1).
- **Harvest set.** #15683, #16336, #16880, #16920. The other 14 rows that pass S1 to S3 are recorded as screened out and not attempted.
  The keyword rule is crude (for example, #15683 is a typo-fix PR matched by S5 and will be reported as out of scope), so recall is limited and is stated as a limitation.

## 3. Sizing disclosure
None for the final window: it was fixed by the study's 2.x scope, not by yield.

## 4. Attempt rule
All 4 harvest PRs are attempted, in ascending PR order. None is skipped or replaced, and every one is reported.

## 5. Reproduction, invisibility, channel, detection (fixed definitions)
- **Build.** Fix commit and its parent built from source (Python 3.11, Rust), as in Table 4b. Failure to build is an outcome ("not buildable").
- **Trigger.** Transcribed from the fix's own regression test. At most 2 trigger attempts per PR. The oracle code is not edited between attempts.
- **Reproduced.** The trigger distinguishes parent from fix on a recorded quantity (the regression test's own assertion).
- **Output-invisible.** On the parent, the output circuit is equivalent to the input modulo global phase
  (`check_semantic`) or identical to the fix's output. A crash or inequivalence counts as visible.
- **Channel.** By the property the regression test asserts: layout or permutation metadata gives contract/metadata;
  global phase gives phase; run-to-run or ordering stability gives determinism; anything else is out of scope.
- **Detection class, assigned by the oracle code tagged `v1.2.0`**
  - (a) detected by an unchanged generic component;
  - (b) detected by an existing fault-specific adapter mechanism;
  - (c) detected only by a check written after the fault was observed;
  - (d) not detected.
  Any new check is labelled post hoc.

## 6. Reporting
One table of all 4 with outcome, including not buildable, not reproduced, visible, and out of scope. A funnel from 1111 to the final
count. Detection shares over reproduced-invisible faults reported descriptively with an interval, and not as a prevalence or sensitivity estimate.

## 7. Deviations log
- 2026-10-09: v1 of this protocol used the window 2024-02-15 to 2025-01-15 (Qiskit 1.0 to 1.3). The study excludes pre-2.0 releases, so v1 was withdrawn
  before it was committed or any diff was read. Before withdrawal the author's assistant had seen the screen counts for three pre-2.0 windows
  (7, 5 and 35 rows at S1 to S3) and the subject lines of those PRs. No diff or PR page was read. None of those PRs is used.
- 2026-10-09 (before commit): the window start was moved from 2.0.0 (2025-03-31) to 2.1.0 (2025-06-18) to match RELEASE_WINDOW_DECISION.md. This removed #14186
  (merged 2025-04-07) from the harvest set. No diff of #14186 was read. The change was made on scope grounds, not on yield. A full census of the 18 rows that pass S1 to S3 is
  a pre-declared follow-up, to be decided only after the 4 harvest PRs are reported.

## 8. Outcome and run notes (appended 2026-10-09, after the protocol was tagged; sections 1 to 7 are unchanged)
- All 4 harvest PRs were attempted in ascending order. #15683 was not built (typo- and comment-only change; out of scope, not a defect fix).
  #16336, #16880 and #16920 were built from source (fix and parent) and each reproduced on its trigger (the regression test's own assertion).
  The probes (`probe_harvest.py`) and the comparison rules (`compare_harvest.py`) were not edited after the first build run.
- Channel and visibility under section 5: #16336 (seed value reaching the layout pass) is out of scope; #16880 (sign of a Pauli-product measurement) is output-visible and out of scope;
  #16920 (measured qubit after OptimizeSwapBeforeMeasure with a loose qubit) is output-visible and out of scope. No detection class (a to d) is assigned to any of the 4.
  For #16880 and #16920, `check_semantic` returns only a structural verdict (circuits contain measurements), so visibility was judged from the circuit's own classical outcome or signed Pauli.
- Supplementary, post hoc, not counted: for #16336 an environment-seed versus explicit `seed_transpiler` comparison separates fix from parent (fix 1234 = explicit 1234; parent equals explicit seed 1).
- Toolchain: the 1.89 Rust pin of the #16880 and #16920 commits could not fetch its clippy/rustfmt components on the author's machine; the builds were run with `RUSTUP_TOOLCHAIN=1.89`, which ignores `rust-toolchain.toml` (same compiler, no lint components). `build_event.ps1` was also patched so that a venv without an importable qiskit is not treated as built.
  Builds: #16336 2.5.0.dev0; #16880 and #16920 2.6.0.dev0.
- Census decision: the pre-declared follow-up census of the 14 other rows that pass S1 to S3 was not run. The four rows that passed the keyword rule (the channel filter) yielded nothing in scope, and the remaining 14 matched no channel keyword. The 14 are listed in the repository as screened out and not attempted. This is a deliberate non-run, not an omission, and it can be reversed by a later amendment.
