@echo off
echo ============================================
echo   ReLIMS Print Service - Uninstall
echo ============================================
echo.

:: Kill running service
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq *print*" >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq *print*" >nul 2>&1

:: Remove auto-start registry key
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ReLIMS Print Service" /f >nul 2>&1
echo Removed auto-start entry.

:: Remove Start Menu shortcut
set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs
if exist "%STARTMENU%\ReLIMS\ReLIMS Print Service.vbs" del "%STARTMENU%\ReLIMS\ReLIMS Print Service.vbs"
if exist "%STARTMENU%\ReLIMS" rmdir "%STARTMENU%\ReLIMS" 2>nul
echo Removed Start Menu shortcut.

:: Remove install directory
set INSTALL_DIR=%LOCALAPPDATA%\ReLIMS Print Service
if exist "%INSTALL_DIR%" (
    rmdir /s /q "%INSTALL_DIR%"
    echo Removed install directory.
)

echo.
echo Uninstall complete.
echo.
pause
