# Shared helpers for run_daily.ps1 and publish_spec.ps1 (dot-sourced; Windows PowerShell 5.1).
# The caller sets $LogFile, $Repo, $Python and $Tools before calling anything here.

function Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $Message
    Add-Content -Path $script:LogFile -Value $line -Encoding UTF8
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
        # stderr lines arrive as ErrorRecords: log their text only.
        & $Exe @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { Log ('    ' + $_.Exception.Message) } else { Log ('    ' + ($_ | Out-String).TrimEnd()) }
        }
        $code = $LASTEXITCODE
    } finally {
        if ($Cwd) { Pop-Location }
        $ErrorActionPreference = $old
    }
    if ($null -eq $code) { $code = 0 }
    return [int]$code
}

# One run at a time (the three weekday passes and hand publishes share the repo and the work dir).
function Enter-RunLock([string]$Path, [int]$WaitMinutes = 30) {
    $deadline = (Get-Date).AddMinutes($WaitMinutes)
    while ($true) {
        try {
            $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
            $bytes = [System.Text.Encoding]::UTF8.GetBytes("pid $PID since $((Get-Date).ToUniversalTime().ToString('o'))")
            $fs.Write($bytes, 0, $bytes.Length)
            $fs.Close()
            $script:HeldLock = $Path
            return
        } catch [System.IO.IOException] {
            $age = (Get-Date) - (Get-Item $Path).LastWriteTime
            if ($age.TotalHours -gt 3) { Log "stale run lock ($([int]$age.TotalMinutes) min old): taking it over"; Remove-Item -Force $Path; continue }
            if ((Get-Date) -gt $deadline) { throw "another daily-video run holds $Path" }
            Start-Sleep -Seconds 30
        }
    }
}

function Stop-Run([int]$Code, [string]$Message) {
    if ($Message) { Log $Message }
    if ($script:HeldLock -and (Test-Path $script:HeldLock)) { Remove-Item -Force $script:HeldLock }
    exit $Code
}

function Fail([string]$Message) { Stop-Run 1 "FAILED: $Message" }

# Named Invoke-Git, never Git: PowerShell resolves a function before git.exe, so a 'Git' function would call itself.
function Invoke-Git([string[]]$Arguments) {
    return Invoke-Native 'git.exe' (@('-C', $script:Repo) + $Arguments)
}

# Push; when another writer pushed first, merge (never rebase) and push once more.
function Push-Repo([string]$What) {
    if ((Invoke-Git @('push', '--quiet', 'origin', 'HEAD')) -eq 0) { return }
    Log "push of $What rejected; merging origin and retrying"
    if ((Invoke-Git @('pull', '--no-rebase', '--no-edit', '--quiet', 'origin', 'main')) -ne 0) { Fail "git pull before re-pushing $What" }
    if ((Invoke-Git @('push', '--quiet', 'origin', 'HEAD')) -ne 0) { Fail "git push $What" }
}

function Commit-Staged([string]$Message) {
    & git.exe -C $script:Repo diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Log "nothing new to commit ($Message)"; return }
    if ((Invoke-Git @('commit', '--quiet', '-m', $Message)) -ne 0) { Fail "git commit: $Message" }
    Push-Repo $Message
}

# Publish a manifest spec (manifest.py write --spec): every file (MP4s of a video post, PNG / JPEG of
# an image post) committed and pushed first, then wait until GitHub Pages serves each one (200 with its
# type, the local size), then write + validate the manifest (merging slots already published today),
# push it and verify what Pages serves. The live manifest never points at a file Pages does not serve.
function Publish-Spec([string]$SpecFile, [int]$PagesTimeoutSec = 900) {
    $spec = Get-Content -Raw -Encoding UTF8 $SpecFile | ConvertFrom-Json
    $date = $spec.date
    $posts = @($spec.posts | Where-Object { $_ })
    $listFile = "$SpecFile.files.txt"
    if ((Invoke-Native $script:Python @((Join-Path $script:Tools 'manifest.py'), '--repo', $script:Repo, 'check-spec', '--spec', $SpecFile, '--list-out', $listFile)) -ne 0) {
        Fail 'not ready to publish (missing files or post-packages above)'
    }
    $mediaFiles = @(Get-Content -Encoding UTF8 $listFile | Where-Object { $_.Trim() })
    if ((Invoke-Git (@('add', '--') + $mediaFiles)) -ne 0) { Fail 'git add media' }
    Commit-Staged "Daily videos $date`: media ($($posts.Count) stories)"
    if ((Invoke-Native $script:Python @((Join-Path $script:Tools 'manifest.py'), '--repo', $script:Repo, 'wait-urls', '--spec', $SpecFile, '--timeout', [string]$PagesTimeoutSec)) -ne 0) {
        Fail 'GitHub Pages did not serve every MP4 in time'
    }
    if ((Invoke-Native $script:Python @((Join-Path $script:Tools 'manifest.py'), '--repo', $script:Repo, 'write', '--spec', $SpecFile, '--merge', '--check-urls')) -ne 0) {
        Fail 'manifest write / validation'
    }
    if ((Invoke-Git @('add', '--', "v/$date/manifest.json")) -ne 0) { Fail 'git add manifest' }
    Commit-Staged "Daily videos $date`: manifest"
    $deadline = (Get-Date).AddSeconds($PagesTimeoutSec)
    while ($true) {
        $code = Invoke-Native $script:Python @((Join-Path $script:Tools 'manifest.py'), '--repo', $script:Repo, 'validate', '--date', $date, '--remote', '--same-as-local', '--check-urls')
        if ($code -eq 0) { break }
        if ((Get-Date) -gt $deadline) { Fail 'Pages does not serve the new manifest (or it is invalid)' }
        Start-Sleep -Seconds 30
    }
    Log "PUBLISHED: https://asafb2k.github.io/rapidtradeview-media/v/$date/manifest.json is live and valid."
}

# Facts feed for Grok-run brand social (tools/facts.py -> v/<date>/facts.json; GROK-SOCIAL.md). It never depends
# on a render and never changes the run's exit code: every failure here is logged and the run goes on.
# facts.py exit 0 = every source loaded; 4 = a source failed (the file says which): a partial file is published only
# when no facts.json for the date exists yet, so a passing outage never replaces a complete feed. $Push = $false
# (-NoPush / -SelectOnly) writes the file into the repo without committing it.
function Publish-Facts([string]$Date, [string]$Work, [bool]$Push) {
    try {
        $tmp = Join-Path $Work 'facts.json'
        $rel = "v/$Date/facts.json"
        $dest = Join-Path $script:Repo $rel
        Remove-Item -Force -ErrorAction SilentlyContinue $tmp
        $code = Invoke-Native $script:Python @((Join-Path $script:Tools 'facts.py'), '--date', $Date, '--out', $tmp, '--print')
        if (($code -eq 0 -or $code -eq 4) -and -not (Test-Path $tmp)) { Log "FACTS FAILED: facts.py exit $code but no $tmp"; return }
        if ($code -eq 4 -and (Test-Path $dest)) { Log "FACTS PARTIAL (a source failed): kept the existing $rel; this run's file is $tmp"; return }
        if ($code -ne 0 -and $code -ne 4) { Log "FACTS FAILED (facts.py exit $code): $rel not updated; the videos go on"; return }
        if ($code -eq 4) { Log "FACTS PARTIAL (a source failed): publishing it, there is no $rel yet" }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -Force $tmp $dest
        if (-not $Push) { Log "facts: wrote $dest (not committed: -NoPush / -SelectOnly)"; return }
        if ((Invoke-Git @('add', '--', $rel)) -ne 0) { Log "FACTS: git add $rel failed"; return }
        & git.exe -C $script:Repo diff --cached --quiet -- $rel
        if ($LASTEXITCODE -eq 0) { Log "facts: $rel unchanged"; return }
        if ((Invoke-Git @('commit', '--quiet', '-m', "Facts $Date", '--', $rel)) -ne 0) { Log "FACTS: git commit failed"; return }
        if ((Invoke-Git @('push', '--quiet', 'origin', 'HEAD')) -ne 0) {
            Log 'facts push rejected; merging origin and retrying'
            if ((Invoke-Git @('pull', '--no-rebase', '--no-edit', '--quiet', 'origin', 'main')) -ne 0) {
                [void](Invoke-Git @('merge', '--abort'))
                Log "FACTS: git pull failed; the facts commit stays local and goes out with the next push"
                return
            }
            if ((Invoke-Git @('push', '--quiet', 'origin', 'HEAD')) -ne 0) { Log "FACTS: git push failed; the facts commit stays local"; return }
        }
        Log "facts: pushed $rel (Pages: https://asafb2k.github.io/rapidtradeview-media/$rel)"
    } catch {
        Log "FACTS FAILED: $($_.Exception.Message); the videos go on"
    }
}

# Preflight gate (manifest.py preflight; owner rule 2026-09-28: every post ready an hour before it goes
# live). $Select = the posts to check ('--slots', '1,2' or '--due-within-min', '90', '--due-after-min', '60').
# A failing post is marked "status": "held" in the manifest (manifest.py --hold; nothing is deleted),
# committed, pushed and checked on Pages. Returns manifest.py's exit code: 0 pass, 1 a failure, 2 nothing to check.
function Invoke-Preflight([string]$Date, [string[]]$Select) {
    $code = Invoke-Native $script:Python (@((Join-Path $script:Tools 'manifest.py'), '--repo', $script:Repo, 'preflight', '--date', $Date, '--hold') + $Select)
    if ($code -eq 2) { return 2 }
    if ($code -ne 0) { Log "PREFLIGHT FAILED for $Date ($($Select -join ' ')): see D:\rtv-ops\tracks\growth\research\daily-video\$Date\preflight-<slot>.json" }
    & git.exe -C $script:Repo diff --quiet -- "v/$Date/manifest.json"
    if ($LASTEXITCODE -ne 0) {
        if ((Invoke-Git @('add', '--', "v/$Date/manifest.json")) -ne 0) { Fail 'git add held manifest' }
        Commit-Staged "Preflight $Date`: hold failing posts"
        $deadline = (Get-Date).AddSeconds(600)
        while ((Invoke-Native $script:Python @((Join-Path $script:Tools 'manifest.py'), '--repo', $script:Repo, 'validate', '--date', $Date, '--remote', '--same-as-local')) -ne 0) {
            if ((Get-Date) -gt $deadline) { Fail 'Pages does not serve the held manifest' }
            Start-Sleep -Seconds 30
        }
        Log "HELD posts are live on Pages for $Date (status held; nothing deleted)."
    }
    return $code
}
