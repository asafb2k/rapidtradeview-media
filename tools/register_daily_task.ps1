<#
.SYNOPSIS
  Registers the Windows Task Scheduler task that runs run_daily.ps1: 06:15 New York time on weekdays
  and 08:00 New York time on weekends. Not run by anything automatically; run it by hand once.

.DESCRIPTION
  The triggers are anchored to UTC ("synchronize across time zones"), so the local (Israel) clock
  change does not move them. The US clock change does: the UTC times are computed from the New York
  offset in force today. After a US change (next: Sunday 2026-11-01, EDT -> EST) the run lands an hour
  earlier in New York time (05:15 / 07:00 ET), which still precedes every slot; re-run this script
  after the change to put it back at 06:15 / 08:00.

  Runs only while the user is logged on (InteractiveToken): no stored password. The PC must be on.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\register_daily_task.ps1 -PrintOnly
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\rtvw\rapidtradeview-media\tools\register_daily_task.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\register_daily_task.ps1 -WithMiddayReports   # + weekday 10:30 ET pass for slots 5 and 7
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\register_daily_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'RapidTradeView daily videos',
    [string]$MiddayTaskName = 'RapidTradeView daily videos (midday reports)',
    [switch]$WithMiddayReports,
    [switch]$PrintOnly,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'run_daily.ps1'

if ($Unregister) {
    foreach ($n in @($TaskName, $MiddayTaskName)) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Host "removed: $n"
        }
    }
    exit 0
}

$eastern = [System.TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$nowNy = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $eastern)

# The next New York date on or after today whose weekday is in $Days, at $Hour:$Minute New York time, in UTC.
function Get-UtcStart([int]$Hour, [int]$Minute, [DayOfWeek[]]$Days) {
    $d = $nowNy.Date
    while ($Days -notcontains $d.DayOfWeek) { $d = $d.AddDays(1) }
    $local = [DateTime]::SpecifyKind($d.AddHours($Hour).AddMinutes($Minute), [DateTimeKind]::Unspecified)
    return [System.TimeZoneInfo]::ConvertTimeToUtc($local, $eastern)
}

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
      <LogonType>InteractiveToken</LogonType>
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
      <WorkingDirectory>$([System.Security.SecurityElement]::Escape($PSScriptRoot))</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

$weekdays = [DayOfWeek[]]@('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
$weekend = [DayOfWeek[]]@('Saturday', 'Sunday')
$wdUtc = Get-UtcStart 6 15 $weekdays
$weUtc = Get-UtcStart 8 0 $weekend
# UTC weekday names equal the New York ones at these hours (10:15 / 12:00 UTC in EDT, 11:15 / 13:00 in EST).
$triggers = (Get-TriggerXml $wdUtc @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')) + "`n" + (Get-TriggerXml $weUtc @('Saturday', 'Sunday')) + "`n"
$runArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$xml = Get-TaskXml 'RapidTradeView daily social videos: select, render, publish manifest (tools\run_daily.ps1). Weekdays 06:15 ET, weekends 08:00 ET.' $triggers $runArgs

$tasks = @(@{ Name = $TaskName; Xml = $xml })
if ($WithMiddayReports) {
    $mdUtc = Get-UtcStart 10 30 $weekdays
    $mdXml = Get-TaskXml 'RapidTradeView daily videos, midday pass: earnings report slots 5 and 7 after the morning releases.' ((Get-TriggerXml $mdUtc @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')) + "`n") "$runArgs -Slots 5,7"
    $tasks += @{ Name = $MiddayTaskName; Xml = $mdXml }
}

Write-Host ("New York now {0:yyyy-MM-dd HH:mm}; weekday trigger {1:u}, weekend trigger {2:u} (UTC)" -f $nowNy, $wdUtc, $weUtc)
foreach ($t in $tasks) {
    if ($PrintOnly) {
        Write-Host "---- $($t.Name) ----"
        Write-Host $t.Xml
        continue
    }
    Register-ScheduledTask -TaskName $t.Name -Xml $t.Xml -Force | Out-Null
    $info = Get-ScheduledTask -TaskName $t.Name | Get-ScheduledTaskInfo
    Write-Host ("registered: {0}; next run {1} (local time)" -f $t.Name, $info.NextRunTime)
}
