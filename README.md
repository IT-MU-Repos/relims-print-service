# ReLIMS Print Manager

A managed desktop application for printing ZPL labels to Zebra and Citizen printers. Includes a background print service, a system tray manager with automatic updates, and cross-platform support for Windows and Linux.

## Architecture

```
ReLIMS Print Manager (system tray app)
  ├── Manages print service lifecycle (start/stop/restart)
  ├── Checks GitHub Releases for updates
  ├── Downloads and applies updates (service-only or full)
  ├── Opens printer configuration in browser
  └── Uninstall capability
  │
  v
ReLIMS Print Service (headless Flask daemon on localhost:5577)
  ├── /print   — Send ZPL to printer
  ├── /status  — Health check + version
  ├── /config  — Get/set configuration
  └── /printers — List available printers
```

## Installation

### Windows

Download `relims-print-manager-setup.exe` from the [latest GitHub release](../../releases/latest) and run it. The installer:
- Installs to `%LOCALAPPDATA%\ReLIMS Print Manager\`
- Registers the manager to auto-start on login
- Starts the manager immediately (which starts the print service)

### Linux

Download `relims-print-manager-linux-install.sh` from the [latest release](../../releases/latest) and run:

```bash
chmod +x relims-print-manager-linux-install.sh
./relims-print-manager-linux-install.sh
```

This installs to `~/.local/share/relims-print-manager/`, creates a systemd user service for the print service, and sets up XDG autostart for the manager.

## Printer Setup

### Zebra Printers

- **USB (Windows)**: Install the Zebra Windows driver, connect via USB. In config, select **Windows (USB)** backend and choose the printer from the dropdown.
- **Network**: Connect the printer to your network. In config, select **Network (TCP)** backend and enter the printer's IP address with port `9100`.

### Citizen Printers

- **USB (Windows)**: Install the Citizen Windows driver, connect via USB. Select **Windows (USB)** backend.
- **CUPS (Linux)**: Install CUPS and the Citizen CUPS driver (`ctzcls`). Select **CUPS** backend and choose the printer.
- **Network (ZPL emulation)**: If the Citizen printer supports ZPL emulation, use **Network (TCP)** backend with port `9100`.

## Updates

The manager automatically checks for updates every hour by polling the GitHub Releases API.

When an update is available:
1. An orange badge appears on the tray icon
2. Right-click the tray icon to see the update menu
3. Choose **Update Print Service Only** (updates just the printing backend) or **Update Everything** (updates both service and manager)

Service-only updates apply instantly (the service restarts in seconds). Full updates briefly restart the manager too.

## API Endpoints

The print service runs on `http://localhost:5577`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Health check: `{"status": "ok", "version": "2.0.0"}` |
| `/printers` | GET | List available printers |
| `/config` | GET | Get current configuration |
| `/config` | POST | Update configuration (partial updates) |
| `/print` | POST | Send ZPL to printer |

### Print Example

```bash
curl -X POST http://localhost:5577/print \
  -H "Content-Type: application/json" \
  -d '{"zpl": "^XA^FO50,50^A0N,40,40^FDHello^FS^XZ", "copies": 1}'
```

## Configuration

Config is stored at:
- **Windows**: `%APPDATA%\ReLIMS Print Service\config.json`
- **Linux**: `~/.config/ReLIMS Print Service/config.json`

| Key | Default | Description |
|-----|---------|-------------|
| `backend` | `"windows"` / `"cups"` | `"windows"` (USB via spooler), `"cups"` (CUPS on Linux), or `"network"` (TCP socket) |
| `printer_name` | `""` | Printer name (for USB/CUPS backend) |
| `printer_host` | `""` | Printer IP address (for network backend) |
| `printer_port` | `9100` | TCP port (for network backend) |
| `api_port` | `5577` | Port the service listens on |
| `timeout` | `5` | Socket timeout in seconds |

## Development

### Quick Start

```bash
cd print-service
pip install -r requirements.txt -r requirements-manager.txt

# Run the print service
cd service
python app_linux.py --debug

# In another terminal, run the manager
cd manager
python main_linux.py
```

Or use the setup script:
```bash
./setup-linux.sh    # Linux
setup.bat           # Windows
```

### Project Structure

```
print-service/
├── service/                  # Print service (headless Flask daemon)
│   ├── app.py                # Windows entry point
│   ├── app_linux.py          # Linux entry point
│   ├── printer.py            # Windows printer backends
│   ├── printer_linux.py      # Linux printer backends (CUPS + network)
│   ├── config.py             # Configuration management
│   ├── version.py            # Service version
│   └── static/index.html     # Config UI
│
├── manager/                  # Print Manager (system tray app)
│   ├── main.py               # Windows entry point
│   ├── main_linux.py         # Linux entry point
│   ├── tray.py               # System tray icon and menu
│   ├── service_control.py    # Windows service lifecycle
│   ├── service_control_linux.py  # Linux systemd integration
│   ├── updater.py            # Update checker/downloader/applier
│   ├── uninstaller.py        # Clean removal logic
│   ├── paths.py              # Platform-specific paths
│   └── version.py            # Manager version
│
├── build/                    # Build configuration
│   ├── build_service.spec    # PyInstaller: service (Windows)
│   ├── build_service_linux.spec  # PyInstaller: service (Linux)
│   ├── build_manager.spec    # PyInstaller: manager (Windows)
│   ├── build_manager_linux.spec  # PyInstaller: manager (Linux)
│   ├── build_self_updater.spec   # PyInstaller: self-updater
│   ├── self_update.py        # Self-updater helper script
│   ├── installer.iss         # Inno Setup installer (Windows)
│   └── linux_installer_header.sh  # Self-extracting installer (Linux)
│
├── .github/workflows/build.yml  # CI/CD pipeline
├── requirements.txt          # Service dependencies
└── requirements-manager.txt  # Manager dependencies
```

### Building

```bash
pip install pyinstaller

# Build service
pyinstaller build/build_service.spec        # Windows
pyinstaller build/build_service_linux.spec   # Linux

# Build manager
pyinstaller build/build_manager.spec         # Windows
pyinstaller build/build_manager_linux.spec   # Linux

# Build self-updater
pyinstaller build/build_self_updater.spec
```

### CI/CD

Push a version tag to trigger automated builds:

```bash
git tag v2.1.0
git push origin v2.1.0
```

The GitHub Actions workflow builds all binaries, creates the Windows installer, generates `manifest.json`, and publishes a GitHub Release with all artifacts.

## Uninstalling

- **From the tray**: Right-click the tray icon > **Uninstall...**
- **Windows**: Run `uninstall.bat` or use Windows Add/Remove Programs
- **Linux**: The tray uninstall removes the systemd service, desktop entries, and install directory

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No printers found" | Ensure the printer is installed in OS settings |
| Network print timeout | Check printer IP is reachable: `ping <ip>` |
| Port 5577 in use | Change `api_port` in config and restart |
| Blank labels | Verify ZPL syntax: `^XA^FO50,50^A0N,40,40^FDTest^FS^XZ` |
| Tray icon not showing (Linux) | Install GTK: `sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1` |
| CUPS not found (Linux) | Install CUPS: `sudo apt install cups` |
