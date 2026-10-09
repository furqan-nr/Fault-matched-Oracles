# Build fix+parent for each candidate, run the probe on each, then compare.
# Usage:  powershell -ExecutionPolicy Bypass -File .\run_expansion.ps1 [-Only "15943,14763"]
param([string]$Only = "")
$ErrorActionPreference = "Stop"
$rows = Import-Csv (Join-Path $PSScriptRoot "targets_expansion.csv")
if ($Only) { $keep = $Only.Split(","); $rows = $rows | Where-Object { $keep -contains $_.pr } }
$out = Join-Path $PSScriptRoot "results_expansion"
foreach ($r in $rows) {
    foreach ($pair in @(@("fix", $r.fix_sha), @("bug", $r.parent_sha))) {
        $name = "exp-$($r.pr)-$($pair[0])"
        & (Join-Path $PSScriptRoot "build_event.ps1") -Sha $pair[1] -Name $name
        $py = Join-Path $PSScriptRoot "_builds\$name\venv\Scripts\python.exe"
        Push-Location $PSScriptRoot
        & $py "probe.py" --pr $r.pr --label $pair[0] --out $out
        Pop-Location
    }
}
Push-Location $PSScriptRoot
py -3.11 compare.py --dir $out
Pop-Location
