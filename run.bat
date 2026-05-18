@echo off
cd /d "%~dp0"

echo ============================================================
echo   DATA TOOL  -  Unified Sales Intelligence Platform
echo ============================================================
echo   Oracle Intent Engine   -^>  http://localhost:8080/
echo   Lead Enrichment        -^>  http://localhost:8080/enrichment/
echo ============================================================
echo.

call "%~dp0venv\Scripts\activate.bat" 2>nul || (
    echo [ERROR] Virtual environment not found.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

python "%~dp0main.py"
pause
