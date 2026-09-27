<#
.SYNOPSIS
  Publishes a hand-written (or run_daily) manifest spec: the MP4s must already be in
  v/<date>/<story_id>/ of this repo (pulled or copied); they are committed and pushed if needed, the
  script waits until GitHub Pages serves every one (200 video/mp4, the local size), then writes and
  validates v/<date>/manifest.json (merging slots already published that day), pushes it and checks
  what Pages serves. Nothing is written while a file or a post-package is missing.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\publish_spec.ps1 -Spec D:\rtv-ops\tracks\growth\research\daily-video\2026-09-28\spec-hand.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Spec,
    [string]$Python = 'C:\Users\USER\anaconda3\envs\rapidtradingview\python.exe',
    [string]$Repo,
    [string]$WorkRoot = 'D:\rtv-ops\tracks\growth\research\daily-video',
    [string]$LogDir = 'D:\rtv-ops\tracks\growth\research\daily-video-logs',
    [int]$PagesTimeoutSec = 900
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$Tools = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Repo) { $Repo = Split-Path -Parent $Tools }
. (Join-Path $Tools 'daily_common.ps1')

$specDate = (Get-Content -Raw -Encoding UTF8 $Spec | ConvertFrom-Json).date
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
$LogFile = Join-Path $LogDir ("{0}-publish-{1}.log" -f $specDate, (Get-Date -Format 'HHmmss'))
Enter-RunLock (Join-Path $WorkRoot '.run.lock')
Log "=== publish spec $Spec ($specDate) ==="
if ((Invoke-Git @('pull', '--ff-only', '--quiet')) -ne 0) { Fail 'git pull --ff-only on the media repo' }
Publish-Spec $Spec $PagesTimeoutSec
Stop-Run 0 'DONE'
