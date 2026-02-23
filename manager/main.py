"""ReLIMS Print Manager - Windows entry point.

Manages the print service lifecycle, checks for updates,
and provides a system tray interface.
"""
import sys

from tray import ManagerTray


def main():
    if "--version" in sys.argv:
        from version import VERSION
        print(f"ReLIMS Print Manager v{VERSION}")
        return

    manager = ManagerTray()
    manager.run()


if __name__ == "__main__":
    main()
