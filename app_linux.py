#!/usr/bin/env python3
"""ReLIMS Print Service for Linux.

A lightweight local service that receives print jobs from the browser
and sends them to CUPS or network printers.
"""
import sys
import signal
import threading

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import load_config, save_config
from printer_linux import get_printer, CUPSPrinter, HAS_CUPS

VERSION = "1.0.0"

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/status")
def status():
    return jsonify({"status": "ok", "version": VERSION, "cups": HAS_CUPS, "platform": "linux"})


@app.route("/printers")
def list_printers():
    printers = CUPSPrinter.list_printers() if HAS_CUPS else []
    default = CUPSPrinter.get_default_printer() if HAS_CUPS else ""
    return jsonify({"printers": printers, "default": default})


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/config", methods=["POST"])
def update_config():
    data = request.get_json(force=True)
    allowed = {"printer_name", "printer_host", "printer_port", "backend", "api_port", "timeout"}
    filtered = {k: v for k, v in data.items() if k in allowed}
    if "printer_port" in filtered:
        filtered["printer_port"] = int(filtered["printer_port"])
    if "api_port" in filtered:
        filtered["api_port"] = int(filtered["api_port"])
    if "timeout" in filtered:
        filtered["timeout"] = int(filtered["timeout"])
    updated = save_config(filtered)
    return jsonify(updated)


@app.route("/print", methods=["POST"])
def print_zpl():
    data = request.get_json(force=True)
    zpl = data.get("zpl", "").strip()
    if not zpl:
        return jsonify({"success": False, "error": "No ZPL data provided"}), 400
    copies = max(1, int(data.get("copies", 1)))
    try:
        printer = get_printer()
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    result = printer.print_zpl(zpl, copies=copies)
    status_code = 200 if result["success"] else 500
    return jsonify(result), status_code


# --- System Tray (using AppIndicator on Linux) ---

def start_tray():
    """Start with system tray icon using pystray (GTK backend on Linux)."""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        print("pystray/Pillow not installed — running without system tray")
        print("Install with: pip install pystray Pillow")
        run_server()
        return

    cfg = load_config()
    port = cfg["api_port"]

    def open_config(icon, item):
        import webbrowser
        webbrowser.open(f"http://localhost:{port}/")

    def quit_app(icon, item):
        icon.stop()

    # Simple green square icon
    image = Image.new("RGB", (64, 64), color=(34, 139, 34))

    icon = pystray.Icon(
        "relims-print",
        image,
        "ReLIMS Print Service",
        menu=pystray.Menu(
            pystray.MenuItem("Open Config", open_config, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        ),
    )

    # Run Flask in a daemon thread
    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False),
        daemon=True,
    )
    server.start()

    print(f"ReLIMS Print Service running on http://localhost:{port}")
    print("System tray icon active. Right-click to access menu.")

    # pystray.Icon.run() blocks — this is the main loop
    icon.run()


def run_server():
    """Run the Flask server without system tray."""
    cfg = load_config()
    port = cfg["api_port"]
    print(f"ReLIMS Print Service running on http://localhost:{port}")
    print("Press Ctrl+C to stop.")

    # Handle SIGTERM for graceful shutdown
    def handle_signal(signum, frame):
        print("\nShutting down...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    if "--no-tray" in sys.argv or "--headless" in sys.argv:
        run_server()
    else:
        start_tray()
