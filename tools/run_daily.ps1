<#
.SYNOPSIS
  Daily social video run: select stories -> data.json -> render -> QA -> copy MP4s -> push media ->
  wait for GitHub Pages -> write manifest -> push manifest -> verify what Pages serves.

.DESCRIPTION
  Windows PowerShell 5.1. Weekdays run in three passes (register_daily_task.ps1), each merging its
  slots into the day's manifest:
    -Pass morning   06:15 ET  slots 1, 2, 3, 6, 7 (earnings, trades, theme)
    -Pass reports   10:30 ET  slots 5, 7 (report summaries released that morning; a report replaces
                              the morning theme in slot 7)
    -Pass picks     13:45 ET  slot 4 (today's picks, published ~13:30; retried up to -RetryEmptyMinutes)
  Weekends: one 08:00 ET run with no -Pass (slot 1). -Slots "5,7" picks slots by hand instead.
  A slot today's manifest already fills is never re-rendered or replaced (daily.py stories).

  Everything is logged to D:\rtv-ops\tracks\growth\research\daily-video-logs\. Work files (plan,
  per-story data.json, renders, post-packages) stay private in
  D:\rtv-ops\tracks\growth\research\daily-video\<date>\; only the MP4s and manifest.json go to the
  public media repo. Render / QA / package commands come from tools\daily_hooks.json: a step that is
  null there is a TODO, its story is skipped, and nothing is faked (No Fallbacks).

  Exit codes: 0 = manifest published and verified (or -NoPush / -SelectOnly done); 1 = a step failed;
  3 = nothing to publish (every slot empty, already published, or no story rendered).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\run_daily.ps1 -Pass morning
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\run_daily.ps1 -Date 2026-09-28 -Pass morning -NoPush
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\run_daily.ps1 -Pass picks -RetryEmptyMinutes 25
#>
[CmdletBinding()]
param(
    [string]$Date,
    [ValidateSet('', 'morning', 'reports', 'picks')][string]$Pass = '',
    [string]$Slots,
    [int]$RetryEmptyMinutes = 0,
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
$Tools = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Repo) { $Repo = Split-Path -Parent $Tools }
if (-not $Hooks) { $Hooks = Join-Path $Tools 'daily_hooks.json' }
. (Join-Path $Tools 'daily_common.ps1')

if (-not $Date) {
    $ny = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time')
    $Date = $ny.ToString('yyyy-MM-dd')
}
if ($Date -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "Date must be YYYY-MM-DD (got '$Date')" }

# Slots of this run: -Slots (a comma list: powershell -File cannot pass an array), else the pass's.
$passSlots = @{ morning = '1,2,3,6,7'; reports = '5,7'; picks = '4' }
if (-not $Slots -and $Pass) { $Slots = $passSlots[$Pass] }
$slotList = @()
if ($Slots) { $slotList = @($Slots -split ',' | Where-Object { $_.Trim() } | ForEach-Object { [int]$_.Trim() }) }
$slotTag = ''
if ($Pass) { $slotTag = "-$Pass" } elseif ($slotList.Count) { $slotTag = '-slots' + ($slotList -join '_') }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Work = Join-Path $WorkRoot $Date
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$LogFile = Join-Path $LogDir ("{0}{1}-{2}.log" -f $Date, $slotTag, (Get-Date -Format 'HHmmss'))
$planFile = Join-Path $Work ('plan' + $slotTag + '.json')
$specFile = Join-Path $Work ('spec' + $slotTag + '.json')
$slotArg = @()
if ($slotList.Count) { $slotArg = @('--slots', ($slotList -join ',')) }

Enter-RunLock (Join-Path $WorkRoot '.run.lock')
Log "=== daily video run $Date$slotTag (repo $Repo, work $Work) ==="

# 0. Latest media repo (earlier manifests feed the novelty rule; today's tells what is published).
if ((Invoke-Git @('pull', '--ff-only', '--quiet')) -ne 0) { Fail 'git pull --ff-only on the media repo' }

# 1-2. Select the day's stories and write one data.json per filled slot. When every slot of this run
# is empty (e.g. today's picks not out yet at 13:45), select again every 3 minutes for up to
# -RetryEmptyMinutes.
$started = Get-Date
while ($true) {
    if ((Invoke-Native $Python @((Join-Path $Tools 'select_stories.py'), '--date', $Date, '--out', $planFile, '--print')) -ne 0) {
        Fail 'story selection'
    }
    $plan = Get-Content -Raw -Encoding UTF8 $planFile | ConvertFrom-Json
    $mine = @($plan.slots | Where-Object { $_ -and (($slotList.Count -eq 0) -or ($slotList -contains [int]$_.slot)) })
    $filledCount = @($mine | Where-Object { $_.status -eq 'filled' }).Count
    if ($filledCount -gt 0 -or $RetryEmptyMinutes -le 0 -or ((Get-Date) - $started).TotalMinutes -ge $RetryEmptyMinutes) { break }
    Log "every slot of this run is empty; selecting again in 3 minutes (retry window $RetryEmptyMinutes min)"
    Start-Sleep -Seconds 180
}
if ($SelectOnly) { Stop-Run 0 "SelectOnly: plan at $planFile" }
if ((Invoke-Native $Python (@((Join-Path $Tools 'daily.py'), 'stories', '--plan', $planFile, '--work', $Work, '--repo', $Repo) + $slotArg)) -ne 0) {
    Fail 'writing story data.json files'
}
# PowerShell 5.1's ConvertFrom-Json emits a JSON array as one object: assign it, then enumerate.
$storiesRaw = Get-Content -Raw -Encoding UTF8 (Join-Path $Work 'stories.json') | ConvertFrom-Json
$stories = @($storiesRaw | Where-Object { $_ })
if ($stories.Count -eq 0) { Stop-Run 3 'NOTHING TO PUBLISH: every slot of this run is empty or already published (reasons above).' }

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
if ($rendered -eq 0) { Stop-Run 3 'NOTHING TO PUBLISH: no story rendered and passed QA (TODO hooks above).' }

# 4. Copy the MP4s into v/<date>/ and write the manifest spec.
$code = Invoke-Native $Python (@((Join-Path $Tools 'daily.py'), 'stage', '--plan', $planFile, '--work', $Work, '--spec', $specFile, '--repo', $Repo) + $slotArg)
if ($code -eq 2) { Stop-Run 3 'NOTHING TO PUBLISH: nothing staged.' }
if ($code -ne 0) { Fail 'staging MP4s' }
if ($NoPush) { Stop-Run 0 "NoPush: MP4s staged in $Repo\v\$Date, spec $specFile. Publish with tools\publish_spec.ps1 -Spec $specFile" }

# 5-8. Push the media, wait for Pages, write + push the manifest, verify what Pages serves.
Publish-Spec $specFile $PagesTimeoutSec
Stop-Run 0 "DONE: $rendered stories rendered this run."
