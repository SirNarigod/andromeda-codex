[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Stage17Authority.Common.ps1')

$record = Read-Stage17ProcessRecord
$listeners = @(Get-Stage17ListenerPids)
$health = $null
try {
    $health = Invoke-RestMethod -Uri $script:Stage17HealthUri -Method Get -TimeoutSec 3
}
catch {
    $health = $null
}
[pscustomobject]@{
    process_record = $record
    listener_pids = $listeners
    health = $health
} | ConvertTo-Json -Depth 12
