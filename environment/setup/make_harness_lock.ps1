# E1 (Windows) - build the fixed HARNESS environment and generate the pinned lockfile.
# Run in PowerShell from anywhere. Qiskit is NOT in this lock (it is built per event).
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $RepoRoot

Write-Host ">> Creating harness venv with Python 3.11"
py -3.11 -m venv .venv-harness
& .\.venv-harness\Scripts\Activate.ps1

python -m pip install --upgrade "pip>=19" "setuptools-rust>=1.9" wheel
Write-Host ">> Installing harness deps (no Qiskit-under-test here)"
python -m pip install -r environment\requirements.harness.in

Write-Host ">> Freezing lock"
python -m pip freeze --exclude-editable | Out-File -Encoding ascii environment\requirements.lock
(Get-FileHash environment\requirements.lock -Algorithm SHA256).Hash |
    Out-File -Encoding ascii environment\requirements.lock.sha256
Get-Content environment\requirements.lock.sha256
Write-Host ">> Done. Record the sha256 and Benchpress revision in environment\ENV.md."
