@echo off
echo ============================================
echo   ReLIMS Print Manager - Uninstall
echo ============================================
echo.

:: Kill running processes
taskkill /f /im relims-print-manager.exe >nul 2>&1
taskkill /f /im relims-print-service.exe >nul 2>&1
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq *print*" >nul 2>&1

:: Remove auto-start registry keys (both old and new)
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ReLIMS Print Manager" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ReLIMS Print Service" /f >nul 2>&1
echo Removed auto-start entries.

:: Remove Start Menu shortcuts (both old and new)
set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs
if exist "%STARTMENU%\ReLIMS Print Manager" rmdir /s /q "%STARTMENU%\ReLIMS Print Manager" 2>nul
if exist "%STARTMENU%\ReLIMS" rmdir /s /q "%STARTMENU%\ReLIMS" 2>nul
echo Removed Start Menu shortcuts.

:: Remove install directories (both old and new)
set INSTALL_DIR=%LOCALAPPDATA%\ReLIMS Print Manager
if exist "%INSTALL_DIR%" (
    rmdir /s /q "%INSTALL_DIR%"
    echo Removed install directory: %INSTALL_DIR%
)
set OLD_INSTALL_DIR=%LOCALAPPDATA%\ReLIMS Print Service
if exist "%OLD_INSTALL_DIR%" (
    rmdir /s /q "%OLD_INSTALL_DIR%"
    echo Removed old install directory: %OLD_INSTALL_DIR%
)

echo.
echo Uninstall complete.
echo.
pause
