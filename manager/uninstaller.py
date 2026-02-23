"""Uninstall logic for the ReLIMS Print Manager on Windows and Linux."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from paths import get_install_dir, get_config_dir


def uninstall_windows(keep_config=False):
    """Full uninstall on Windows.

    - Stops the print service
    - Removes auto-start registry entry
    - Removes Start Menu shortcuts
    - Spawns a cleanup script to delete the install directory after this process exits
    """
    from service_control import stop_service

    # Stop the print service
    stop_service()

    # Remove registry auto-start entry
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, "ReLIMS Print Manager")
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:
        pass

    # Remove Start Menu shortcuts
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ReLIMS Print Manager"
    if start_menu.exists():
        shutil.rmtree(start_menu, ignore_errors=True)

    # Remove config if requested
    if not keep_config:
        config_dir = get_config_dir()
        if config_dir.exists():
            shutil.rmtree(config_dir, ignore_errors=True)

    # Create self-destruct batch file that waits for us to exit, then deletes everything
    install_dir = get_install_dir()
    cleanup_bat = Path(tempfile.gettempdir()) / "relims_cleanup.bat"
    pid = os.getpid()

    with open(cleanup_bat, "w") as f:
        f.write(f"""@echo off
:wait
tasklist /fi "PID eq {pid}" 2>nul | find /i "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
timeout /t 2 /nobreak >nul
rmdir /s /q "{install_dir}"
del "%~f0"
""")

    subprocess.Popen(
        ["cmd", "/c", str(cleanup_bat)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )

    sys.exit(0)


def uninstall_linux(keep_config=False):
    """Full uninstall on Linux.

    - Stops and disables the systemd user service
    - Removes systemd service file
    - Removes XDG autostart and .desktop files
    - Removes the install directory
    - Optionally removes config
    """
    from service_control_linux import stop_service, disable_service, daemon_reload

    SERVICE_NAME = "relims-print-service"

    # Stop and disable systemd service
    stop_service()
    disable_service()

    # Remove systemd service file
    service_file = Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"
    if service_file.exists():
        service_file.unlink()
        daemon_reload()

    # Remove XDG autostart entry
    autostart = Path.home() / ".config" / "autostart" / "relims-print-manager.desktop"
    if autostart.exists():
        autostart.unlink()

    # Remove .desktop file from applications
    desktop_file = Path.home() / ".local" / "share" / "applications" / "relims-print-manager.desktop"
    if desktop_file.exists():
        desktop_file.unlink()

    # Remove config if requested
    if not keep_config:
        config_dir = get_config_dir()
        if config_dir.exists():
            shutil.rmtree(config_dir, ignore_errors=True)

    # Remove install directory
    install_dir = get_install_dir()
    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)

    print("ReLIMS Print Manager has been uninstalled.")
    sys.exit(0)
