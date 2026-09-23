@echo off
rem TagClip start script for Windows (double-click to run)
chcp 65001 > nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment ... first time only
    py -3 -m venv .venv 2> nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo ERROR: Python was not found. Please install Python - see README.md
        pause
        exit /b 1
    )
)

echo [2/3] Checking required packages ...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install packages. Check your internet connection.
    pause
    exit /b 1
)

if not exist ".venv\browser_ready.txt" (
    echo [3/3] Downloading browser for JavaScript pages ... first time only, a few minutes
    ".venv\Scripts\python.exe" -m playwright install chromium && echo ok> ".venv\browser_ready.txt"
    if not exist ".venv\browser_ready.txt" echo WARNING: Browser download failed. Edge will be used instead if available.
)

".venv\Scripts\python.exe" app.py
pause
