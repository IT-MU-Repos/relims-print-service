"""System tray icon and menu for the ReLIMS Print Manager."""
import sys
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

from version import VERSION
from updater import UpdateChecker, failed_version, record_failed_version
from paths import get_service_url

if sys.platform == "win32":
    from service_control import (
        is_service_running, start_service, stop_service,
        restart_service, get_service_version,
    )
else:
    from service_control_linux import (
        is_service_running, start_service, stop_service,
        restart_service, get_service_version,
    )


class ManagerTray:
    def __init__(self):
        self.checker = UpdateChecker()
        self.update_info = None
        self.icon = None
        self._check_timer = None
        # One update at a time: the hourly check and a menu click must never
        # stop and replace the service concurrently.
        self._update_lock = threading.Lock()

    # --- Icon rendering ---

    def _create_icon(self, has_update=False):
        """Green rounded square icon, with orange badge dot when update available."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([4, 4, 60, 60], radius=8, fill=(34, 139, 34))
        # "P" letter in white
        draw.text((18, 10), "P", fill="white")
        if has_update:
            draw.ellipse([42, 2, 62, 22], fill=(255, 140, 0))
        return img

    # --- Menu building ---

    def _build_menu(self):
        running = is_service_running()
        svc_version = get_service_version() if running else "stopped"
        svc_status = f"Running (v{svc_version})" if running else "Stopped"

        items = [
            pystray.MenuItem(f"ReLIMS Print Manager v{VERSION}", None, enabled=False),
            pystray.MenuItem(f"Print Service: {svc_status}", None, enabled=False),
            pystray.Menu.SEPARATOR,
        ]

        # Service control
        if running:
            items.append(pystray.MenuItem("Stop Service", self._on_stop))
            items.append(pystray.MenuItem("Restart Service", self._on_restart))
        else:
            items.append(pystray.MenuItem("Start Service", self._on_start))

        items.append(pystray.Menu.SEPARATOR)

        # Update section
        if self.update_info:
            v = self.update_info["version"]
            sub_items = []
            if self.update_info.get("needs_service_update"):
                sub_items.append(pystray.MenuItem(
                    "Update Print Service Only", self._on_update_service))
            sub_items.append(pystray.MenuItem(
                "Update Everything", self._on_update_all))
            items.append(pystray.MenuItem(
                f"Update Available (v{v})",
                pystray.Menu(*sub_items),
            ))
        else:
            items.append(pystray.MenuItem("Check for Updates", self._on_check_updates))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Configure Printer...", self._on_configure, default=True))
        items.append(pystray.MenuItem("Uninstall...", self._on_uninstall))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit Manager", self._on_quit))

        return pystray.Menu(*items)

    def _refresh_menu(self):
        """Rebuild and refresh the tray menu."""
        if self.icon:
            self.icon.menu = self._build_menu()
            self.icon.update_menu()

    # --- Update checking ---

    def _start_update_timer(self):
        """Schedule periodic update checks (every 60 minutes)."""
        self._check_updates_background()
        self._check_timer = threading.Timer(3600, self._start_update_timer)
        self._check_timer.daemon = True
        self._check_timer.start()

    def _check_updates_background(self):
        """Check for an update in a background thread, and install it.

        Installing used to need someone to click Update in the tray menu, so
        lab PCs sat on old versions indefinitely. Updates now install on their
        own; the menu entries remain for installing on demand.
        """
        def _check():
            info = self.checker.check_for_update()
            if info:
                self.update_info = info
                if self.icon:
                    self.icon.icon = self._create_icon(has_update=True)
                    self._refresh_menu()
                self._install_update(info, automatic=True)
        t = threading.Thread(target=_check, daemon=True)
        t.start()

    def _install_update(self, info, automatic):
        """Install whatever `info` says is behind: the service, then the manager.

        The service goes first and is health-checked (see
        UpdateChecker.apply_service_update). A release whose service had to be
        rolled back is not trusted for the manager either, and automatic
        updates skip it from then on — see updater.record_failed_version.
        """
        if not self._update_lock.acquire(blocking=False):
            return  # an update is already running
        try:
            version = info["version"]
            if info.get("needs_service_update"):
                if automatic and failed_version("service") == version:
                    return
                if not self.checker.download_update("service"):
                    return
                if not self.checker.apply_service_update():
                    record_failed_version("service", version)
                    return
            if info.get("needs_manager_update"):
                if not self.checker.download_update("manager"):
                    return
                # Hands over to the self-updater and ends this process; returns
                # only if it could not, leaving this manager running as it was.
                self.checker.apply_manager_update()
                return
            self.update_info = None
            if self.icon:
                self.icon.icon = self._create_icon(has_update=False)
                self._refresh_menu()
        finally:
            self._update_lock.release()

    # --- Menu actions ---

    def _on_start(self, icon, item):
        start_service()
        self._refresh_menu()

    def _on_stop(self, icon, item):
        stop_service()
        self._refresh_menu()

    def _on_restart(self, icon, item):
        restart_service()
        self._refresh_menu()

    def _on_check_updates(self, icon, item):
        self._check_updates_background()

    def _on_update_service(self, icon, item):
        """Download and apply a service-only update."""
        if not self.update_info:
            return
        info = dict(self.update_info, needs_service_update=True, needs_manager_update=False)
        threading.Thread(target=self._install_update, args=(info, False), daemon=True).start()

    def _on_update_all(self, icon, item):
        """Download and apply updates to both service and manager."""
        if not self.update_info:
            return
        threading.Thread(
            target=self._install_update, args=(self.update_info, False), daemon=True
        ).start()

    def _on_configure(self, icon, item):
        webbrowser.open(get_service_url("/"))

    def _on_uninstall(self, icon, item):
        """Trigger the uninstall process."""
        if sys.platform == "win32":
            from uninstaller import uninstall_windows
            icon.stop()
            uninstall_windows()
        else:
            from uninstaller import uninstall_linux
            icon.stop()
            uninstall_linux()

    def _on_quit(self, icon, item):
        if self._check_timer:
            self._check_timer.cancel()
        icon.stop()

    # --- Main entry ---

    def run(self):
        """Start the manager tray icon and ensure the service is running."""
        start_service()

        self.icon = pystray.Icon(
            "relims-manager",
            self._create_icon(),
            "ReLIMS Print Manager",
            menu=self._build_menu(),
        )

        # Start periodic update checks
        self._start_update_timer()

        # pystray.Icon.run() blocks -- this is the main loop
        self.icon.run()
