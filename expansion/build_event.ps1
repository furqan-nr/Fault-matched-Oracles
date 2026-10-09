# Build Qiskit from source at one commit into its own venv (same recipe as Post BASR/environment/setup/build_qiskit_event.ps1,
# but everything lives under Paper 1B/expansion/_builds so Post BASR is never touched).
param([Parameter(Mandatory=$true)][string]$Sha, [Parameter(Mandatory=$true)][string]$Name)
$ErrorActionPreference = "Stop"
$Work = Join-Path $PSScriptRoot "_builds\$Name"
$Py = Join-Path $Work "venv\Scripts\python.exe"
if (Test-Path $Py) { Write-Host ">> $Name already built"; exit 0 }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Rust toolchain (cargo) not found" }
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$SrcTree = Join-Path $Work "src"
if (-not (Test-Path $SrcTree)) {
    git -C (Join-Path $PSScriptRoot "_qiskit") worktree add --detach $SrcTree $Sha
    if ($LASTEXITCODE -ne 0) { throw "worktree add failed for $Sha" }
}
py -3.11 -m venv (Join-Path $Work "venv")
& $Py -m pip install --upgrade "pip>=19" "setuptools-rust>=1.9" wheel
& $Py -m pip install numpy sympy
Write-Host ">> building Qiskit @ $Sha (several minutes)"
& $Py -m pip install $SrcTree
if ($LASTEXITCODE -ne 0) { throw "pip build failed for $Name" }
& $Py -c "import qiskit,sys;print('built',qiskit.__version__)"
