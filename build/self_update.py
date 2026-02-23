"""Standalone self-updater for the ReLIMS Print Manager.

This is a tiny program that:
1. Waits for the manager process to exit
2. Replaces the manager binary with the new one
3. Relaunches the manager

Built into its own PyInstaller binary so it can run independently.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import time


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="ReLIMS self-updater")
    parser.add_argument("--pid", type=int, required=True,
                        help="PID of the manager process to wait for")
    parser.add_argument("--source", required=True,
                        help="Path to the new manager binary")
    parser.add_argument("--target", required=True,
                        help="Path to the current manager binary to replace")
    args = parser.parse_args()

    # Wait for the manager to exit (up to 30 seconds)
    for _ in range(60):
        if not is_pid_alive(args.pid):
            break
        time.sleep(0.5)
    else:
        print("Warning: Manager process did not exit within 30 seconds, proceeding anyway")

    # Small extra delay to ensure file handles are released
    time.sleep(1)

    backup = args.target + ".bak"

    try:
        # Backup current binary
        if os.path.exists(args.target):
            shutil.move(args.target, backup)

        # Copy new binary into place
        shutil.copy2(args.source, args.target)

        # Make executable on Linux
        if platform.system() != "Windows":
            os.chmod(args.target, 0o755)

        # Clean up
        if os.path.exists(backup):
            os.remove(backup)
        if os.path.exists(args.source):
            os.remove(args.source)

        print(f"Update applied successfully: {args.target}")

    except Exception as e:
        print(f"Update failed: {e}")
        # Rollback
        if os.path.exists(backup):
            if os.path.exists(args.target):
                os.remove(args.target)
            shutil.move(backup, args.target)
        sys.exit(1)

    # Relaunch the manager
    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                [args.target],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen([args.target])
        print("Manager relaunched")
    except Exception as e:
        print(f"Failed to relaunch manager: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
