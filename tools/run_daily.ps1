<#
.SYNOPSIS
  Daily social video run: select stories -> data.json -> render -> QA -> copy MP4s -> push media ->
  wait for GitHub Pages -> write manifest -> push manifest -> verify what Pages serves.

.DESCRIPTION
  Windows PowerShell 5.1. Everything is logged to D:\rtv-ops\tracks\growth\research\daily-video-logs\.
  Work files (plan, per-story data.json, renders, post-packages) stay private in
  D:\rtv-ops\tracks\growth\research\daily-video\<date>\; only the MP4s and manifest.json go to the
  public media repo. Render / QA / package commands come from tools\daily_hooks.json: a step that is
  null there is a TODO, its story is skipped, and nothing is faked (No Fallbacks).

  Exit codes: 0 = manifest published and verified; 1 = a step failed; 3 = nothing to publish
  (every slot empty or no story rendered).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\run_daily.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\run_daily.ps1 -Date 2026-09-28 -NoPush
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\run_daily.ps1 -Slots 5,7   # midday report pass
#>
[CmdletBinding()]
param(
    [string]$Date,
    [string]$Slots,
    [switch]$NoPush,
    [switch]$SelectOnly,
    [string]$Python = 'C:\Users\USER\anaconda3\envs\rapidtradingview\python.exe',
    [string]$Node = 'node',
    [string]$Repo,
    [string]$WorkRoot = 'D:\rtv-ops\tracks\growth\research\daily-video',
    [string]$LogDir = 'D:\rtv-ops\tracks\growth\research\daily-video-logs',
    [string]$Hooks,
    [int]$PagesTimeoutSec = 900
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
# Windows PowerShell 5.1 leaves $PSScriptRoot empty inside param() defaults: resolve paths here.
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Repo) { $Repo = Split-Path -Parent $tools }
if (-not $Hooks) { $Hooks = Join-Path $tools 'daily_hooks.json' }
if (-not $Date) {
    $ny = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time')
    $Date = $ny.ToString('yyyy-MM-dd')
}
if ($Date -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "Date must be YYYY-MM-DD (got '$Date')" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Work = Join-Path $WorkRoot $Date
New-Item -ItemType Directory -Force -Path $Work | Out-Null
# -Slots is a comma list ("5,7"): powershell -File cannot pass an array to an [int[]] parameter.
$slotList = @()
if ($Slots) { $slotList = @($Slots -split ',' | Where-Object { $_.Trim() } | ForEach-Object { [int]$_.Trim() }) }
$slotTag = ''
if ($slotList.Count) { $slotTag = '-slots' + ($slotList -join '_') }
$LogFile = Join-Path $LogDir ("{0}{1}-{2}.log" -f $Date, $slotTag, (Get-Date -Format 'HHmmss'))

function Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

# Runs a native command, logs every output line (stdout and stderr), returns its exit code.
# EAP is lowered for the call: in PowerShell 5.1 a native command's stderr under 'Stop' throws.
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$Cwd = $null) {
    Log ("  > {0} {1}" -f $Exe, ($Arguments -join ' '))
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    if ($Cwd) { Push-Location $Cwd }
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Log ('    ' + ($_ | Out-String).TrimEnd()) }
        $code = $LASTEXITCODE
    } finally {
        if ($Cwd) { Pop-Location }
        $ErrorActionPreference = $old
    }
    if ($null -eq $code) { $code = 0 }
    return [int]$code
}

function Fail([string]$Message) {
    Log "FAILED: $Message"
    exit 1
}

# Named Invoke-Git, never Git: PowerShell resolves a function before git.exe, so a 'Git' function would call itself.
function Invoke-Git([string[]]$Arguments) {
    return Invoke-Native 'git.exe' (@('-C', $Repo) + $Arguments)
}

# Push; when another writer pushed first, merge (never rebase) and push once more.
function Push-Repo([string]$What) {
    if ((Invoke-Git @('push', '--quiet', 'origin', 'HEAD')) -eq 0) { return }
    Log "push of $What rejected; merging origin and retrying"
    if ((Invoke-Git @('pull', '--no-rebase', '--no-edit', '--quiet', 'origin', 'main')) -ne 0) { Fail "git pull before re-pushing $What" }
    if ((Invoke-Git @('push', '--quiet', 'origin', 'HEAD')) -ne 0) { Fail "git push $What" }
}

$planFile = Join-Path $Work 'plan.json'
$specFile = Join-Path $Work ('spec' + $slotTag + '.json')
$slotArg = @()
if ($slotList.Count) { $slotArg = @('--slots', ($slotList -join ',')) }

Log "=== daily video run $Date$slotTag (repo $Repo, work $Work) ==="

# 0. Latest media repo (earlier manifests feed the novelty rule).
if ((Invoke-Git @('pull', '--ff-only', '--quiet')) -ne 0) { Fail 'git pull --ff-only on the media repo' }

# 1. Select the day's stories from the public API.
if ((Invoke-Native $Python @((Join-Path $tools 'select_stories.py'), '--date', $Date, '--out', $planFile, '--print')) -ne 0) {
    Fail 'story selection'
}
if ($SelectOnly) { Log "SelectOnly: plan at $planFile"; exit 0 }

# 2. One data.json per filled slot.
if ((Invoke-Native $Python (@((Join-Path $tools 'daily.py'), 'stories', '--plan', $planFile, '--work', $Work) + $slotArg)) -ne 0) {
    Fail 'writing story data.json files'
}
# PowerShell 5.1's ConvertFrom-Json emits a JSON array as one object: assign it, then enumerate.
$storiesRaw = Get-Content -Raw -Encoding UTF8 (Join-Path $Work 'stories.json') | ConvertFrom-Json
$stories = @($storiesRaw | Where-Object { $_ })
if ($stories.Count -eq 0) { Log 'NOTHING TO PUBLISH: every selected slot is empty (reasons above).'; exit 3 }

# 3. Render + QA + package each story through the template hooks.
$hookCfg = Get-Content -Raw -Encoding UTF8 $Hooks | ConvertFrom-Json
if (-not (Test-Path $hookCfg.readme)) {
    Log "TODO: $($hookCfg.readme) does not exist yet: the v6 templates have not landed, so no render hook is wired."
}
$rendered = 0
foreach ($s in $stories) {
    $out = $s.dir
    $label = "slot $($s.slot) $($s.story_id) ($($s.category))"
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $out 'qa-passed.json')
    if (-not $s.template) { Log "SKIP $label`: no video template for this category yet (TODO)"; continue }
    $tpl = $hookCfg.templates.($s.template)
    if ($null -eq $tpl) { Log "SKIP $label`: template '$($s.template)' is not in daily_hooks.json (TODO)"; continue }
    $ok = $true
    foreach ($step in @('data', 'render', 'qa', 'package')) {
        $cmd = $tpl.$step
        if ($null -eq $cmd) {
            Log "SKIP $label`: TODO hook '$($s.template).$step' is not wired (see daily_hooks.json / README-v6-daily.md)"
            $ok = $false
            break
        }
        $argv = @($cmd | ForEach-Object {
            $_.Replace('{python}', $Python).Replace('{node}', $Node).Replace('{data}', $s.data).Replace('{out}', $out).Replace('{story_id}', $s.story_id).Replace('{date}', $Date).Replace('{slot}', [string]$s.slot)
        })
        $exe = $argv[0]
        $rest = @()
        if ($argv.Count -gt 1) { $rest = $argv[1..($argv.Count - 1)] }
        Log "$label`: $step"
        if ((Invoke-Native $exe $rest $hookCfg.cwd) -ne 0) {
            Log "SKIP $label`: step '$step' failed (see output above)"
            $ok = $false
            break
        }
    }
    if ($ok) {
        $marker = @{ passed = $true; at = (Get-Date).ToUniversalTime().ToString('o'); template = $s.template } | ConvertTo-Json
        [System.IO.File]::WriteAllText((Join-Path $out 'qa-passed.json'), $marker)
        $rendered++
        Log "$label`: rendered and QA passed"
    }
}
if ($rendered -eq 0) { Log 'NOTHING TO PUBLISH: no story rendered and passed QA (TODO hooks above).'; exit 3 }

# 4. Copy the MP4s into v/<date>/ and write the manifest spec.
$code = Invoke-Native $Python (@((Join-Path $tools 'daily.py'), 'stage', '--plan', $planFile, '--work', $Work, '--spec', $specFile, '--repo', $Repo) + $slotArg)
if ($code -eq 2) { Log 'NOTHING TO PUBLISH: nothing staged.'; exit 3 }
if ($code -ne 0) { Fail 'staging MP4s' }
$spec = Get-Content -Raw -Encoding UTF8 $specFile | ConvertFrom-Json
if ($NoPush) { Log "NoPush: MP4s staged in $Repo\v\$Date, spec $specFile. Next: commit + push, manifest.py wait-urls, manifest.py write --check-urls --merge."; exit 0 }

# 5. Commit + push the media first, so the manifest never points at a file Pages does not serve.
$mediaFiles = @()
foreach ($p in $spec.posts) { foreach ($f in @('reel_9x16', 'feed_4x5', 'square_1x1')) { $mediaFiles += "v/$Date/$($p.story_id)/$f.mp4" } }
if ((Invoke-Git (@('add', '--') + $mediaFiles)) -ne 0) { Fail 'git add media' }
& git.exe -C $Repo diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    if ((Invoke-Git @('commit', '--quiet', '-m', "Daily videos $Date`: media ($($spec.posts.Count) stories)")) -ne 0) { Fail 'git commit media' }
    Push-Repo 'media'
} else { Log 'media unchanged since the last push' }

# 6. Wait until Pages serves every MP4 (200 video/mp4, the local size).
if ((Invoke-Native $Python @((Join-Path $tools 'manifest.py'), '--repo', $Repo, 'wait-urls', '--spec', $specFile, '--timeout', [string]$PagesTimeoutSec)) -ne 0) {
    Fail 'GitHub Pages did not serve every MP4 in time'
}

# 7. Write + validate the manifest (merging slots already published today), commit, push.
if ((Invoke-Native $Python @((Join-Path $tools 'manifest.py'), '--repo', $Repo, 'write', '--spec', $specFile, '--merge', '--check-urls')) -ne 0) {
    Fail 'manifest write / validation'
}
if ((Invoke-Git @('add', '--', "v/$Date/manifest.json")) -ne 0) { Fail 'git add manifest' }
& git.exe -C $Repo diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    if ((Invoke-Git @('commit', '--quiet', '-m', "Daily videos $Date`: manifest")) -ne 0) { Fail 'git commit manifest' }
    Push-Repo 'manifest'
} else { Log 'manifest unchanged since the last push' }

# 8. Verify what Pages serves: the same manifest, valid, every MP4 200 video/mp4.
$deadline = (Get-Date).AddSeconds($PagesTimeoutSec)
while ($true) {
    $code = Invoke-Native $Python @((Join-Path $tools 'manifest.py'), '--repo', $Repo, 'validate', '--date', $Date, '--remote', '--same-as-local', '--check-urls')
    if ($code -eq 0) { break }
    if ((Get-Date) -gt $deadline) { Fail 'Pages does not serve the new manifest (or it is invalid)' }
    Start-Sleep -Seconds 30
}
Log "DONE: https://asafb2k.github.io/rapidtradeview-media/v/$Date/manifest.json is live and valid ($rendered stories rendered this run)."
exit 0
