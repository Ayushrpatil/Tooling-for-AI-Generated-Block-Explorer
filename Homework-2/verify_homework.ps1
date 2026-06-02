$ErrorActionPreference = "SilentlyContinue"

function Write-Status {
    param(
        [string]$Area,
        [string]$Status,
        [string]$Detail
    )

    "{0,-10} {1,-8} {2}" -f $Area, $Status, $Detail
}

Write-Output "INFO7500 Homework 2 verification"
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
    Write-Status "OpenAI" "MISSING" "OPENAI_API_KEY is not set."
}

$bitcoinDataDir = Join-Path $env:LOCALAPPDATA "Bitcoin"
$bitcoinConf = Join-Path $bitcoinDataDir "bitcoin.conf"
$bitcoinDebugLog = Join-Path $bitcoinDataDir "debug.log"

if (Test-Path $bitcoinConf) {
    Write-Status "Bitcoin" "OK" "Found bitcoin.conf at $bitcoinConf"
} else {
    Write-Status "Bitcoin" "MISSING" "bitcoin.conf not found at $bitcoinConf"
}

if (Test-Path $bitcoinDebugLog) {
    Write-Status "debug.log" "OK" "Found debug.log at $bitcoinDebugLog"
} else {
    Write-Status "debug.log" "MISSING" "debug.log not found at $bitcoinDebugLog"
}

$candidateBins = @(
    "C:\bitcoin-core-install\bin\bitcoin-cli.exe",
    "C:\bitcoin-core-install\bin\bitcoind.exe",
    "C:\src\bitcoin\build\src\bitcoin-cli.exe",
    "C:\src\bitcoin\build\src\bitcoind.exe"
)

$foundBins = $candidateBins | Where-Object { Test-Path $_ }
if ($foundBins.Count -gt 0) {
    Write-Status "Binaries" "OK" ($foundBins -join ", ")
} else {
    Write-Status "Binaries" "MISSING" "No expected Bitcoin Core binaries found in the common locations."
}

Write-Output ""
Write-Output "Next checks to run manually:"
Write-Output "1. docker build -t info7500-docker-demo ."
Write-Output "2. docker run --rm info7500-docker-demo"
Write-Output '3. python openai_text_to_sql.py --schema-file sample_blockchain_schema.sql --question "How many blocks are in the blocks table?"'
Write-Output "4. bitcoin-cli.exe getblockhash 0"
