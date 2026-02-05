# ReLIMS Print Service

A lightweight Windows tray application that accepts ZPL code over HTTP and prints to Zebra or Citizen label printers.

Runs on `http://localhost:5577` and provides a simple API for the ReLIMS frontend to send ZPL labels to a locally connected printer.

## Quick Start (Development)

```bash
cd print-service
pip install -r requirements.txt
python app.py --no-tray
```

Open http://localhost:5577 to access the configuration UI.

## API Endpoints

### `GET /status`
Health check. Returns `{"status": "ok", "version": "1.0.0"}`.

### `GET /printers`
List available Windows printers.
```bash
curl http://localhost:5577/printers
```

### `POST /print`
Send ZPL to the configured printer.
```bash
curl -X POST http://localhost:5577/print \
  -H "Content-Type: application/json" \
  -d '{"zpl": "^XA^FO50,50^A0N,40,40^FDHello^FS^XZ", "copies": 1}'
```

### `GET /config`
Get current configuration.

### `POST /config`
Update configuration (partial updates supported).
```bash
curl -X POST http://localhost:5577/config \
  -H "Content-Type: application/json" \
  -d '{"backend": "network", "printer_host": "192.168.1.100", "printer_port": 9100}'
```

## Configuration

Config is stored at:
- **Windows**: `%APPDATA%\ReLIMS Print Service\config.json`
- **Linux/Mac**: `~/.config/ReLIMS Print Service/config.json`

| Key | Default | Description |
|-----|---------|-------------|
| `backend` | `"windows"` | `"windows"` (USB via spooler) or `"network"` (TCP socket) |
| `printer_name` | `""` | Windows printer name (for USB backend) |
| `printer_host` | `""` | Printer IP address (for network backend) |
| `printer_port` | `9100` | TCP port (for network backend) |
| `api_port` | `5577` | Port the service listens on |
| `timeout` | `5` | Socket timeout in seconds |

## Building the Windows Installer

### Prerequisites
- Python 3.11+
- [Inno Setup 6+](https://jrsoftware.org/isinfo.php)

### Steps

1. Install dependencies:
   ```bash
   pip install -r requirements.txt pyinstaller
   ```

2. Build the exe:
   ```bash
   pyinstaller build/build.spec
   ```
   Output: `dist/relims-print-service.exe`

3. (Optional) Place an `icon.ico` in `build/` before building for a custom icon.

4. Compile the installer with Inno Setup:
   - Open `build/installer.iss` in Inno Setup
   - Click Build > Compile
   - Output: `build/Output/relims-print-service-setup.exe`

## How It Works

- **Windows (USB)**: Uses `win32print` to send raw ZPL through the Windows print spooler as a RAW document. Works with any printer visible in Windows.
- **Network (TCP)**: Opens a direct TCP socket to the printer on port 9100 and sends raw ZPL bytes. Works with any ZPL-compatible network printer.

The service runs as a system tray icon. Double-click to open the config page. The installer registers it to auto-start with Windows.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No printers found" | Ensure the printer is installed in Windows Settings > Printers |
| Network print timeout | Check the printer IP is reachable: `ping 192.168.1.100` |
| Port 5577 in use | Change `api_port` in config and restart |
| Blank labels | Verify ZPL syntax — test with `^XA^FO50,50^A0N,40,40^FDTest^FS^XZ` |
