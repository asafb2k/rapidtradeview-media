<#
.SYNOPSIS
  Registers the Windows Task Scheduler tasks that run run_daily.ps1. Not run by anything
  automatically; run it by hand once.
    weekdays 06:15 ET  -Pass morning   (slots 1-3, 6-7)
    weekdays 10:30 ET  -Pass reports   (report summaries for slots 5 and 7)
    weekdays 13:45 ET  -Pass picks     (today's picks for slot 4, retried until 14:10 ET)
    weekends 08:00 ET  one post (slot 1)

.DESCRIPTION
  The triggers are anchored to UTC ("synchronize across time zones"), so the local (Israel) clock
  change does not move them. The US clock change does: the UTC times are computed from the New York
  offset in force today. After a US change (next: Sunday 2026-11-01, EDT -> EST) every run lands an
  hour earlier in New York time; re-run this script after the change (the 13:45 picks pass would
  otherwise start at 12:45, before the picks publish, and only its retry window would be left).

  Default: runs only while the user is logged on (InteractiveToken): no stored password. -LogonType S4U
  runs the tasks whether or not the user is logged on, still without storing a password, but Windows only
  lets an ELEVATED (Run as administrator) PowerShell register an S4U task ("Access is denied" otherwise;
  checked 2026-09-28). S4U tasks reach the internet and local files (git over SSH with the key in
  C:\Users\USER\.ssh), not password-protected network shares. The PC must be on either way.
  -From YYYY-MM-DD: the first New York date the tasks may run (default today), e.g. to leave today to a
  one-time task. The passes share one run lock, so an overrunning pass delays the next instead of colliding.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\register_daily_task.ps1 -PrintOnly
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\register_daily_task.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\register_daily_task.ps1 -From 2026-09-29
  (elevated) powershell -NoProfile -ExecutionPolicy Bypass -File ...\register_daily_task.ps1 -LogonType S4U
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\register_daily_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$NamePrefix = 'RapidTradeView daily videos',
    [string]$From,
    [ValidateSet('InteractiveToken', 'S4U')][string]$LogonType = 'InteractiveToken',
    [switch]$PrintOnly,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $toolsDir 'run_daily.ps1'

$weekdayNames = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
$weekendNames = @('Saturday', 'Sunday')
# Name suffix, New York hour, minute, days, run_daily.ps1 arguments.
$plan = @(
    @{ Suffix = 'weekday 06:15 ET morning'; Hour = 6; Minute = 15; Days = $weekdayNames; Args = '-Pass morning' },
    @{ Suffix = 'weekday 10:30 ET reports'; Hour = 10; Minute = 30; Days = $weekdayNames; Args = '-Pass reports' },
    @{ Suffix = 'weekday 13:45 ET picks'; Hour = 13; Minute = 45; Days = $weekdayNames; Args = '-Pass picks -RetryEmptyMinutes 25' },
    @{ Suffix = 'weekend 08:00 ET'; Hour = 8; Minute = 0; Days = $weekendNames; Args = '' }
)

if ($Unregister) {
    foreach ($t in Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like "$NamePrefix*" }) {
        Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
        Write-Host "removed: $($t.TaskName)"
    }
    exit 0
}

$eastern = [System.TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$nowNy = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $eastern)

$firstDay = $nowNy.Date
if ($From) { $firstDay = [DateTime]::ParseExact($From, 'yyyy-MM-dd', $null) }

# The next New York date on or after -From (default today) whose weekday is in $Days, at $Hour:$Minute New York time, in UTC.
function Get-UtcStart([int]$Hour, [int]$Minute, [string[]]$Days) {
    $d = $firstDay
    while ($Days -notcontains $d.DayOfWeek.ToString()) { $d = $d.AddDays(1) }
    $local = [DateTime]::SpecifyKind($d.AddHours($Hour).AddMinutes($Minute), [DateTimeKind]::Unspecified)
    return [System.TimeZoneInfo]::ConvertTimeToUtc($local, $eastern)
}

# UTC weekday names equal the New York ones at these hours (10:15 to 17:45 UTC in EDT, an hour later in EST).
function Get-TriggerXml([DateTime]$Utc, [string[]]$DayNames) {
    $days = ($DayNames | ForEach-Object { "<$_ />" }) -join ''
    return @"
    <CalendarTrigger>
      <StartBoundary>$($Utc.ToString('yyyy-MM-ddTHH:mm:ss'))Z</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>$days</DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>

"@
}

function Get-TaskXml([string]$Description, [string]$Triggers, [string]$Arguments) {
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $escapedArgs = [System.Security.SecurityElement]::Escape($Arguments)
    $escapedDesc = [System.Security.SecurityElement]::Escape($Description)
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$escapedDesc</Description>
  </RegistrationInfo>
  <Triggers>
$Triggers  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$user</UserId>
      <LogonType>$LogonType</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>$escapedArgs</Arguments>
      <WorkingDirectory>$([System.Security.SecurityElement]::Escape($toolsDir))</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

Write-Host ("New York now {0:yyyy-MM-dd HH:mm}" -f $nowNy)
foreach ($p in $plan) {
    $name = "$NamePrefix ($($p.Suffix))"
    $utc = Get-UtcStart $p.Hour $p.Minute $p.Days
    $runArgs = ("-NoProfile -ExecutionPolicy Bypass -File `"$script`" " + $p.Args).TrimEnd()
    $xml = Get-TaskXml "RapidTradeView daily social videos (tools\run_daily.ps1 $($p.Args)): $($p.Suffix)." (Get-TriggerXml $utc $p.Days) $runArgs
    if ($PrintOnly) {
        Write-Host ("---- {0}: first run {1:u} (UTC)" -f $name, $utc)
        Write-Host $xml
        continue
    }
    Register-ScheduledTask -TaskName $name -Xml $xml -Force | Out-Null
    $info = Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo
    Write-Host ("registered: {0}; next run {1} (local time)" -f $name, $info.NextRunTime)
}
