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

# Install the CUPS USB quirk for Citizen label printers.
#
# The CL-E321 advertises a bidirectional USB interface but never answers the
# back-channel read, so the CUPS usb backend blocks ~8s after every job before
# it will start the next one — labels appear seconds after they were sent, and
# a second job queues behind the stall. `unidir` removes it. The print service
# never reads from the printer, so unidirectional I/O costs nothing.
#
# Needs root, which this installer otherwise never requires. Best-effort only:
# it must never abort the install, hence the `|| true` on the call.
QUIRK_FILE="/usr/share/cups/usb/net.labserve.relims.usb-quirks"
QUIRK_LINE="0x1d90 0x20f9 unidir"

write_usb_quirk() {
    printf '%s\n%s\n' \
        "# Citizen CL-E321Z - no USB back-channel; avoids a ~8s stall per job." \
        "$QUIRK_LINE"
}

install_usb_quirk() {
    # Nothing to do if CUPS isn't present or the quirk is already there.
    [ -d /usr/share/cups/usb ] || return 0
    if grep -qsF "$QUIRK_LINE" "$QUIRK_FILE"; then
        echo "CUPS USB quirk already present."
        return 0
    fi

    echo
    echo "Citizen label printers stall ~8s per job without a CUPS USB quirk."

    if [ "$(id -u)" = "0" ]; then
        write_usb_quirk > "$QUIRK_FILE"
        chmod 0644 "$QUIRK_FILE"
        echo "CUPS USB quirk installed: $QUIRK_FILE"
        return 0
    fi

    # Only prompt when there is a terminal to answer; a piped/CI run must not hang.
    if [ -t 0 ] && command -v sudo &> /dev/null; then
        read -p "Install it now (requires sudo)? [y/N]: " install_quirk
        if [[ "$install_quirk" =~ ^[Yy]$ ]]; then
            if write_usb_quirk | sudo tee "$QUIRK_FILE" > /dev/null; then
                echo "CUPS USB quirk installed: $QUIRK_FILE"
                return 0
            fi
        fi
    fi

    echo "Skipped. To apply it later, run as root:"
    echo "  echo '$QUIRK_LINE' | sudo tee $QUIRK_FILE"
    echo "No restart needed - the next print job picks it up."
}

install_usb_quirk || true

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
