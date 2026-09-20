# N1 finding — fixed-seed transpilation is non-deterministic in layout metadata (Qiskit 2.5.0)

**Found automatically** by the N1 contract differ (`scripts/contract_differ_sweep.py`) via the MR-4
metadata-idempotence check: 2 violations in a 216-config corpus sweep, both on ring coupling maps.

## What
With a **fixed `seed_transpiler`**, repeated `transpile()` of the *same* circuit yields **different
recorded layout metadata** (`initial_index_layout`, `final_index_layout`, `routing_permutation`).

Minimal reproducer (`scripts/repro_fixedseed_nondeterminism.py`): a 4-qubit random circuit on a
4-qubit ring at optimization_level=3, `seed_transpiler=1234`, gives 2 distinct `final_index_layout`
values over 20 identical calls (e.g. `[0,2,3,1]` vs `[0,3,2,1]`).

## Why it matters (observability)
The compiled circuit remains correct **modulo layout permutation**, so a black-box output-equivalence
oracle is BLIND to this. Only a metadata/contract oracle (the determinism + contract channels this
paper studies) detects it. It is exactly an output-invisible fault of the kind the mining study
counts, now demonstrated live on stock Qiskit by the N1 oracle.

## Characterization
- **Not a thread race:** persists with `RAYON_NUM_THREADS=1` (2 distinct layouts over 8 runs).
- Intermittent within a single process (fixed `PYTHONHASHSEED`), so it is an uncontrolled RNG source
  or an address-/iteration-order-dependent set inside a layout/routing pass, not covered by
  `seed_transpiler`.
- Observed at opt levels 1 and 3, widths 4 and 8, ring topology.

## Status / next steps (triage before any upstream claim)
1. Confirm it is **previously unreported** — search the Qiskit issue tracker for fixed-seed / VF2 /
   Sabre / ring non-determinism before calling it novel.
2. Reduce to the smallest pass (likely VF2Layout/VF2PostLayout or SabreSwap) with an isolated repro.
3. If unreported, file upstream (this is P4: developer-facing validation) with the minimal reproducer.

Even if it is a known limitation, N1 **auto-detected a real output-invisible contract violation on a
released Qiskit**, which is the "we built an oracle that finds real bugs" result for the paper.

## Triage update — root cause isolated

Forcing any explicit `layout_method` (trivial / dense / sabre) makes the result fully deterministic
(1 layout over 15 runs); only the DEFAULT layout path varies. The default path runs **VF2Layout** as a
perfect-mapping finder with a **call/time budget** (`vf2_call_limit`, `vf2_max_trials`); its winning
mapping is wall-clock/iteration-order dependent, so with multiple perfect layouts it picks different
ones across identical fixed-seed calls.

**Honest assessment:** this is most likely **documented VF2Layout time-bounded behavior**, not a novel
bug. N1 correctly and automatically flagged a genuine output-invisible determinism artifact — good
evidence the oracle works — but it does NOT (yet) constitute a "previously unknown, maintainer-confirmed"
bug. Do not report upstream as new without first checking whether the VF2 time-budget nondeterminism is
already known (it likely is).

**Implication for the paper path (task #6):** this find strengthens "the oracle detects real
output-invisible issues" but is not the novel-bug win that would decisively justify the Option-B
flagship split. To pursue Option B, run a LARGER / adversarial sweep and/or retro-detect on the mined
buggy builds; otherwise keep the scope-matched framing.

## Adversarial probe (decision-relevant)

With `layout_method=sabre` + `routing_method=sabre` fixed (removing the known VF2 time-budget
nondeterminism), an adversarial sweep of 243 configs — random + structured circuits (QFT, GHZ-like,
explicit SWAP-permutation), widths 4/6/8, line/ring/heavy-hex-like maps, opt 1/2/3 — produced
**0 contract violations**. So on current Qiskit 2.5.0 the differ is well-calibrated (zero false
positives) and finds no novel contract/metadata bug; the sole find is the known VF2 layout
nondeterminism. A novel-bug result (the decisive Option-B lever) would require retro-detection on the
mined BUGGY builds (needs the from-source builds) or a much larger/again-adversarial corpus.

## Version-specificity (observed 2026-07-04) — possible regression lead

The sweep behaves differently across releases:
- **Qiskit 2.5.0** (sandbox): default-layout sweep flags the fixed-seed layout-metadata nondeterminism.
- **Qiskit 2.4.2** (user anchor): the same 216-config default-layout sweep reports **0 violations**.

If this holds under more seeds, the VF2 fixed-seed layout nondeterminism is a **determinism-channel
regression introduced between 2.4.2 and 2.5.0** — which would be a genuinely novel (output-invisible)
bug and the decisive Option-B lever. Before claiming that: (1) re-run both versions with many more seeds
(e.g. --seeds 100) to rule out a seed-coverage artifact; (2) if 2.4.2 stays clean and 2.5.0 reproduces,
bisect 2.4.2->2.5.0 with the determinism oracle to find the introducing commit; (3) check the Qiskit
tracker before reporting. The manuscript now pins the finding to 2.5.0 and notes 2.4.2 is clean.

## CORRECTION (seeds=100, 2026-07-04) — supersedes the "version-specific" note above

At --seeds 100 (1800 configs each), the VF2 idempotence nondeterminism appears on BOTH releases:
Qiskit 2.4.2 = 24 idempotence violations, Qiskit 2.5.0 = 27. So it is **NOT a 2.4.2->2.5.0 regression**
— the earlier "2.4.2 clean" was a seed-coverage artifact (seeds=12 undersampled). The determinism-channel
artifact is real and longstanding; not a novel bug.

Qiskit 2.5.0 additionally showed 6 `layout_reconciliation` violations (w6/opt3, seed 17, all coupling
maps). **Investigated and found to be FALSE POSITIVES of the differ, not miscompilations:** the |0>
output probability multiset of the opt3-transpiled circuit MATCHES the source (compile is correct), but
`Operator.from_circuit` reconciliation returns process_fidelity ~0 under the default VF2 post-layout —
i.e. the operator-level C1 check mis-reconciles these layouts. The layout-applied output is correct.

**Consequences:** (1) do NOT claim a novel bug from this sweep; (2) the C1 (layout_reconciliation)
check is unreliable under the default VF2 post-layout and should be replaced by a sampled,
permutation-robust statevector reconciliation before its violations are trusted; (3) the calibrated
"0 violations" claim holds only with the layout method fixed. Manuscript §6.7 corrected accordingly.
