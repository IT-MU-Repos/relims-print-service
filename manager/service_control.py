"""Windows service lifecycle management for the print service."""
import json
import os
import subprocess
import urllib.request

from paths import get_service_binary_path, get_pid_file_path, get_service_url


def _save_pid(pid: int):
    pid_file = get_pid_file_path()
    pid_file.write_text(str(pid))


def _load_pid() -> int | None:
    pid_file = get_pid_file_path()
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _clear_pid():
    pid_file = get_pid_file_path()
    if pid_file.exists():
        pid_file.unlink(missing_ok=True)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_service_running() -> bool:
    """Check if the print service is running (PID check + HTTP health check)."""
    pid = _load_pid()
    if pid and _is_pid_alive(pid):
        # Double-check with HTTP health
        try:
            with urllib.request.urlopen(get_service_url("/status"), timeout=2) as resp:
                data = json.loads(resp.read())
                return data.get("status") == "ok"
        except Exception:
            return True  # PID alive but HTTP not responding yet
    # No PID file -- try HTTP as fallback (service may have been started externally)
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
    """Start the print service as a detached subprocess."""
    if is_service_running():
        return True

    service_bin = get_service_binary_path()
    if not service_bin.exists():
        return False

    try:
        proc = subprocess.Popen(
            [str(service_bin)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        _save_pid(proc.pid)
        return True
    except OSError:
        return False


def stop_service() -> bool:
    """Stop the print service."""
    pid = _load_pid()
    if pid and _is_pid_alive(pid):
        try:
            # Use taskkill for clean shutdown on Windows
            subprocess.run(
                ["taskkill", "/f", "/pid", str(pid)],
                capture_output=True,
                timeout=10,
            )
            _clear_pid()
            return True
        except Exception:
            pass

    # Fallback: kill by process name
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "relims-print-service.exe"],
            capture_output=True,
            timeout=10,
        )
        _clear_pid()
        return True
    except Exception:
        return False


def restart_service() -> bool:
    """Stop and restart the print service."""
    stop_service()
    import time
    time.sleep(1)
    return start_service()
