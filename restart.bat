@echo off
title Restarting Oracle Intelligence Platform...
cd /d "%~dp0"

echo Stopping existing server...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTEN"') do (
    taskkill /PID %%p /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo Starting server with latest code...
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    echo ERROR: venv not found. Run setup.bat first.
    pause & exit /b 1
)

REM Environment is loaded by the Python app via python-dotenv

echo.
echo ============================================
echo  Oracle Intelligence Platform
echo  http://localhost:8000
echo ============================================
echo  Press Ctrl+C to stop
echo ============================================
echo.

"%PYTHON%" -m uvicorn unified_app:app --host 0.0.0.0 --port 8000
