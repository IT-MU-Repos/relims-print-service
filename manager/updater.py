"""Update checker, downloader, and applier for the ReLIMS Print Manager."""
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from packaging.version import Version

from paths import (
    get_install_dir, get_staging_dir, get_service_binary_path,
    get_self_updater_path, get_service_url,
)
from version import VERSION as MANAGER_VERSION

GITHUB_OWNER = "IT-MU-Repos"
GITHUB_REPO = "relims-print-service"
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
CHECK_INTERVAL_SECONDS = 3600  # 1 hour


class UpdateChecker:
    def __init__(self):
        self.latest_release = None
        self.latest_version = None
        self.manifest = None
        self._downloaded_assets = {}

    def check_for_update(self) -> dict | None:
        """Check GitHub Releases API for a newer version.

        Returns a dict with update info if available, None otherwise.
        """
        try:
            req = urllib.request.Request(API_URL)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", f"ReLIMS-Print-Manager/{MANAGER_VERSION}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                release = json.loads(resp.read())
        except Exception:
            return None

        tag = release.get("tag_name", "").lstrip("v")
        if not tag:
            return None

        # Check if this is actually newer
        try:
            if Version(tag) <= Version(MANAGER_VERSION):
                return None
        except Exception:
            if tag == MANAGER_VERSION:
                return None

        self.latest_release = release
        self.latest_version = tag

        # Fetch manifest.json from release assets
        self.manifest = self._fetch_manifest(release)

        current_service = self._get_service_version()
        return {
            "version": tag,
            "current_manager": MANAGER_VERSION,
            "current_service": current_service,
            "needs_service_update": self._needs_update("service", current_service),
            "needs_manager_update": self._needs_update("manager", MANAGER_VERSION),
        }

    def _fetch_manifest(self, release: dict) -> dict | None:
        """Download manifest.json from the release assets."""
        for asset in release.get("assets", []):
            if asset["name"] == "manifest.json":
                try:
                    req = urllib.request.Request(asset["browser_download_url"])
                    req.add_header("User-Agent", f"ReLIMS-Print-Manager/{MANAGER_VERSION}")
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        return json.loads(resp.read())
                except Exception:
                    return None
        return None

    def _get_service_version(self) -> str:
        """Query the running print service for its version."""
        try:
            with urllib.request.urlopen(get_service_url("/status"), timeout=3) as resp:
                data = json.loads(resp.read())
                return data.get("version", "unknown")
        except Exception:
            return "unknown"

    def _needs_update(self, component: str, current: str) -> bool:
        """Check if a specific component needs updating."""
        if current == "unknown":
            return True
        if self.manifest:
            remote = self.manifest.get(
                f"{component}_version", self.latest_version)
        else:
            remote = self.latest_version
        try:
            return Version(remote) > Version(current)
        except Exception:
            return remote != current

    # --- Downloading ---

    def download_update(self, component: str) -> Path | None:
        """Download a component's release asset to the staging directory.

        Args:
            component: "service" or "manager"

        Returns:
            Path to the downloaded file, or None on failure.
        """
        if not self.latest_release:
            return None

        asset_name = self._resolve_asset_name(component)
        if not asset_name:
            return None

        download_url = None
        for asset in self.latest_release.get("assets", []):
            if asset["name"] == asset_name:
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            return None

        staging = get_staging_dir()
        dest = staging / asset_name

        try:
            req = urllib.request.Request(download_url)
            req.add_header("User-Agent", f"ReLIMS-Print-Manager/{MANAGER_VERSION}")
            with urllib.request.urlopen(req, timeout=300) as resp:
                with open(dest, "wb") as f:
                    shutil.copyfileobj(resp, f)
            self._downloaded_assets[component] = dest
            return dest
        except Exception:
            if dest.exists():
                dest.unlink(missing_ok=True)
            return None

    def _resolve_asset_name(self, component: str) -> str | None:
        """Determine the asset filename for a component on this platform."""
        suffix = "windows" if platform.system() == "Windows" else "linux"
        asset_key = f"{component}_{suffix}"

        if self.manifest and "assets" in self.manifest:
            name = self.manifest["assets"].get(asset_key)
            if name:
                return name

        # Fallback: construct expected name
        if suffix == "windows":
            return f"relims-print-{component}.exe"
        return f"relims-print-{component}-linux.tar.gz"

    # --- Applying updates ---

    def apply_service_update(self) -> bool:
        """Stop the service, replace its binary, and restart it.

        Returns True on success, False on failure (with rollback).
        """
        if sys.platform == "win32":
            from service_control import stop_service, start_service
        else:
            from service_control_linux import stop_service, start_service

        staged = self._downloaded_assets.get("service")
        if not staged or not staged.exists():
            return False

        stop_service()
        time.sleep(1)

        target = get_service_binary_path()
        backup = target.with_suffix(target.suffix + ".bak")

        try:
            # Backup current binary
            if target.exists():
                shutil.move(str(target), str(backup))

            # Apply update
            if staged.name.endswith(".tar.gz"):
                with tarfile.open(str(staged)) as tf:
                    # Extract the single binary from the archive
                    members = tf.getmembers()
                    for member in members:
                        if member.isfile():
                            member.name = target.name
                            tf.extract(member, path=target.parent)
                            break
            else:
                shutil.copy2(str(staged), str(target))

            # Make executable on Linux
            if platform.system() != "Windows":
                os.chmod(str(target), 0o755)

            # Clean up
            if backup.exists():
                backup.unlink()
            staged.unlink(missing_ok=True)

        except Exception:
            # Rollback
            if backup.exists():
                if target.exists():
                    target.unlink(missing_ok=True)
                shutil.move(str(backup), str(target))
            start_service()
            return False

        start_service()
        return True

    def apply_manager_update(self) -> bool:
        """Self-update the manager by spawning the external updater helper.

        The updater waits for this process to exit, replaces the binary,
        and relaunches the manager. This method does NOT return -- it exits.
        """
        staged = self._downloaded_assets.get("manager")
        if not staged or not staged.exists():
            return False

        # If it's a tar.gz, extract the binary first
        if staged.name.endswith(".tar.gz"):
            extracted = get_staging_dir() / "relims-print-manager"
            try:
                with tarfile.open(str(staged)) as tf:
                    members = tf.getmembers()
                    for member in members:
                        if member.isfile():
                            member.name = "relims-print-manager"
                            tf.extract(member, path=get_staging_dir())
                            break
                staged.unlink(missing_ok=True)
                staged = extracted
                os.chmod(str(staged), 0o755)
            except Exception:
                return False

        updater = get_self_updater_path()
        if not updater.exists():
            return False

        # Get the path to our own binary
        if getattr(sys, 'frozen', False):
            current_exe = Path(sys.executable)
        else:
            current_exe = Path(sys.argv[0]).resolve()

        pid = os.getpid()

        try:
            if platform.system() == "Windows":
                subprocess.Popen(
                    [str(updater), "--pid", str(pid),
                     "--source", str(staged), "--target", str(current_exe)],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.Popen(
                    [str(updater), "--pid", str(pid),
                     "--source", str(staged), "--target", str(current_exe)],
                )
        except Exception:
            return False

        # Exit so the updater can replace our binary
        sys.exit(0)
