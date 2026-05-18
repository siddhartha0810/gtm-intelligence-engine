@echo off
cd /d "%~dp0"

echo ============================================================
echo   DATA TOOL  —  First-Time Setup
echo ============================================================
echo.

python --version >nul 2>&1 || (
    echo [ERROR] Python not found. Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
python -m venv venv

echo [2/3] Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo [3/3] Done!
echo.
echo ============================================================
echo   Setup complete. Run  run.bat  to start the application.
echo ============================================================
pause
