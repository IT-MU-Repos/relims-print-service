"""Platform-specific paths for the ReLIMS Print Manager."""
import json
import os
import sys
from pathlib import Path

DEFAULT_API_PORT = 5577


def get_install_dir() -> Path:
    """Get the installation directory for the manager and service binaries."""
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", ".")) / "ReLIMS Print Manager"
    return Path.home() / ".local" / "share" / "relims-print-manager"


def get_config_dir() -> Path:
    """Get the config directory (shared with the print service for backward compat)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "."))
    else:
        base = Path.home() / ".config"
    config_dir = base / "ReLIMS Print Service"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_staging_dir() -> Path:
    """Get the staging directory for downloaded updates."""
    staging = get_install_dir() / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def get_manager_state_path() -> Path:
    """Get the path to the manager state file (last check, dismissed updates, etc.)."""
    return get_config_dir() / "manager_state.json"


def get_service_binary_name() -> str:
    """Get the service binary filename for the current platform."""
    if sys.platform == "win32":
        return "relims-print-service.exe"
    return "relims-print-service"


def get_manager_binary_name() -> str:
    """Get the manager binary filename for the current platform."""
    if sys.platform == "win32":
        return "relims-print-manager.exe"
    return "relims-print-manager"


def get_self_updater_binary_name() -> str:
    """Get the self-updater binary filename for the current platform."""
    if sys.platform == "win32":
        return "relims-self-updater.exe"
    return "relims-self-updater"


def get_service_binary_path() -> Path:
    """Full path to the service binary."""
    return get_install_dir() / get_service_binary_name()


def get_self_updater_path() -> Path:
    """Full path to the self-updater binary."""
    return get_install_dir() / get_self_updater_binary_name()


def get_pid_file_path() -> Path:
    """Get the path to the service PID file (Windows only, Linux uses systemd)."""
    return get_install_dir() / "service.pid"


def get_service_port() -> int:
    """Read the configured API port from the shared config file."""
    config_path = get_config_dir() / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
                return int(cfg.get("api_port", DEFAULT_API_PORT))
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return DEFAULT_API_PORT


def get_service_url(path: str = "") -> str:
    """Get the full URL to a service endpoint."""
    port = get_service_port()
    return f"http://localhost:{port}{path}"
