#!/bin/bash
#
# ReLIMS Print Service - Systemd Setup
#
# Installs the print service as a systemd user service so it:
#   - Starts automatically on login
#   - Always runs in the background
#   - Restarts automatically if it crashes
#
# Usage:
#   ./setup-print-service.sh          # Install and start
#   ./setup-print-service.sh uninstall # Remove the service
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
SERVICE_DIR="$SCRIPT_DIR/service"
SERVICE_NAME="relims-print-service"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/$SERVICE_NAME.service"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# --- Uninstall ---
if [[ "${1:-}" == "uninstall" ]]; then
    echo -e "${YELLOW}Removing ReLIMS Print Service...${NC}"
    systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl --user daemon-reload
    echo -e "${GREEN}Print service removed.${NC}"
    exit 0
fi

# --- Preflight checks ---
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo -e "${RED}ERROR: Virtual environment not found at $SCRIPT_DIR/.venv${NC}"
    echo "Run setup-linux.sh first to create the virtual environment."
    exit 1
fi

if [[ ! -f "$SERVICE_DIR/app_linux.py" ]]; then
    echo -e "${RED}ERROR: app_linux.py not found in $SERVICE_DIR${NC}"
    exit 1
fi

# --- Install systemd service ---
echo -e "${GREEN}Installing ReLIMS Print Service as systemd user service...${NC}"

mkdir -p "$UNIT_DIR"

cat > "$UNIT_FILE" << EOF
[Unit]
Description=ReLIMS Print Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$SERVICE_DIR
ExecStart=$VENV_PYTHON $SERVICE_DIR/app_linux.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user start "$SERVICE_NAME"

# Enable lingering so the service runs even without an active login session
loginctl enable-linger "$USER" 2>/dev/null || true

echo
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}ReLIMS Print Service installed and running!${NC}"
echo -e "${GREEN}================================================${NC}"
echo
echo "  Status:  http://localhost:5577/status"
echo "  Config:  http://localhost:5577"
echo
echo "  Useful commands:"
echo "    systemctl --user status $SERVICE_NAME     # Check status"
echo "    systemctl --user restart $SERVICE_NAME    # Restart"
echo "    systemctl --user stop $SERVICE_NAME       # Stop"
echo "    journalctl --user -u $SERVICE_NAME -f     # View logs"
echo
echo "  To uninstall:"
echo "    $0 uninstall"
echo
