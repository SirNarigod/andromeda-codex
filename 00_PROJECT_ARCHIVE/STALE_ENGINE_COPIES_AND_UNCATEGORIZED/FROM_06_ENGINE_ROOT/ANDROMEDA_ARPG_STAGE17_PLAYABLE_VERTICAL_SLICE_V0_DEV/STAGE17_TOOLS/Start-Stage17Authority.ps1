[CmdletBinding()]
param(
    [string]$PythonPath = $(
        if ($env:ANDROMEDA_STAGE17_PYTHON) { $env:ANDROMEDA_STAGE17_PYTHON }
        else { 'C:\Users\thall\ANDROMEDA_PRODUCT\.venv\Scripts\python.exe' }
    ),
    [string]$MasterRelease = $(
        if ($env:ANDROMEDA_MASTER_RELEASE) { $env:ANDROMEDA_MASTER_RELEASE }
        else { 'C:\Users\thall\ANDROMEDA_PRODUCT\ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip' }
    ),
    [ValidateRange(5, 300)][int]$TimeoutSeconds = 90,
    [ValidateRange(100, 5000)][int]$PollIntervalMilliseconds = 500
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Stage17Authority.Common.ps1')

function Set-TemporaryEnvironment {
    param([hashtable]$Values)
    $previous = @{}
    foreach ($name in $Values.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], 'Process')
    }
    return $previous
}

function Restore-TemporaryEnvironment {
    param([hashtable]$Previous)
    foreach ($name in $Previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $Previous[$name], 'Process')
    }
}

$startedProcess = $null
$ownedBackendProcess = $null
$record = @{
    schema = 'ANDROMEDA_STAGE17_AUTHORITY_PROCESS_V0_1_0_DEV'
    state = 'STARTING'
    workspace = $script:Stage17Workspace
    backend_path = $script:Stage17Backend
    runtime_state = $script:Stage17Runtime
    host = $script:Stage17Host
    port = $script:Stage17Port
    workers = 1
    health_uri = $script:Stage17HealthUri
    requested_at = (Get-Date).ToUniversalTime().ToString('o')
}

try {
    Write-Host 'STAGE17_AUTHORITY: STARTING'
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "PYTHON_NOT_FOUND: $PythonPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $script:Stage17Backend 'stage16b_authority_api.py') -PathType Leaf)) {
        throw "STAGE17_BACKEND_ENTRYPOINT_NOT_FOUND: $script:Stage17Backend"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $script:Stage17Workspace '01_RUNTIME') -PathType Container)) {
        throw "STAGE16A_RUNTIME_DEPENDENCY_NOT_FOUND"
    }
    if (-not (Test-Path -LiteralPath $MasterRelease -PathType Leaf)) {
        throw "MASTER_RELEASE_NOT_FOUND: $MasterRelease"
    }
    $masterHash = (Get-FileHash -LiteralPath $MasterRelease -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($masterHash -ne $script:Stage17ExpectedMasterSha256) {
        throw "MASTER_RELEASE_HASH_MISMATCH: $masterHash"
    }
    $listenersBefore = @(Get-Stage17ListenerPids)
    if ($listenersBefore.Count -gt 0) {
        throw "PORT_8000_ALREADY_IN_USE_BY_PID: $($listenersBefore -join ',')"
    }

    $basePythonPath = (& $PythonPath -c "import sys; print(sys._base_executable)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $basePythonPath -PathType Leaf)) {
        throw "PYTHON_BASE_EXECUTABLE_VALIDATION_FAILED"
    }
    & $PythonPath -c "import fastapi, uvicorn; print(f'{fastapi.__version__}|{uvicorn.__version__}')" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PYTHON_FASTAPI_UVICORN_VALIDATION_FAILED: exit=$LASTEXITCODE"
    }

    $authorityState = Join-Path $script:Stage17Runtime 'authority'
    $saveRoot = Join-Path $script:Stage17Runtime 'saves'
    $logRoot = Join-Path $script:Stage17Runtime 'logs'
    New-Item -ItemType Directory -Path $authorityState -Force | Out-Null
    New-Item -ItemType Directory -Path $saveRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $stdoutPath = Join-Path $logRoot 'authority_stdout.log'
    $stderrPath = Join-Path $logRoot 'authority_stderr.log'

    $environment = @{
        ANDROMEDA_MASTER_RELEASE = (Resolve-Path -LiteralPath $MasterRelease).Path
        ANDROMEDA_S16B_VAR = $authorityState
        ANDROMEDA_S16B_DB = (Join-Path $authorityState 'stage17_world.sqlite')
        ANDROMEDA_S16B_SAVE_ROOT = $saveRoot
        ANDROMEDA_S16B_OWNER_SCOPE = 'stage17:playable-v0-dev'
        ANDROMEDA_S16B_SEED = '160800'
        ANDROMEDA_S16B_DEV_PROFILE_BOOTSTRAP = '1'
        ANDROMEDA_S17_RESOURCE_PLACEMENT_MANIFEST = (Join-Path $script:Stage17Workspace 'STAGE17_CONTENT\RESOURCE_PLACEMENT\CANONICAL\S17_RESOURCE_METRIC_PLACEMENTS_R0001.json')
        PYTHONDONTWRITEBYTECODE = '1'
    }
    $launchNotBeforeUtc = (Get-Date).ToUniversalTime()
    $previousEnvironment = Set-TemporaryEnvironment $environment
    try {
        $startArguments = @{
            FilePath = (Resolve-Path -LiteralPath $PythonPath).Path
            ArgumentList = @('-m', 'uvicorn', 'stage16b_authority_api:app', '--host', $script:Stage17Host, '--port', "$script:Stage17Port", '--workers', '1')
            WorkingDirectory = $script:Stage17Backend
            RedirectStandardOutput = $stdoutPath
            RedirectStandardError = $stderrPath
            WindowStyle = 'Hidden'
            PassThru = $true
        }
        $startedProcess = Start-Process @startArguments
    }
    finally {
        Restore-TemporaryEnvironment $previousEnvironment
    }

    $startedProcess.Refresh()
    $record.launcher_pid = $startedProcess.Id
    $record.requested_python_path = (Resolve-Path -LiteralPath $PythonPath).Path
    $record.python_path = (Resolve-Path -LiteralPath $basePythonPath).Path
    $record.launcher_start_time_utc = $startedProcess.StartTime.ToUniversalTime().ToString('o')
    $record.stdout = $stdoutPath
    $record.stderr = $stderrPath
    $record.command = '-m uvicorn stage16b_authority_api:app --host 127.0.0.1 --port 8000 --workers 1'
    $record.runtime_environment = $environment
    Write-Stage17ProcessRecord $record

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $health = $null
    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $candidate = Invoke-RestMethod -Uri $script:Stage17HealthUri -Method Get -TimeoutSec 5
            if ($candidate.status -eq 'PASS') {
                $listenerPids = @(Get-Stage17ListenerPids)
                if ($listenerPids.Count -ne 1) {
                    throw "LISTENER_COUNT_MISMATCH: expected=1 actual=$($listenerPids -join ',')"
                }
                $listenerProcess = Get-Process -Id $listenerPids[0] -ErrorAction Stop
                $listenerPath = $listenerProcess.Path
                $listenerStartUtc = $listenerProcess.StartTime.ToUniversalTime()
                if ([string]::IsNullOrWhiteSpace($listenerPath) -or -not [string]::Equals(
                    [IO.Path]::GetFullPath($listenerPath),
                    [IO.Path]::GetFullPath($basePythonPath),
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                    throw "LISTENER_EXECUTABLE_MISMATCH: expected=$basePythonPath actual=$listenerPath"
                }
                if ($listenerStartUtc -lt $launchNotBeforeUtc.AddSeconds(-2)) {
                    throw "LISTENER_PREDATES_LAUNCH: pid=$($listenerProcess.Id)"
                }
                if ($null -eq $listenerProcess.Parent -or $listenerProcess.Parent.Id -ne $startedProcess.Id) {
                    $actualParent = if ($null -eq $listenerProcess.Parent) { 'NONE' } else { [string]$listenerProcess.Parent.Id }
                    throw "LISTENER_PARENT_MISMATCH: expected=$($startedProcess.Id) actual=$actualParent"
                }
                if ([string]$candidate.service -ne 'ANDROMEDA_STAGE16B_AUTHORITY_ADAPTER') {
                    throw "HEALTH_SERVICE_IDENTITY_MISMATCH: $($candidate.service)"
                }
                $ownedBackendProcess = $listenerProcess
                $health = $candidate
                break
            }
        }
        catch {
            if ($_.Exception.Message -match '^(LISTENER_|HEALTH_SERVICE_IDENTITY_)') {
                throw
            }
        }
        Start-Sleep -Milliseconds $PollIntervalMilliseconds
    }
    $stopwatch.Stop()
    if ($null -eq $health) {
        throw "HEALTH_TIMEOUT_AFTER_SECONDS: $TimeoutSeconds"
    }

    $record.state = 'READY'
    $record.pid = $ownedBackendProcess.Id
    $record.process_start_time_utc = $ownedBackendProcess.StartTime.ToUniversalTime().ToString('o')
    $record.ready_at = (Get-Date).ToUniversalTime().ToString('o')
    $record.startup_duration_ms = [Math]::Round($stopwatch.Elapsed.TotalMilliseconds, 3)
    $record.health = $health
    $record.listener_pid = $ownedBackendProcess.Id
    $record.listener_parent_pid = $startedProcess.Id
    $record.launcher_process_exited_after_spawn = $startedProcess.HasExited
    Write-Stage17ProcessRecord $record
    Write-Host "STAGE17_AUTHORITY: READY pid=$($ownedBackendProcess.Id) startup_ms=$($record.startup_duration_ms)"
    exit 0
}
catch {
    $record.state = 'FAILED'
    $record.failed_at = (Get-Date).ToUniversalTime().ToString('o')
    $record.failure = $_.Exception.Message
    if ($null -ne $ownedBackendProcess -and -not $ownedBackendProcess.HasExited) {
        Stop-Process -Id $ownedBackendProcess.Id -ErrorAction SilentlyContinue
        $ownedBackendProcess.WaitForExit(10000) | Out-Null
    }
    if ($null -ne $startedProcess -and -not $startedProcess.HasExited) {
        Stop-Process -Id $startedProcess.Id -ErrorAction SilentlyContinue
        $startedProcess.WaitForExit(10000) | Out-Null
    }
    Write-Stage17ProcessRecord $record
    Write-Error "STAGE17_AUTHORITY: FAILED $($_.Exception.Message)"
    exit 1
}
