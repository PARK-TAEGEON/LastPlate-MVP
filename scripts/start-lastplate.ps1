param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$url = 'http://127.0.0.1:8000'
$pythonCandidates = @(
    $env:LASTPLATE_PYTHON,
    (Join-Path $projectRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:USERPROFILE 'Documents\Codex\2026-09-18\files-mentioned-by-the-user-lastplate\work\.venv\Scripts\python.exe')
)
function Test-LastPlateReady {
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        $sites = Invoke-RestMethod -Uri "$url/api/ui/sites" -TimeoutSec 2
        return ($health.status -eq 'ok' -and $sites.default_site -eq 'DEMO-LH')
    } catch { return $false }
}
if (-not (Test-LastPlateReady)) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'run.py'))) { throw 'Keep this script in the scripts folder inside lastplate-mvp.' }
    $pythonPath = $pythonCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $pythonPath) { throw 'Python environment not found. Install requirements into .venv as described in README.md.' }
    $logDirectory = Join-Path $projectRoot 'data'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $errorLog = Join-Path $logDirectory 'lastplate-server-error.log'
    Start-Process -FilePath $pythonPath -ArgumentList 'run.py','--host','127.0.0.1','--port','8000' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'lastplate-server.log') -RedirectStandardError $errorLog | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-LastPlateReady) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        if (Test-Path -LiteralPath $errorLog) { Get-Content -LiteralPath $errorLog -Tail 20 }
        throw "LastPlate did not start. Check $errorLog"
    }
}
if (-not $NoBrowser) { Start-Process "$url/" }
Write-Output "LastPlate is ready: $url/"
