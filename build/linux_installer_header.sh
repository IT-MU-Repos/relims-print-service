#!/bin/bash
#
# ReLIMS Print Manager - Linux Installer
#
# This is a self-extracting installer. The binary payload is appended
# after the __ARCHIVE_BELOW__ marker.
#

set -e

INSTALL_DIR="$HOME/.local/share/relims-print-manager"
SERVICE_NAME="relims-print-service"
MANAGER_NAME="relims-print-manager"

echo "========================================"
echo "  ReLIMS Print Manager - Linux Installer"
echo "========================================"
echo

# Check dependencies
if ! command -v systemctl &> /dev/null; then
    echo "WARNING: systemctl not found. Auto-start will not be configured."
    echo "You can still run the manager manually."
    echo
fi

if ! command -v lp &> /dev/null; then
    echo "WARNING: CUPS not found. You'll only be able to use network printing."
    echo "Install CUPS with: sudo apt install cups"
    echo
fi

# Create install directory
echo "Installing to: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Extract binaries from the payload appended to this script
ARCHIVE_START=$(awk '/^__ARCHIVE_BELOW__/ {print NR + 1; exit 0; }' "$0")
tail -n+$ARCHIVE_START "$0" | tar xzf - -C "$INSTALL_DIR"

chmod +x "$INSTALL_DIR/relims-print-service"
chmod +x "$INSTALL_DIR/relims-print-manager"
chmod +x "$INSTALL_DIR/relims-self-updater"

echo "Binaries installed."

# Create systemd user service for the print service
if command -v systemctl &> /dev/null; then
    mkdir -p ~/.config/systemd/user

    cat > ~/.config/systemd/user/$SERVICE_NAME.service << EOF
[Unit]
Description=ReLIMS Print Service
After=network.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/relims-print-service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable $SERVICE_NAME
    systemctl --user start $SERVICE_NAME

    echo "Systemd service installed and started."

    # Enable lingering so services survive reboot without requiring login
    if command -v loginctl &> /dev/null; then
        loginctl enable-linger "$(whoami)" 2>/dev/null || true
        echo "User lingering enabled (services will start on boot)."
    fi
fi

# Create XDG autostart entry for the manager
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/$MANAGER_NAME.desktop << EOF
[Desktop Entry]
Type=Application
Name=ReLIMS Print Manager
Exec=$INSTALL_DIR/relims-print-manager
Comment=ReLIMS Print Manager - manages label printer service
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
EOF

# Create .desktop file for application menu
mkdir -p ~/.local/share/applications
cp ~/.config/autostart/$MANAGER_NAME.desktop \
   ~/.local/share/applications/$MANAGER_NAME.desktop

echo "Desktop entries created."

echo
echo "========================================"
echo "  Installation Complete!"
echo "========================================"
echo
echo "  Install directory: $INSTALL_DIR"
echo "  Print service: running as systemd user service"
echo "  Manager: will auto-start on login"
echo
echo "  Configure your printer at: http://localhost:5577"
echo
echo "  To start the manager now:"
echo "    $INSTALL_DIR/relims-print-manager &"
echo
echo "  To uninstall, use the tray menu or run:"
echo "    $INSTALL_DIR/relims-print-manager --uninstall"
echo

exit 0
__ARCHIVE_BELOW__
