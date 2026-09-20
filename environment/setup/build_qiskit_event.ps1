# E3 / Phase 2 (Windows) - build Qiskit-under-test FROM SOURCE for one revision.
# Usage:  .\environment\setup\build_qiskit_event.ps1 -Sha 2.4.2 -EventEnvId smoke-2_4_2
param(
    [Parameter(Mandatory=$true)][string]$Sha,
    [Parameter(Mandatory=$true)][string]$EventEnvId,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $RepoRoot

$Work = "environment\_builds\$EventEnvId"
$Lock = "environment\events\$EventEnvId.lock"

if ((Test-Path $Lock) -and -not $Force) {
    Write-Host ">> $Lock already exists; skipping rebuild (use -Force to rebuild)."
    exit 0
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Error "Rust toolchain (cargo) not found - required to build Qiskit from source. See SETUP_WINDOWS.md."
    exit 2
}
New-Item -ItemType Directory -Force -Path $Work, "environment\events" | Out-Null

if (-not (Test-Path "$Work\qiskit\.git")) {
    if (Test-Path "$Work\qiskit") { Remove-Item -Recurse -Force "$Work\qiskit" }
    # Blobless partial clone (full commit/tree history; file blobs fetched on demand at checkout) with
    # retries, so a flaky network doesn't drop the build. Much lighter than a full clone.
    $ok = $false
    foreach ($attempt in 1..3) {
        git -c http.postBuffer=524288000 -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 clone --filter=blob:none https://github.com/Qiskit/qiskit "$Work\qiskit"
        if (($LASTEXITCODE -eq 0) -and (Test-Path "$Work\qiskit\.git")) { $ok = $true; break }
        Write-Host "!! clone attempt $attempt/3 failed; cleaning up and retrying ..."
        if (Test-Path "$Work\qiskit") { Remove-Item -Recurse -Force "$Work\qiskit" }
    }
    if (-not $ok) { Write-Error "clone failed after 3 attempts (network)."; exit 3 }
}
git -C "$Work\qiskit" fetch --all --tags --quiet
git -C "$Work\qiskit" checkout --quiet $Sha
if ($LASTEXITCODE -ne 0) { Write-Error "checkout of $Sha failed."; exit 4 }
$Resolved = (git -C "$Work\qiskit" rev-parse HEAD).Trim()

py -3.11 -m venv "$Work\venv"
# Use the venv's python.exe DIRECTLY (do not Activate.ps1 - that would leave the per-event venv
# active in the caller's shell; keep the caller on .venv-anchor).
$VenvPy = "$Work\venv\Scripts\python.exe"
& $VenvPy -m pip install --upgrade "pip>=19" "setuptools-rust>=1.9" wheel
Write-Host ">> Building Qiskit @ $Resolved from source"
rustc --version
& $VenvPy -m pip install "$Work\qiskit"

$py = @"
import json, platform, qiskit
print(json.dumps({
  'event_environment_id': '$EventEnvId',
  'requested': '$Sha',
  'resolved_sha': '$Resolved',
  'qiskit_version': qiskit.__version__,
  'python': platform.python_version(),
  'platform': platform.platform(),
}, indent=2))
"@
& $VenvPy -c $py | Out-File -Encoding ascii $Lock
Write-Host ">> Recorded $Lock"
