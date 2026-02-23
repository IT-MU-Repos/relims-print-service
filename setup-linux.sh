#!/bin/bash
#
# ReLIMS Print Manager - Linux Dev Setup Script
#
# This script sets up a development environment.
# For production, use the installer from GitHub Releases.
#
# This script:
# 1. Creates a virtual environment
# 2. Installs dependencies (service + manager)
# 3. Optionally installs the service as a systemd user service
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
SERVICE_NAME="relims-print-service"

echo "========================================"
echo "ReLIMS Print Manager - Linux Dev Setup"
echo "========================================"
echo
echo "This sets up a development environment."
echo "For production, use the installer from GitHub Releases."
echo

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required but not found."
    echo "Install it with: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# Check for CUPS
if ! command -v lp &> /dev/null; then
    echo "WARNING: CUPS not found. You'll only be able to use network printing."
    echo "Install CUPS with: sudo apt install cups"
    echo
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

# Activate and install dependencies
echo "Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/requirements.txt"
pip install -r "$SCRIPT_DIR/requirements-manager.txt"

# Check for GTK (needed for system tray)
if ! python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null; then
    echo
    echo "WARNING: GTK 3 not found. System tray may not work."
    echo "Install with: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1"
fi

echo
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo
echo "To run the print service (dev mode):"
echo "  source $VENV_DIR/bin/activate"
echo "  cd $SCRIPT_DIR/service"
echo "  python app_linux.py --debug"
echo
echo "To run the manager (dev mode):"
echo "  source $VENV_DIR/bin/activate"
echo "  cd $SCRIPT_DIR/manager"
echo "  python main_linux.py"
echo

# Offer to install service as systemd unit
echo
read -p "Install print service as systemd user service (auto-start on login)? [y/N]: " install_service
if [[ "$install_service" =~ ^[Yy]$ ]]; then
    mkdir -p ~/.config/systemd/user

    cat > ~/.config/systemd/user/$SERVICE_NAME.service << EOF
[Unit]
Description=ReLIMS Print Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR/service
ExecStart=$VENV_DIR/bin/python $SCRIPT_DIR/service/app_linux.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable $SERVICE_NAME
    systemctl --user start $SERVICE_NAME

    echo
    echo "Systemd service installed and started!"
    echo
    echo "Service commands:"
    echo "  systemctl --user status $SERVICE_NAME    # Check status"
    echo "  systemctl --user restart $SERVICE_NAME   # Restart"
    echo "  systemctl --user stop $SERVICE_NAME      # Stop"
    echo "  systemctl --user disable $SERVICE_NAME   # Disable auto-start"
    echo
    echo "View logs:"
    echo "  journalctl --user -u $SERVICE_NAME -f"
fi

echo
echo "Configuration URL: http://localhost:5577"
echo
echo "Done!"
