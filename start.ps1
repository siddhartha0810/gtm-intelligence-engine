# Oracle Intelligence Platform — PowerShell Startup Script
# Run from DATA TOOL root: .\start.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Oracle Intelligence Platform — Startup    " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# --- Resolve Python ---
$PythonCmd = $null
if (Test-Path "$Root\venv\Scripts\python.exe") {
    $PythonCmd = "$Root\venv\Scripts\python.exe"
} elseif (Test-Path "C:\Program Files\Python311\python.exe") {
    $PythonCmd = "C:\Program Files\Python311\python.exe"
} else {
    Write-Error "Cannot find Python 3.11. Install it or run setup.bat first."
    exit 1
}
Write-Host "Python: $PythonCmd" -ForegroundColor Green

# --- Init DB schema ---
Write-Host "Initialising database schema..." -ForegroundColor Yellow
try {
    & $PythonCmd -c "import sys; sys.path.insert(0,'oracle_intent_engine'); from src import database; database.init_db()" 2>$null
} catch { }

# --- Backend ---
Write-Host "Starting backend on http://localhost:8000 ..." -ForegroundColor Yellow
$BackendArgs = @("-m", "uvicorn", "unified_app:app", "--reload", "--port", "8000")
$Backend = Start-Process -FilePath $PythonCmd `
    -ArgumentList $BackendArgs `
    -WorkingDirectory $Root `
    -PassThru `
    -NoNewWindow:$false

# --- Frontend ---
if (Test-Path "$Root\frontend\package.json") {
    Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Yellow
    $Frontend = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/k", "cd /d `"$Root\frontend`" && npm run dev" `
        -PassThru
} else {
    Write-Host "WARNING: frontend\package.json not found — skipping." -ForegroundColor Red
}

Write-Host ""
Write-Host "Backend PID:  $($Backend.Id)" -ForegroundColor Green
Write-Host "Frontend URL: http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C or close this window to stop." -ForegroundColor Gray
$Backend | Wait-Process
