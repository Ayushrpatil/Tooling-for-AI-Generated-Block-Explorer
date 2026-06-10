param(
    [string]$SqliteDb = "",
    [string]$RpcCookieFile = ""
)

$ErrorActionPreference = "SilentlyContinue"

function Write-Status {
    param(
        [string]$Area,
        [string]$Status,
        [string]$Detail
    )

    "{0,-14} {1,-8} {2}" -f $Area, $Status, $Detail
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SqliteDb) {
    $SqliteDb = Join-Path $scriptRoot "bitcoin-homework3.sqlite"
}
if (-not $RpcCookieFile) {
    $RpcCookieFile = Join-Path $scriptRoot "..\bitcoin-data\.cookie"
}

Write-Output "INFO7500 Homework 3 verification"
Write-Output ""

$dockerServer = docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -eq 0 -and $dockerServer) {
    Write-Status "Docker" "OK" "Engine reachable. Server version: $dockerServer"
} else {
    Write-Status "Docker" "MISSING" "Docker engine is not reachable. Start Docker Desktop and retry."
}

if (Test-Path Env:OPENAI_API_KEY) {
    Write-Status "OpenAI" "OK" "OPENAI_API_KEY is set for this shell session."
} else {
    Write-Status "OpenAI" "MISSING" "OPENAI_API_KEY is not set in this shell session."
}

$requiredFiles = @(
    (Join-Path $scriptRoot "bitcoin_schema.sql"),
    (Join-Path $scriptRoot "bitcoin_rpc.py"),
    (Join-Path $scriptRoot "sync_bitcoin_to_sqlite.py"),
    (Join-Path $scriptRoot "bitcoin_sync_status.py"),
    (Join-Path $scriptRoot "bitcoin_text_to_sql.py"),
    (Join-Path $scriptRoot "run_text_to_sql_tests.py"),
    (Join-Path $scriptRoot "test_cases.json"),
    (Join-Path $scriptRoot "hard_test_cases.json"),
    (Join-Path $scriptRoot "rejection_test_cases.json")
)

$missingFiles = $requiredFiles | Where-Object { -not (Test-Path $_) }
if ($missingFiles.Count -eq 0) {
    Write-Status "Files" "OK" "All Homework 3 deliverables are present."
} else {
    Write-Status "Files" "MISSING" ($missingFiles -join ", ")
}

if (Test-Path $SqliteDb) {
    Write-Status "SQLite DB" "OK" "Found $SqliteDb"
} else {
    Write-Status "SQLite DB" "MISSING" "Expected at $SqliteDb"
}

if (Test-Path $RpcCookieFile) {
    Write-Status "RPC cookie" "OK" "Found $RpcCookieFile"
} else {
    Write-Status "RPC cookie" "MISSING" "Expected at $RpcCookieFile"
}

$statusScript = Join-Path $scriptRoot "bitcoin_sync_status.py"
if ((Test-Path $statusScript) -and (Test-Path $RpcCookieFile)) {
    $statusOutput = python $statusScript --sqlite-db $SqliteDb --rpc-cookie-file $RpcCookieFile 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Node status" "OK" "bitcoin_sync_status.py ran successfully."
        Write-Output ""
        Write-Output "Current node/database status:"
        Write-Output $statusOutput
    } else {
        Write-Status "Node status" "WARN" "bitcoin_sync_status.py did not complete successfully."
    }
}

Write-Output ""
Write-Output "Suggested next commands:"
Write-Output "1. python .\Homework-3\sync_bitcoin_to_sqlite.py --sqlite-db $SqliteDb --rpc-cookie-file $RpcCookieFile --poll-interval-seconds 300"
Write-Output "2. python .\Homework-3\bitcoin_text_to_sql.py --sqlite-db $SqliteDb --question `"How many blocks are stored in the database?`""
Write-Output "3. python .\Homework-3\run_text_to_sql_tests.py --sqlite-db $SqliteDb"
