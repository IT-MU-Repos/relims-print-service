#!/usr/bin/env python3
"""ReLIMS Print Manager - Linux entry point.

Manages the print service lifecycle, checks for updates,
and provides a system tray interface.
"""
import signal
import sys

from tray import ManagerTray


def main():
    if "--version" in sys.argv:
        from version import VERSION
        print(f"ReLIMS Print Manager v{VERSION}")
        return

    # Handle SIGTERM for graceful shutdown
    def handle_signal(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    manager = ManagerTray()
    manager.run()


if __name__ == "__main__":
    main()
