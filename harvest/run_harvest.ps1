# Build fix+parent for each harvest PR (reusing ..\expansion\build_event.ps1 and its _qiskit clone), run probes, compare.
# Usage:  powershell -ExecutionPolicy Bypass -File .\run_harvest.ps1 [-Only "16920,16880"]
param([string]$Only = "")
$ErrorActionPreference = "Stop"
$exp = Join-Path $PSScriptRoot "..\expansion"
$rows = Import-Csv (Join-Path $PSScriptRoot "targets_harvest.csv")
if ($Only) { $keep = $Only.Split(","); $rows = $rows | Where-Object { $keep -contains $_.pr } }
$out = Join-Path $PSScriptRoot "results_harvest"
if (-not $env:FMO_REPO) { $env:FMO_REPO = "D:\CUSIT PhD\Fault matched Oracles" }
foreach ($r in $rows) {
    foreach ($pair in @(@("fix", $r.fix_sha), @("bug", $r.parent_sha))) {
        $name = "harv-$($r.pr)-$($pair[0])"
        & (Join-Path $exp "build_event.ps1") -Sha $pair[1] -Name $name
        $py = Join-Path $exp "_builds\$name\venv\Scripts\python.exe"
        Push-Location $PSScriptRoot
        & $py "probe_harvest.py" --pr $r.pr --label $pair[0] --out $out
        Pop-Location
    }
}
Push-Location $PSScriptRoot
py -3.11 compare_harvest.py --dir $out
Pop-Location
