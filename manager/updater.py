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
    get_self_updater_path, get_service_url, get_manager_state_path,
)
from version import VERSION as MANAGER_VERSION

GITHUB_OWNER = "IT-MU-Repos"
GITHUB_REPO = "relims-print-service"
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
CHECK_INTERVAL_SECONDS = 3600  # 1 hour

# How long a freshly installed service gets to answer /status with the new
# version before the update is rolled back. Startup includes PyInstaller
# unpacking the onefile binary, which is slow on a busy lab PC.
SERVICE_HEALTH_TIMEOUT_SECONDS = 30


def _is_newer(remote: str, current: str) -> bool:
    try:
        return Version(remote) > Version(current)
    except Exception:
        return remote != current


def _extract_binary(archive: Path, wanted: str, dest_dir: Path, out_name: str) -> None:
    """Extract the file named `wanted` from a release tarball as `out_name`.

    Chosen by name, not position: the service archive also carries
    setup-print-service.sh, and "the first file" is only the binary for as
    long as the archive happens to list it first.
    """
    with tarfile.open(str(archive)) as tf:
        files = [m for m in tf.getmembers() if m.isfile()]
        member = next((m for m in files if Path(m.name).name == wanted), None)
        if member is None:
            raise FileNotFoundError(f"{wanted} not found in {archive.name}")
        member.name = out_name
        # "data" refuses absolute paths, links out of dest_dir and device
        # files; it exists from Python 3.11.4 (CI builds on the latest 3.11).
        safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tf.extract(member, path=dest_dir, **safe)


def load_state() -> dict:
    try:
        return json.loads(get_manager_state_path().read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        get_manager_state_path().write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def failed_version(component: str) -> str | None:
    """The last version of `component` whose update was rolled back."""
    return load_state().get("failed_versions", {}).get(component)


def record_failed_version(component: str, version: str) -> None:
    """Remember a release that failed, so automatic updates stop retrying it.

    Without this, a broken release is re-applied every hour: each attempt
    stops the service and costs the lab a few seconds of failed prints. A
    later release clears it by being a different version; "Update" in the
    tray menu still tries it on request.
    """
    state = load_state()
    state.setdefault("failed_versions", {})[component] = version
    save_state(state)


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

        # Newer than EITHER component. Comparing against the manager alone
        # stranded a service that was left behind — by a failed or rolled-back
        # service update, say — once the manager itself was current. An
        # unreachable service ("unknown") does not count as behind on its own:
        # it may simply be stopped, and that is not something to update over.
        current_service = self._get_service_version()
        service_behind = current_service != "unknown" and _is_newer(tag, current_service)
        if not (_is_newer(tag, MANAGER_VERSION) or service_behind):
            return None

        self.latest_release = release
        self.latest_version = tag

        # Fetch manifest.json from release assets
        self.manifest = self._fetch_manifest(release)

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

    def _wait_for_service_version(self, expected: str) -> bool:
        """Poll /status until the service reports `expected`, or time out."""
        deadline = time.monotonic() + SERVICE_HEALTH_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._get_service_version() == expected:
                return True
            time.sleep(1)
        return False

    def apply_service_update(self) -> bool:
        """Stop the service, replace its binary, restart it, and check it.

        The previous binary is kept until the new one has answered /status
        with the new version. If it does not — it crashes on start, or a
        dependency is missing from the build — the previous binary goes back
        and is restarted, so a bad release costs a lab PC seconds of printing
        rather than all of it.

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
                _extract_binary(staged, "relims-print-service", target.parent, target.name)
            else:
                shutil.copy2(str(staged), str(target))

            # Make executable on Linux
            if platform.system() != "Windows":
                os.chmod(str(target), 0o755)

        except Exception:
            self._restore_service_backup(target, backup, start_service)
            return False

        start_service()
        expected = (self.manifest or {}).get("service_version", self.latest_version)
        if expected and not self._wait_for_service_version(expected):
            stop_service()
            time.sleep(1)
            self._restore_service_backup(target, backup, start_service)
            return False

        # Verified — only now is the old binary disposable.
        backup.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
        return True

    @staticmethod
    def _restore_service_backup(target, backup, start_service):
        """Put the previous service binary back and start it."""
        if backup.exists():
            if target.exists():
                target.unlink(missing_ok=True)
            shutil.move(str(backup), str(target))
        start_service()

    def apply_manager_update(self) -> bool:
        """Self-update the manager by spawning the external updater helper.

        The updater waits for this process to exit, replaces the binary,
        and relaunches the manager. On success this does NOT return -- the
        whole process exits.
        """
        staged = self._downloaded_assets.get("manager")
        if not staged or not staged.exists():
            return False

        # If it's a tar.gz, extract the binary first
        if staged.name.endswith(".tar.gz"):
            extracted = get_staging_dir() / "relims-print-manager"
            try:
                _extract_binary(staged, "relims-print-manager", get_staging_dir(),
                                "relims-print-manager")
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

        # Exit so the updater can replace our binary. os._exit, not sys.exit:
        # this runs on a background thread, where sys.exit only ends the
        # thread and leaves the old manager running while its binary is
        # replaced underneath it.
        os._exit(0)
