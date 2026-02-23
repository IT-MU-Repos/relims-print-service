@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   ReLIMS Print Manager - Dev Setup
echo ============================================
echo.
echo This script sets up a development environment.
echo For production, use the installer from GitHub Releases.
echo.

:: Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Show Python version
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo Found: %PYVER%
echo.

:: Install dependencies
echo Installing Python dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet -r requirements-manager.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo Done.
echo.

echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo To run the print service (dev mode):
echo   cd service
echo   python app.py --debug
echo.
echo To run the manager (dev mode):
echo   cd manager
echo   python main.py
echo.
echo Configure your printer at: http://localhost:5577
echo.
pause
