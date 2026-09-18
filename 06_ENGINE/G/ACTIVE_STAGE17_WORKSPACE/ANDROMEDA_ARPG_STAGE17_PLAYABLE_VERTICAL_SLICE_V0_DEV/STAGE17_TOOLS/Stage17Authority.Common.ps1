Set-StrictMode -Version Latest

$script:Stage17Workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$script:Stage17Backend = Join-Path $script:Stage17Workspace '12_AUTHORITY_BACKEND_STAGE17'
$script:Stage17Runtime = Join-Path $script:Stage17Workspace 'STAGE17_RUNTIME_STATE'
$script:Stage17ProcessRecord = Join-Path $script:Stage17Runtime 'authority_backend_process.json'
$script:Stage17Host = '127.0.0.1'
$script:Stage17Port = 8000
$script:Stage17HealthUri = "http://$script:Stage17Host`:$script:Stage17Port/health"
$script:Stage17ExpectedMasterSha256 = '6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'

function Get-Stage17ListenerPids {
    $pids = @()
    try {
        $connections = @(Get-NetTCPConnection -LocalPort $script:Stage17Port -State Listen -ErrorAction Stop)
        foreach ($connection in $connections) {
            if ($connection.LocalAddress -in @($script:Stage17Host, '0.0.0.0', '::', '::1')) {
                $pids += [int]$connection.OwningProcess
            }
        }
    }
    catch {
        $lines = @(netstat -ano -p tcp 2>$null)
        foreach ($line in $lines) {
            if ($line -match '^\s*TCP\s+(127\.0\.0\.1|0\.0\.0\.0|\[::\]|\[::1\]):8000\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                $pids += [int]$Matches[2]
            }
        }
    }
    return @($pids | Sort-Object -Unique)
}

function Write-Stage17ProcessRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Record)

    New-Item -ItemType Directory -Path $script:Stage17Runtime -Force | Out-Null
    $temporary = "$script:Stage17ProcessRecord.tmp"
    $Record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $script:Stage17ProcessRecord -Force
}

function Read-Stage17ProcessRecord {
    if (-not (Test-Path -LiteralPath $script:Stage17ProcessRecord)) {
        return $null
    }
    return Get-Content -LiteralPath $script:Stage17ProcessRecord -Raw | ConvertFrom-Json
}

function Test-Stage17OwnedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedPython,
        [Parameter(Mandatory = $true)][object]$ExpectedStartTimeUtc
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    $actualPath = $process.Path
    if ([string]::IsNullOrWhiteSpace($actualPath)) {
        return $false
    }
    if (-not [string]::Equals(
        [IO.Path]::GetFullPath($actualPath),
        [IO.Path]::GetFullPath($ExpectedPython),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        return $false
    }
    if ($ExpectedStartTimeUtc -is [DateTime]) {
        $expectedStart = ([DateTime]$ExpectedStartTimeUtc).ToUniversalTime()
    }
    else {
        $expectedStart = [DateTimeOffset]::Parse(
            [string]$ExpectedStartTimeUtc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).UtcDateTime
    }
    $actualStart = $process.StartTime.ToUniversalTime()
    return [Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -le 2.0
}
