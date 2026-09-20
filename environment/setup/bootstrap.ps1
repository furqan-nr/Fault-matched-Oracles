# Turnkey E1-E4 + Phase 0 bootstrap (Windows / PowerShell).
# Prereqs (one-time): Python 3.11, Rust (MSVC), VS C++ Build Tools, git. See SETUP_WINDOWS.md.
# Usage:  .\environment\setup\bootstrap.ps1            (build tag defaults to 2.4.2)
#         .\environment\setup\bootstrap.ps1 -BuildTag 2.4.2
param([string]$BuildTag = "2.4.2")
$ErrorActionPreference = "Stop"
# Make native-command (pip/git) non-zero exits terminate, on PowerShell 7.4+; harmless on 5.1.
try { $PSNativeCommandUseErrorActionPreference = $true } catch {}
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $RepoRoot

function Invoke-Checked($file, $argline) {
    Write-Host ">> $file $argline"
    & $file @argline
    if ($LASTEXITCODE -ne 0) { throw "command failed ($LASTEXITCODE): $file $argline" }
}

Write-Host "==> Checking prerequisites"
& py -3.11 --version
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "MISSING: Rust/cargo (see SETUP_WINDOWS.md)" }
if (-not (Get-Command git   -ErrorAction SilentlyContinue)) { throw "MISSING: git (see SETUP_WINDOWS.md)" }
rustc --version; cargo --version

Write-Host "==> E1: harness lock (.venv-harness, no Qiskit)"
& "$PSScriptRoot\make_harness_lock.ps1"

Write-Host "==> E2: anchor/dev env (.venv-anchor = harness + Qiskit 2.4.2 wheel)"
py -3.11 -m venv .venv-anchor
& .\.venv-anchor\Scripts\Activate.ps1
python -m pip install --upgrade "pip>=19" wheel
python -m pip install -r environment\requirements.anchor.in
python -m pip install -e .

Write-Host "==> E3: from-source Qiskit build smoke ($BuildTag) [isolated venv]"
& "$PSScriptRoot\build_qiskit_event.ps1" -Sha $BuildTag -EventEnvId ("smoke-" + ($BuildTag -replace '\.','_'))

Write-Host "==> E4 + Phase 0 (in .venv-anchor)"
& .\.venv-anchor\Scripts\Activate.ps1
python environment\setup\check_feasibility.py
python -m cart.cli manifest
python -m pytest -q

Write-Host "==> Done. Fill machine-specific fields in environment\ENV.md."
