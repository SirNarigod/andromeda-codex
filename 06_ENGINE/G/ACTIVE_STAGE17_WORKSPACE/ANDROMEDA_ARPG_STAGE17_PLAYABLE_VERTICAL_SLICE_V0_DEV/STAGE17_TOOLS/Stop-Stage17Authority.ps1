[CmdletBinding()]
param([ValidateRange(1, 60)][int]$TimeoutSeconds = 20)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Stage17Authority.Common.ps1')

$record = Read-Stage17ProcessRecord
if ($null -eq $record) {
    throw 'STAGE17_AUTHORITY_PROCESS_RECORD_NOT_FOUND'
}
if ($null -eq $record.pid -or $null -eq $record.python_path -or $null -eq $record.process_start_time_utc) {
    throw 'STAGE17_AUTHORITY_PROCESS_RECORD_INCOMPLETE'
}
$ownedPid = [int]$record.pid
$process = Get-Process -Id $ownedPid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    $listeners = @(Get-Stage17ListenerPids)
    if ($listeners.Count -gt 0) {
        throw "RECORDED_PROCESS_ABSENT_BUT_PORT_8000_OWNED_BY: $($listeners -join ',')"
    }
    $output = @{
        schema = 'ANDROMEDA_STAGE17_AUTHORITY_PROCESS_V0_1_0_DEV'
        state = 'OFF'
        pid = $ownedPid
        shutdown_at = (Get-Date).ToUniversalTime().ToString('o')
        shutdown_reason = 'PROCESS_ALREADY_EXITED'
    }
    Write-Stage17ProcessRecord $output
    Write-Host 'STAGE17_AUTHORITY: OFF (process already exited)'
    exit 0
}
if (-not (Test-Stage17OwnedProcess -ProcessId $ownedPid -ExpectedPython ([string]$record.python_path) -ExpectedStartTimeUtc $record.process_start_time_utc)) {
    throw "PROCESS_OWNERSHIP_NOT_PROVEN: pid=$ownedPid"
}
$backendProcess = Get-Process -Id $ownedPid -ErrorAction Stop
$recordProperties = @($record.PSObject.Properties.Name)
if ('listener_parent_pid' -in $recordProperties -and $null -ne $record.listener_parent_pid) {
    if ($null -eq $backendProcess.Parent -or $backendProcess.Parent.Id -ne [int]$record.listener_parent_pid) {
        throw "PROCESS_PARENT_OWNERSHIP_NOT_PROVEN: pid=$ownedPid"
    }
}
$listenersBefore = @(Get-Stage17ListenerPids)
if ($listenersBefore.Count -gt 0 -and ($listenersBefore.Count -ne 1 -or $listenersBefore[0] -ne $ownedPid)) {
    throw "PORT_8000_LISTENER_NOT_EXCLUSIVELY_OWNED: expected=$ownedPid actual=$($listenersBefore -join ',')"
}

Stop-Process -Id $ownedPid
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ($null -eq (Get-Process -Id $ownedPid -ErrorAction SilentlyContinue)) {
        break
    }
    Start-Sleep -Milliseconds 200
}
if ($null -ne (Get-Process -Id $ownedPid -ErrorAction SilentlyContinue)) {
    throw "OWNED_PROCESS_DID_NOT_STOP: pid=$ownedPid"
}
if (
    'launcher_pid' -in $recordProperties -and
    'requested_python_path' -in $recordProperties -and
    'launcher_start_time_utc' -in $recordProperties -and
    $null -ne $record.launcher_pid -and
    $null -ne $record.requested_python_path -and
    $null -ne $record.launcher_start_time_utc
) {
    $launcherPid = [int]$record.launcher_pid
    $launcherDeadline = (Get-Date).AddSeconds([Math]::Min($TimeoutSeconds, 10))
    while ((Get-Date) -lt $launcherDeadline) {
        if ($null -eq (Get-Process -Id $launcherPid -ErrorAction SilentlyContinue)) {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if ($null -ne (Get-Process -Id $launcherPid -ErrorAction SilentlyContinue)) {
        if (-not (Test-Stage17OwnedProcess -ProcessId $launcherPid -ExpectedPython ([string]$record.requested_python_path) -ExpectedStartTimeUtc $record.launcher_start_time_utc)) {
            throw "LAUNCHER_PROCESS_OWNERSHIP_NOT_PROVEN: pid=$launcherPid"
        }
        Stop-Process -Id $launcherPid
    }
}
$listenerDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    $listenersAfter = @(Get-Stage17ListenerPids)
    if ($listenersAfter.Count -eq 0) {
        break
    }
    Start-Sleep -Milliseconds 200
} while ((Get-Date) -lt $listenerDeadline)
if ($listenersAfter.Count -gt 0) {
    throw "LISTENER_8000_REMAINS_AFTER_OWNED_SHUTDOWN: $($listenersAfter -join ',')"
}

$output = @{
    schema = 'ANDROMEDA_STAGE17_AUTHORITY_PROCESS_V0_1_0_DEV'
    state = 'OFF'
    pid = $ownedPid
    python_path = [string]$record.python_path
    process_start_time_utc = if ($record.process_start_time_utc -is [DateTime]) { $record.process_start_time_utc.ToUniversalTime().ToString('o') } else { [string]$record.process_start_time_utc }
    launcher_pid = if ('launcher_pid' -in $recordProperties -and $null -ne $record.launcher_pid) { [int]$record.launcher_pid } else { $null }
    shutdown_at = (Get-Date).ToUniversalTime().ToString('o')
    shutdown_reason = 'CONTROLLED_OWNER_PID_STOP'
    listener_8000 = 'NONE'
}
Write-Stage17ProcessRecord $output
Write-Host "STAGE17_AUTHORITY: OFF pid=$ownedPid listener_8000=NONE"
