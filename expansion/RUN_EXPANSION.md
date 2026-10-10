# Paper 1B - real-fault expansion: exact run sheet (Windows PowerShell)

Everything lives in this folder; Post BASR source/data are never modified.
Folder: `expansion/` in this repository

## 0. Prerequisites (you already have these from the 1A builds)
py -3.11 --version ; cargo --version ; git --version

## 1. Resolve SHAs + clone Qiskit (REQUIRED once)  [~2-5 min]
cd expansion
powershell -ExecutionPolicy Bypass -File .\resolve_shas.ps1
# targets_expansion.csv is already pre-filled (squash commits verified by subject line).
# Step 2 needs the _qiskit clone, so run step 1 at least once.

## 2. Build + probe + compare   [8 from-source builds, ~10-30 min each; resumable]
powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1
# one candidate at a time (cheapest first):
powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1 -Only "15943"
powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1 -Only "14763"
powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1 -Only "13833"
powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1 -Only "13945"

## 3. Outputs
results_expansion\pr<N>\{fix,bug}.json      raw probe results
results_expansion\expansion_summary.json    verdict per PR
# Send back: the printed verdict block (detect / blind / notes) or the summary json.

## If a build dies half-way
git -C _qiskit worktree prune ; Remove-Item -Recurse -Force _builds\exp-<PR>-<fix|bug> ; rerun step 2.

Note (2026-10-09): #13833 was merged 2025-02-13, before the Qiskit 2.1 study window, so the paper excludes it from Table 4b. Its saved results are kept here for transparency.
