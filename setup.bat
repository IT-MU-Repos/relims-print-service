@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   ReLIMS Print Service - Setup
echo ============================================
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

:: Set install directory
set INSTALL_DIR=%LOCALAPPDATA%\ReLIMS Print Service
echo Installing to: %INSTALL_DIR%
echo.

:: Create install directory
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: Copy files
echo Copying files...
copy /y app.py "%INSTALL_DIR%\" >nul
copy /y printer.py "%INSTALL_DIR%\" >nul
copy /y config.py "%INSTALL_DIR%\" >nul
copy /y requirements.txt "%INSTALL_DIR%\" >nul
if not exist "%INSTALL_DIR%\static" mkdir "%INSTALL_DIR%\static"
copy /y static\index.html "%INSTALL_DIR%\static\" >nul
echo Done.
echo.

:: Install dependencies
echo Installing Python dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r "%INSTALL_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo Done.
echo.

:: Create launcher script
echo Creating launcher...
(
echo @echo off
echo cd /d "%INSTALL_DIR%"
echo start /b pythonw app.py
) > "%INSTALL_DIR%\start-print-service.bat"

:: Create VBS launcher (hidden window, no console flash)
(
echo Set WshShell = CreateObject("WScript.Shell"^)
echo WshShell.Run chr(34^) ^& "%INSTALL_DIR%\start-print-service.bat" ^& chr(34^), 0
echo Set WshShell = Nothing
) > "%INSTALL_DIR%\ReLIMS Print Service.vbs"

:: Add to Start Menu
set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs
if not exist "%STARTMENU%\ReLIMS" mkdir "%STARTMENU%\ReLIMS"
copy /y "%INSTALL_DIR%\ReLIMS Print Service.vbs" "%STARTMENU%\ReLIMS\" >nul
echo Created Start Menu shortcut.

:: Add to auto-start on login
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ReLIMS Print Service" /t REG_SZ /d "wscript.exe \"%INSTALL_DIR%\ReLIMS Print Service.vbs\"" /f >nul 2>&1
echo Configured auto-start with Windows.
echo.

:: Start the service now
echo Starting ReLIMS Print Service...
start "" wscript.exe "%INSTALL_DIR%\ReLIMS Print Service.vbs"

:: Wait a moment then verify
timeout /t 3 /nobreak >nul
echo.

:: Test if service is running
python -c "import urllib.request; urllib.request.urlopen('http://localhost:5577/status', timeout=3); print('Service is running on http://localhost:5577')" 2>nul
if %errorlevel% neq 0 (
    echo Service may still be starting. Open http://localhost:5577 in your browser to check.
)

echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo   The Print Service is now running.
echo   Open http://localhost:5577 to configure your printer.
echo.
echo   It will start automatically when you log in.
echo   To uninstall, run uninstall.bat
echo.
pause
