import json
import os
import sys
from pathlib import Path

from zpl import DEFAULT_RESTORE_MODE, RESTORE_MODES

# Default backend based on platform
_default_backend = "windows" if sys.platform == "win32" else "cups"

# Origins allowed to reach the routes that print or change settings. The
# service listens on loopback, but loopback is reachable from any page the
# browser happens to have open — without this list any site a lab PC visits
# could print through it or rewrite its settings.
#
# This must list every origin the ReLIMS front ends are served from, or
# printing simply stops: the browser sends the SPA's own origin on a fetch to
# localhost:5577. A workstation served from somewhere not listed here needs it
# added to `allowed_origins` in its config.json.
DEFAULT_ALLOWED_ORIGINS = [
    # The settings page this service serves itself.
    "http://localhost:5577",
    "http://127.0.0.1:5577",
    # Production.
    "https://labserve.net",
    "https://www.labserve.net",
    "https://www.it-mu.co.za",
    "https://apps.it-mu.co.za",
    # Staging / test.
    "https://staging.labserve.net",
    "https://staging.it-mu.co.za",
    "https://test.labserve.net",
    "https://test.it-mu.co.za",
    "https://clientschange.labserve.net",
] + [
    # Local dev servers, per each app's vite.config.ts `server.port`:
    # 5001 timestamp, 5002 filemanager, 5003 client-portal, 5004 kiosk,
    # 5010 lims, 5013 mule, 5021 qims, 5173 legacy client-portal.
    f"http://{host}:{port}"
    for port in (5001, 5002, 5003, 5004, 5010, 5013, 5021, 5173)
    for host in ("localhost", "127.0.0.1")
]

DEFAULT_CONFIG = {
    "printer_name": "",
    "printer_host": "",
    "printer_port": 9100,
    "backend": _default_backend,
    "api_port": 5577,
    "timeout": 5,
    "label_offset_x": 0,
    "label_offset_y": 0,
    "label_origin_x": 0,
    "label_origin_y": 0,
    # Measured label size in dots. label_width also feeds ^PW: content shifted
    # right by label_origin_x needs a print width that covers the offset too.
    "label_width": 0,
    "label_height": 0,
    "label_darkness": 0,
    # How a job hands the printer back to whatever else prints on it. See
    # zpl.build_restore_epilogue.
    "printer_restore_mode": DEFAULT_RESTORE_MODE,
    "allowed_origins": list(DEFAULT_ALLOWED_ORIGINS),
}

# Settings a POST /config may write. Kept here rather than in the two app
# modules so Windows and Linux can never accept different fields.
WRITABLE_KEYS = {
    "printer_name", "printer_host", "printer_port", "backend", "api_port", "timeout",
    "label_offset_x", "label_offset_y",
    "label_origin_x", "label_origin_y", "label_width", "label_height",
    "label_darkness", "printer_restore_mode",
}

# Deliberately NOT writable over HTTP, and so absent from WRITABLE_KEYS: the
# allowlist is what stops an untrusted page reaching these routes at all, and a
# route that could rewrite it would guard nothing. Edit config.json to change it.


# Settings a single print job may override without saving them, so Test Print
# can use what is on screen. `api_port` is deliberately absent — the port the
# service listens on means nothing to a job already in flight.
PRINT_OVERRIDE_KEYS = WRITABLE_KEYS - {"api_port"}

_INT_KEYS = {
    "printer_port", "api_port", "timeout", "label_offset_x", "label_offset_y",
    "label_origin_x", "label_origin_y", "label_width", "label_height",
    "label_darkness",
}


def filter_config_payload(data, allowed=None):
    """Reduce an untrusted body to known settings, with ints coerced.

    Values that cannot be read as ints are dropped rather than raising, so one
    bad field in a request never costs the caller the rest of them.
    """
    allowed = WRITABLE_KEYS if allowed is None else allowed
    filtered = {k: v for k, v in (data or {}).items() if k in allowed}
    for key in _INT_KEYS & filtered.keys():
        try:
            filtered[key] = int(filtered[key])
        except (TypeError, ValueError):
            del filtered[key]
    # Same "drop it rather than raise" treatment for the one enum we accept.
    # Dropping leaves the saved value in place, which is safer than storing a
    # mode the epilogue builder would have to guess at.
    mode = filtered.get("printer_restore_mode")
    if mode is not None and (not isinstance(mode, str) or mode.lower() not in RESTORE_MODES):
        del filtered["printer_restore_mode"]
    elif mode is not None:
        filtered["printer_restore_mode"] = mode.lower()
    return filtered


def get_allowed_origins(cfg=None):
    """Origins permitted to print or change settings, from config."""
    cfg = load_config() if cfg is None else cfg
    origins = cfg.get("allowed_origins")
    if not isinstance(origins, list):
        return list(DEFAULT_ALLOWED_ORIGINS)
    cleaned = [o for o in origins if isinstance(o, str) and o]
    return cleaned or list(DEFAULT_ALLOWED_ORIGINS)


def get_config_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "."))
    else:
        base = Path.home() / ".config"
    config_dir = base / "ReLIMS Print Service"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_config():
    path = get_config_path()
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            with open(path, "r") as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(data):
    config = load_config()
    config.update(data)
    path = get_config_path()
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    return config
