@echo off
title Oracle Intelligence Platform
cd /d "%~dp0"

echo ============================================
echo  Oracle Intelligence Platform
echo ============================================

REM --- Resolve Python ---
set PYTHON=
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else if exist "C:\Program Files\Python311\python.exe" (
    set PYTHON=C:\Program Files\Python311\python.exe
) else (
    echo ERROR: Python not found. Install Python 3.11 or run setup.bat.
    pause & exit /b 1
)
echo Python: %PYTHON%

REM --- Build React frontend if dist is missing or outdated ---
if not exist "frontend\dist\index.html" (
    echo Building frontend...
    cd frontend
    call npm install --silent
    call npm run build
    cd ..
    echo Frontend built.
)

echo Starting server on http://localhost:8000 ...
echo.
echo Open your browser at: http://localhost:8000
echo Press Ctrl+C to stop.
echo.

"%PYTHON%" -m uvicorn unified_app:app --host 0.0.0.0 --port 8000
