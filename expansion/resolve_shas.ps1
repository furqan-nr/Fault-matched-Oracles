# Resolve fix/parent SHAs of the Tier-A candidate PRs from upstream Qiskit history (squash-merge subjects end in "(#N)").
# Writes targets_expansion.csv next to this script. Touches nothing outside this folder.
$ErrorActionPreference = "Stop"
$Src = Join-Path $PSScriptRoot "_qiskit"
if (-not (Test-Path (Join-Path $Src ".git"))) {
    git clone --filter=blob:none https://github.com/Qiskit/qiskit $Src
    if ($LASTEXITCODE -ne 0) { throw "clone failed" }
}
git -C $Src fetch origin --tags --quiet
$cands = @(
    @("13945","contract_metadata"),
    @("13833","contract_metadata"),
    @("15943","global_phase"),
    @("14763","determinism")
)
$rows = @("pr,channel,fix_sha,parent_sha")
foreach ($c in $cands) {
    $pr = $c[0]
    $sha = (git -C $Src log origin/main --first-parent --fixed-strings "--grep=(#$pr)" --format=%H -n 1)
    if (-not $sha) { Write-Warning "PR $pr : no squash commit found on origin/main - resolve by hand"; continue }
    $sha = $sha.Trim()
    $par = (git -C $Src rev-parse "$sha^").Trim()
    $subj = (git -C $Src log -1 --format=%s $sha)
    Write-Host ("PR {0}: fix={1} parent={2}`n        subject: {3}" -f $pr, $sha, $par, $subj)
    $rows += "$pr,$($c[1]),$sha,$par"
}
$rows | Set-Content -Encoding ascii (Join-Path $PSScriptRoot "targets_expansion.csv")
Write-Host "`nwrote targets_expansion.csv - CHECK that each subject above matches the PR title before building."
