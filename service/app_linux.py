#!/usr/bin/env python3
"""ReLIMS Print Service for Linux.

A headless local service that receives print jobs from the browser
and sends them to CUPS or network printers via ZPL or image data.
"""
import base64
import collections
import logging
import re
import signal
import sys

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import load_config, save_config, get_config_path
from printer_linux import get_printer, CUPSPrinter, HAS_CUPS
from version import VERSION

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# ---------------------------------------------------------------------------
# Logging — write to file next to config + keep last 200 lines in memory
# ---------------------------------------------------------------------------
LOG_BUFFER_SIZE = 200
_log_buffer = collections.deque(maxlen=LOG_BUFFER_SIZE)


class _BufferHandler(logging.Handler):
    """Keep recent log lines in a deque so /logs can serve them."""
    def emit(self, record):
        _log_buffer.append(self.format(record))


def _setup_logging():
    log_path = get_config_path().parent / "print-service.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    file_handler.setFormatter(fmt)

    buf_handler = _BufferHandler()
    buf_handler.setFormatter(fmt)

    logger = logging.getLogger("print-service")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(buf_handler)

    return logger


logger = _setup_logging()


def apply_zpl_offsets(zpl):
    """Inject ^LS (horizontal) and ^LT (vertical) shift commands into ZPL."""
    cfg = load_config()
    ox = int(cfg.get("label_offset_x", 0))
    oy = int(cfg.get("label_offset_y", 0))
    if ox == 0 and oy == 0:
        return zpl
    cmds = ""
    if ox != 0:
        cmds += f"^LS{ox}"
    if oy != 0:
        cmds += f"^LT{oy}"
    return re.sub(r'(\^XA)', r'\1' + cmds, zpl, flags=re.IGNORECASE)


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
    allowed = {"printer_name", "printer_host", "printer_port", "backend", "api_port", "timeout",
               "label_offset_x", "label_offset_y"}
    filtered = {k: v for k, v in data.items() if k in allowed}
    for int_key in ("printer_port", "api_port", "timeout", "label_offset_x", "label_offset_y"):
        if int_key in filtered:
            filtered[int_key] = int(filtered[int_key])
    updated = save_config(filtered)
    return jsonify(updated)


@app.route("/print", methods=["POST"])
def print_label():
    data = request.get_json(force=True)
    zpl = data.get("zpl", "").strip()
    image_b64 = data.get("image", "").strip()
    if not zpl and not image_b64:
        return jsonify({"success": False, "error": "No ZPL or image data provided"}), 400
    copies = max(1, int(data.get("copies", 1)))
    try:
        printer = get_printer()
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    logger.info("/print request: copies=%d, has_image=%s, has_zpl=%s",
                copies, bool(image_b64), bool(zpl))

    # Prefer ZPL when available — sends raw ZPL commands to the printer.
    if zpl:
        result = printer.print_zpl(apply_zpl_offsets(zpl), copies=copies)
        if result["success"] or not image_b64:
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        # ZPL failed but we have image as fallback
        logger.info("ZPL print failed, falling back to image")
    # Image fallback (or image-only request for driver-based printers)
    if image_b64:
        try:
            image_data = base64.b64decode(image_b64)
        except Exception:
            return jsonify({"success": False, "error": "Invalid base64 image data"}), 400
        result = printer.print_image(image_data, copies=copies)
        status_code = 200 if result["success"] else 500
        return jsonify(result), status_code
    return jsonify({"success": False, "error": "No printable data"}), 400


@app.route("/print-batch", methods=["POST"])
def print_batch():
    data = request.get_json(force=True)
    zpls = data.get("zpls", [])
    images_b64 = data.get("images", [])
    if not zpls and not images_b64:
        return jsonify({"success": False, "error": "No zpls or images provided"}), 400
    copies = max(1, int(data.get("copies", 1)))
    try:
        printer = get_printer()
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    logger.info("/print-batch request: copies=%d, images=%d, zpls=%d",
                copies, len(images_b64), len(zpls))

    # Prefer ZPL batch
    if zpls:
        shifted = [apply_zpl_offsets(z) for z in zpls]
        if hasattr(printer, 'print_batch_zpl'):
            result = printer.print_batch_zpl(shifted, copies_each=copies)
        else:
            printed = 0
            for zpl in shifted:
                r = printer.print_zpl(zpl, copies=copies)
                if r["success"]:
                    printed += 1
            result = {"success": printed == len(zpls), "printed": printed, "total": len(zpls)}
        status_code = 200 if result["success"] else 500
        return jsonify(result), status_code
    # Image batch fallback
    if images_b64:
        try:
            images = [base64.b64decode(img) for img in images_b64]
        except Exception:
            return jsonify({"success": False, "error": "Invalid base64 image data"}), 400
        if hasattr(printer, 'print_batch_images'):
            result = printer.print_batch_images(images, copies_each=copies)
        else:
            printed = 0
            for img in images:
                r = printer.print_image(img, copies=copies)
                if r["success"]:
                    printed += 1
            result = {"success": printed == len(images), "printed": printed, "total": len(images)}
        status_code = 200 if result["success"] else 500
        return jsonify(result), status_code
    return jsonify({"success": False, "error": "No printable data"}), 400


@app.route("/logs")
def get_logs():
    """Return recent log entries for debugging."""
    return jsonify({"lines": list(_log_buffer)})


def main():
    cfg = load_config()
    port = cfg["api_port"]
    debug = "--debug" in sys.argv
    logger.info("ReLIMS Print Service v%s starting on port %d", VERSION, port)
    print(f"ReLIMS Print Service v{VERSION} running on http://localhost:{port}")
    print("Press Ctrl+C to stop.")

    def handle_signal(signum, frame):
        print("\nShutting down...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    app.run(host="127.0.0.1", port=port, debug=debug)


if __name__ == "__main__":
    main()
