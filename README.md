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
  ├── /print       — Send ZPL to printer
  ├── /print-batch — Send many labels in one job
  ├── /health      — Rich health check (identity, version, printer state)
  ├── /status      — Legacy health check + version
  ├── /config      — Get/set configuration
  ├── /printers    — List available printers
  └── /logs        — Recent service log lines
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

#### CUPS USB quirk (Linux, required for fast printing)

The CL-E321 advertises a bidirectional USB interface but never answers the
back-channel read, so the CUPS `usb` backend blocks for ~8s after **every** job
before it will start the next one. Labels appear seconds after they were sent,
and a second job queues behind the stall rather than printing sooner.

The installers offer to apply the fix. To apply it by hand:

```bash
echo '0x1d90 0x20f9 unidir' | sudo tee /usr/share/cups/usb/net.labserve.relims.usb-quirks
```

No restart is needed — the backend loads quirks per job, so the next print picks
it up. The print service never reads from the printer, so unidirectional I/O
costs it nothing.

**This is system-wide.** The quirk applies to every CUPS client on the machine
that talks to a CL-E321, not just this service, so any other software loses the
printer's back-channel (status and media queries) too. It is also the one change
uninstalling cannot undo on its own — removing it needs root, so the uninstaller
prints the command rather than running it:

```bash
sudo rm /usr/share/cups/usb/net.labserve.relims.usb-quirks
```
 Verify with `/var/log/cups/error_log`: a job's `time-at-processing`
and `time-at-completed` should be the same second, and no `Read thread still
active` line should appear.

## Sharing a printer with other software

ZPL's positioning, width and darkness commands are **modal**: they update the
printer's *active configuration* and stay in effect for every later format until
changed again or the printer is powered off. A label job therefore leaves its
`^MD` darkness, `^LH` label home and `^PW` width — plus the `^LL` and `^CI` the
Main-API renderer emits — sitting on the printer for whatever prints next. On a
lab PC that is usually the legacy VB.NET LIMS app or ordinary driver printing,
which then come out wrong.

Since 2.1.0 every job ends with a small configuration-only format that hands the
printer back. It carries no field data, so it costs no media.

| `printer_restore_mode` | Sends | Use when |
|---|---|---|
| `"jur"` *(default)* | `^XA^LH0,0^MD0^CI0^JUR^XZ` — power-on values, then recall the printer's saved configuration | Normally. `^JUR` restores wholesale, so it also undoes the renderer's `^PW`/`^LL`. The power-on values in front are a failsafe for a printer that ignores `^JUR`. |
| `"neutralize"` | `^XA^LH0,0^MD0^CI0^XZ` — put back the power-on values | The printer's ZPL emulation does not implement `^JU`. Cannot restore `^PW`/`^LL`, whose power-on values depend on the printer. |
| `"off"` | nothing | Reproducing pre-2.1.0 behaviour. |

The restore is sent once, after the last copy, inside the same connection or
spooler document as the label — never between copies, which would print copies
2..n at the handed-back settings, and never as a separate job, which would let
another application slip a print in between.

## The service never changes the printer's settings

Its own settings — calibrated origin and darkness — travel inside every label, and
the restore above hands the printer back afterwards. Nothing it sends writes to the
printer's permanent memory, recalls defaults or re-calibrates media: `^JUS`, `^JUF`,
`^JUN`, `^JUA`, `~JC`, `~JL`, `~JR` and `~SD`/`^SD` are stripped from every outgoing job,
`raw` ones included.

That matters because the legacy offline LIMS sends no `^LH`, `^PW`, `^LL` or `^CI` of its
own — it relies on the printer's own setup. On the Citizen CL-E321 that setup is
`CitizenPrinter.CONFIG_STR` in LIMS_SOURCE.

Up to v2.0.16 the service had a **Reset Printer Settings** action (`^JUF` + `~JC`), which
wiped that setup. It was removed in v2.1.0, as was an unreleased `^JUS` "baseline". If LIMS
labels are already off:

1. Power-cycle the printer. That clears anything an older service left active.
2. If that is not enough on a Citizen, use the LIMS app's own **Printer Maintenance → Fix My
   Printer**, which re-sends its known-good setup.


### Failsafes

- **Restore works without `^JUR`.** The default restore puts back label home, darkness and
  code page before `^JUR`, so those come back even on a printer that ignores it.
- **A failed job still hands the printer back.** If a job fails partway, the label may be on
  the printer without its restore, so the restore is sent again as a job of its own.
- **Restore on startup.** The service hands the printer back once when it starts. That covers
  a crash between a label and its restore, and printers an older service left dirty. The
  restore prints nothing.
- **The filter cannot be bypassed.** `^CC`/`~CC`/`^CT`/`~CT` (which change the command
  prefix) are stripped too, and a job containing a Citizen configuration block (`~!!`) is
  refused with `400`.
- **Visible state.** `/health` reports `restore_mode`, each job logs the restore it sent, and
  the settings page warns when restore is off.
- **Per-PC rollback.** `"printer_restore_mode": "off"` in one PC's `config.json` sends exactly
  what pre-2.1.0 sent, if the restore ever misbehaves on a particular printer.

## Updates

The manager automatically checks for updates every hour by polling the GitHub Releases API.

When an update is available:
1. An orange badge appears on the tray icon
2. Right-click the tray icon to see the update menu
3. Choose **Update Print Service Only** (updates just the printing backend) or **Update Everything** (updates both service and manager)

Service-only updates apply instantly (the service restarts in seconds). Full updates briefly restart the manager too.

## API Endpoints

The print service runs on `http://localhost:5577`.

> Integrating from another web app? See **[docs/INTEGRATION.md](docs/INTEGRATION.md)** for
> the full contract, detection patterns, and copy-paste client code.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Rich health check (v2.0.12+): `{"service": "relims-print-service", "status": "ok"\|"degraded", "version", "platform", "backend", "backend_available", "printer_configured", "uptime_seconds"}` |
| `/status` | GET | Legacy health check (kept stable): `{"status": "ok", "version": "...", "platform": "windows"\|"linux", "win32"\|"cups": bool}` |
| `/printers` | GET | List available printers |
| `/config` | GET | Get current configuration |
| `/config` | POST | Update configuration (partial updates) |
| `/print` | POST | Send ZPL (and/or base64 image) to printer. Optional `"raw": true` (skip calibration offsets). `"reset_printer"` is accepted but ignored since v2.1.0 |
| `/print-batch` | POST | Send multiple labels in a single job |
| `/logs` | GET | Last 200 log lines (debugging) |
| `/` | GET | Printer configuration UI |

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
| `label_offset_x` / `label_offset_y` | `0` | Fine-tune print position offsets (dots) |
| `label_origin_x` / `label_origin_y` | `0` | Calibrated label origin (dots); when set, replaces incoming `^LH` |
| `label_width` / `label_height` | `0` | Label dimensions from calibration. `label_width` also sets `^PW`: content shifted right by `label_origin_x` needs a print width covering the offset too. |
| `printer_restore_mode` | `"jur"` | How a job hands the printer back — see [Sharing a printer](#sharing-a-printer-with-other-software). `"jur"`, `"neutralize"`, or `"off"`. |
| `allowed_origins` | loopback | Origins allowed to print or change settings. **Not writable over HTTP** — edit `config.json`. |
| `label_darkness` | `0` | Print darkness, `-30`…`30`. Injected as `^MD`, which is **relative** to the printer's own darkness — `0` emits nothing and leaves the printer untouched. Negative is brighter, positive is darker. Label-global (affects barcodes too) and ZPL-only. |

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
├── docs/
│   └── INTEGRATION.md        # Web-app integration guide (health check, printing)
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

### Cutting a release

**Bumping the version is the release action.** In your PR, set the same new version in
**both** files:

```python
# service/version.py  AND  manager/version.py
VERSION = "2.1.0"
```

Merge to `main` and CI does the rest: it builds all binaries, creates the Windows
installer, generates `manifest.json`, tags `v2.1.0` at the merge commit, and publishes a
GitHub Release with all artifacts. The Mµle **Tools → Print service** page picks it up
within ~5 minutes, and installed agents start offering the update on their next hourly
check.

Both files must match — CI fails fast if they drift. The update check compares the release
tag against the **manager** version (`manager/updater.py`), so bumping only the service
would ship an update nobody is ever offered.

A merge that doesn't change the version runs a ~10s check and stops — no build, no
duplicate release. The same applies to re-running an old commit.

Pushing a `v*` tag by hand still works and takes precedence over the source version. To
rebuild and replace the assets of a version that is *already* released, run the workflow
manually from the Actions tab with **force** ticked.

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
| Labels take ~8s to appear (Linux/USB) | Missing CUPS USB quirk — see [Citizen Printers](#citizen-printers). Confirm with `grep "Read thread still active" /var/log/cups/error_log` |
