import json
import os
import sys
from pathlib import Path

# Default backend based on platform
_default_backend = "windows" if sys.platform == "win32" else "cups"

DEFAULT_CONFIG = {
    "printer_name": "",
    "printer_host": "",
    "printer_port": 9100,
    "backend": _default_backend,
    "api_port": 5577,
    "timeout": 5,
}


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
