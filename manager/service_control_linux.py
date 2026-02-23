"""Linux service lifecycle management using systemd user services."""
import json
import subprocess
import urllib.request

from paths import get_service_url

SERVICE_NAME = "relims-print-service"


def _systemctl(*args) -> subprocess.CompletedProcess:
    """Run a systemctl --user command."""
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        timeout=15,
    )


def is_service_running() -> bool:
    """Check if the print service systemd unit is active."""
    result = _systemctl("is-active", SERVICE_NAME)
    if result.stdout.decode().strip() == "active":
        return True
    # Fallback: try HTTP health check
    try:
        with urllib.request.urlopen(get_service_url("/status"), timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def get_service_version() -> str:
    """Get the running service's version via its /status endpoint."""
    try:
        with urllib.request.urlopen(get_service_url("/status"), timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("version", "unknown")
    except Exception:
        return "unknown"


def start_service() -> bool:
    """Start the print service via systemd."""
    result = _systemctl("start", SERVICE_NAME)
    return result.returncode == 0


def stop_service() -> bool:
    """Stop the print service via systemd."""
    result = _systemctl("stop", SERVICE_NAME)
    return result.returncode == 0


def restart_service() -> bool:
    """Restart the print service via systemd."""
    result = _systemctl("restart", SERVICE_NAME)
    return result.returncode == 0


def is_service_enabled() -> bool:
    """Check if the service is enabled to start on login."""
    result = _systemctl("is-enabled", SERVICE_NAME)
    return result.stdout.decode().strip() == "enabled"


def enable_service() -> bool:
    """Enable the service to start on login."""
    result = _systemctl("enable", SERVICE_NAME)
    return result.returncode == 0


def disable_service() -> bool:
    """Disable the service from starting on login."""
    result = _systemctl("disable", SERVICE_NAME)
    return result.returncode == 0


def daemon_reload() -> bool:
    """Reload systemd daemon (after changing service files)."""
    result = _systemctl("daemon-reload")
    return result.returncode == 0
