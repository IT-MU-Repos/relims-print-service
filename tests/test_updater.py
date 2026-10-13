"""The manager's update path: detect, install, verify, roll back, auto-install.

The manager modules import flat siblings (`paths`, `version`) whose names clash
with the service's own `version`, and `tray` imports pystray / PIL, which the
service test environment does not install. Each test therefore loads them
fresh from file with small stand-ins in `sys.modules`.
"""
import importlib.util
import io
import json
import sys
import time
import types
from pathlib import Path

import pytest

MANAGER = Path(__file__).resolve().parent.parent / "manager"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, MANAGER / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeServiceControl(types.ModuleType):
    def __init__(self):
        super().__init__("service_control_fake")
        self.calls = []
        for name in ("start_service", "stop_service", "restart_service"):
            setattr(self, name, self._recorder(name))
        self.is_service_running = lambda: True
        self.get_service_version = lambda: "unknown"

    def _recorder(self, name):
        def call():
            self.calls.append(name)
            return True
        return call


@pytest.fixture
def env(tmp_path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()

    paths = types.ModuleType("paths")
    paths.get_install_dir = lambda: install

    def get_staging_dir():
        staging = install / "staging"
        staging.mkdir(exist_ok=True)
        return staging

    paths.get_staging_dir = get_staging_dir
    paths.get_service_binary_path = lambda: install / "relims-print-service"
    paths.get_self_updater_path = lambda: install / "relims-self-updater"
    paths.get_service_url = lambda path="": "http://localhost:1" + path
    paths.get_manager_state_path = lambda: tmp_path / "manager_state.json"

    version = types.ModuleType("version")
    version.VERSION = "2.0.16"

    control = FakeServiceControl()
    for name, module in {
        "paths": paths, "version": version,
        "service_control": control, "service_control_linux": control,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    updater = _load("updater_under_test", "updater.py")
    monkeypatch.setattr(updater, "SERVICE_HEALTH_TIMEOUT_SECONDS", 0.05)
    # The real waits (service stop, health polling) only slow the suite down.
    monkeypatch.setattr(updater, "time", types.SimpleNamespace(
        sleep=lambda _seconds: None, monotonic=time.monotonic,
    ))
    return types.SimpleNamespace(updater=updater, control=control, install=install)


def _fake_urlopen(release_tag, service_version):
    def urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/releases/latest"):
            body = {"tag_name": f"v{release_tag}", "assets": []}
        elif url.endswith("/status"):
            if service_version is None:
                raise OSError("service not running")
            body = {"status": "ok", "version": service_version}
        else:
            raise OSError(f"unexpected url {url}")
        return io.BytesIO(json.dumps(body).encode())
    return urlopen


class TestCheckForUpdate:
    def check(self, env, monkeypatch, manager, service, release="2.1.0"):
        monkeypatch.setattr(env.updater, "MANAGER_VERSION", manager)
        monkeypatch.setattr(env.updater.urllib.request, "urlopen", _fake_urlopen(release, service))
        return env.updater.UpdateChecker().check_for_update()

    def test_offers_an_update_when_both_are_behind(self, env, monkeypatch):
        info = self.check(env, monkeypatch, manager="2.0.16", service="2.0.16")
        assert info["needs_service_update"] and info["needs_manager_update"]

    def test_offers_an_update_when_only_the_service_is_behind(self, env, monkeypatch):
        # Previously compared against the manager alone, which stranded a
        # service left behind once the manager was current.
        info = self.check(env, monkeypatch, manager="2.1.0", service="2.0.16")
        assert info["needs_service_update"] and not info["needs_manager_update"]

    def test_nothing_when_both_are_current(self, env, monkeypatch):
        assert self.check(env, monkeypatch, manager="2.1.0", service="2.1.0") is None

    def test_a_stopped_service_alone_is_not_a_reason_to_update(self, env, monkeypatch):
        assert self.check(env, monkeypatch, manager="2.1.0", service=None) is None

    def test_compares_versions_numerically(self, env, monkeypatch):
        # As strings, "2.0.16" > "2.0.9"... and "2.0.9" > "2.0.10".
        assert self.check(env, monkeypatch, manager="2.0.9", service="2.0.9",
                          release="2.0.10") is not None


class TestApplyServiceUpdate:
    def staged_checker(self, env, reports):
        target = env.install / "relims-print-service"
        target.write_text("old binary")
        staged = env.install / "staging"
        staged.mkdir(exist_ok=True)
        staged = staged / "relims-print-service.exe"
        staged.write_text("new binary")

        checker = env.updater.UpdateChecker()
        checker.latest_version = "2.1.0"
        checker._downloaded_assets["service"] = staged
        checker._get_service_version = lambda: reports
        return checker, target

    def test_a_service_that_reports_the_new_version_is_kept(self, env):
        checker, target = self.staged_checker(env, reports="2.1.0")
        assert checker.apply_service_update() is True
        assert target.read_text() == "new binary"
        assert not target.with_suffix(".bak").exists()

    def test_a_service_that_never_comes_up_is_rolled_back(self, env):
        checker, target = self.staged_checker(env, reports="unknown")
        assert checker.apply_service_update() is False
        assert target.read_text() == "old binary"
        # Stopped for the swap, started, stopped again, started on the old one.
        assert env.control.calls == ["stop_service", "start_service",
                                     "stop_service", "start_service"]

    def test_a_service_still_reporting_the_old_version_is_rolled_back(self, env):
        checker, target = self.staged_checker(env, reports="2.0.16")
        assert checker.apply_service_update() is False
        assert target.read_text() == "old binary"


class TestFailedVersionMemory:
    def test_round_trip(self, env):
        assert env.updater.failed_version("service") is None
        env.updater.record_failed_version("service", "2.1.0")
        assert env.updater.failed_version("service") == "2.1.0"

    def test_a_corrupt_state_file_is_treated_as_empty(self, env, tmp_path):
        (tmp_path / "manager_state.json").write_text("{not json")
        assert env.updater.failed_version("service") is None


class StubChecker:
    def __init__(self, service_ok=True):
        self.service_ok = service_ok
        self.calls = []

    def download_update(self, component):
        self.calls.append(f"download {component}")
        return Path(component)

    def apply_service_update(self):
        self.calls.append("apply service")
        return self.service_ok

    def apply_manager_update(self):
        self.calls.append("apply manager")
        return False


@pytest.fixture
def tray(env, monkeypatch):
    pystray = types.ModuleType("pystray")
    pystray.Icon = pystray.Menu = pystray.MenuItem = object
    pil = types.ModuleType("PIL")
    pil.Image = pil.ImageDraw = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "pystray", pystray)
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "updater", env.updater)
    module = _load("tray_under_test", "tray.py")
    manager = module.ManagerTray()
    return manager


INFO = {"version": "2.1.0", "needs_service_update": True, "needs_manager_update": True}


class TestAutomaticInstall:
    def test_installs_the_service_then_the_manager(self, tray):
        tray.checker = StubChecker()
        tray._install_update(INFO, automatic=True)
        assert tray.checker.calls == [
            "download service", "apply service", "download manager", "apply manager",
        ]

    def test_a_rolled_back_service_stops_the_manager_update(self, tray):
        tray.checker = StubChecker(service_ok=False)
        tray._install_update(INFO, automatic=True)
        assert tray.checker.calls == ["download service", "apply service"]

    def test_a_failed_release_is_not_retried_automatically(self, tray, env):
        tray.checker = StubChecker(service_ok=False)
        tray._install_update(INFO, automatic=True)
        tray.checker = StubChecker()
        tray._install_update(INFO, automatic=True)
        assert tray.checker.calls == [], "the hourly check must not keep re-applying it"

    def test_but_can_still_be_installed_by_hand(self, tray, env):
        env.updater.record_failed_version("service", "2.1.0")
        tray.checker = StubChecker()
        tray._install_update(INFO, automatic=False)
        assert tray.checker.calls[:2] == ["download service", "apply service"]

    def test_a_newer_release_is_tried_again(self, tray, env):
        env.updater.record_failed_version("service", "2.1.0")
        tray.checker = StubChecker()
        tray._install_update(dict(INFO, version="2.1.1"), automatic=True)
        assert "apply service" in tray.checker.calls

    def test_never_two_updates_at_once(self, tray):
        tray.checker = StubChecker()
        tray._update_lock.acquire()
        tray._install_update(INFO, automatic=True)
        assert tray.checker.calls == []


class TestArchiveExtraction:
    def archive(self, tmp_path, order):
        import tarfile
        src = tmp_path / "src" / "relims-print-service"
        src.mkdir(parents=True)
        (src / "relims-print-service").write_text("binary")
        (src / "setup-print-service.sh").write_text("#!/bin/sh")
        path = tmp_path / "svc.tar.gz"
        with tarfile.open(path, "w:gz") as tf:
            for name in order:
                tf.add(src / name, arcname=f"relims-print-service/{name}")
        return path

    def test_picks_the_binary_even_when_the_script_comes_first(self, env, tmp_path):
        archive = self.archive(tmp_path, ["setup-print-service.sh", "relims-print-service"])
        out = tmp_path / "out"
        out.mkdir()
        env.updater._extract_binary(archive, "relims-print-service", out, "relims-print-service")
        assert (out / "relims-print-service").read_text() == "binary"

    def test_a_missing_binary_fails_rather_than_installing_something_else(self, env, tmp_path):
        archive = self.archive(tmp_path, ["setup-print-service.sh"])
        with pytest.raises(FileNotFoundError):
            env.updater._extract_binary(archive, "relims-print-service", tmp_path, "x")
