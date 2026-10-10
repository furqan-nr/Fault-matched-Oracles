# Running the 1B harvest (protocol 1B-H v2, tag v1.2.0)

Run in Windows PowerShell. Builds go to `..\expansion\_builds` (gitignored), the Qiskit clone is `..\expansion\_qiskit`.

```powershell
cd "D:\CUSIT PhD\Post BASR\Paper 1 - Observability\Paper 1B\harvest"

# 1. make sure the Qiskit clone has the harvest commits (they are newer than the earlier expansion run)
git -C ..\expansion\_qiskit fetch origin main
foreach ($s in "04e955cc7b92688b12d163899ea068e6f78e901a","a5cfe3e906a79da9da2973d720a3d2a264ac0b75","9f1a177f20319ec04131153f431d3a1343484de8","eaadbecc8f894753118b2844187ec22eb4c26b3e","65bd52bbbe826e2f751d88b9d5a70db8aa7b085a","5f0a8617ef5816c4e39fab98b4e7d28e85e941fd") { git -C ..\expansion\_qiskit cat-file -e $s; if ($LASTEXITCODE -ne 0) { "MISSING $s" } }

# 2. build 6 trees (fix and parent for #16336, #16880, #16920), run probes, compare
$env:FMO_REPO = "D:\CUSIT PhD\Fault matched Oracles"
powershell -ExecutionPolicy Bypass -File .\run_harvest.ps1
```

If a build fails, the failure is an outcome ("not buildable"); rerun with `-Only "16920"` for single PRs.
#15683 is not built (typo/comment-only; reported as out of scope).
The probe and compare scripts must not be edited after the first build run (protocol Sec. 5: oracle code frozen; max 2 trigger attempts).
