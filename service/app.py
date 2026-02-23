"""ReLIMS Print Service for Windows.

A headless local service that receives print jobs from the browser
and sends them to Windows or network printers via ZPL or image data.
"""
import base64
import sys

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import load_config, save_config
from printer import get_printer, WindowsPrinter, HAS_WIN32
from version import VERSION

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/status")
def status():
    return jsonify({"status": "ok", "version": VERSION, "win32": HAS_WIN32})


@app.route("/printers")
def list_printers():
    printers = WindowsPrinter.list_printers() if HAS_WIN32 else []
    default = WindowsPrinter.get_default_printer() if HAS_WIN32 else ""
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
    # If image data is provided and printer supports it, prefer image printing.
    # This is needed for Citizen printers which need images sent through
    # the driver (e.g., ctzcls on CUPS, or Citizen Windows driver) rather than raw ZPL.
    if image_b64:
        try:
            image_data = base64.b64decode(image_b64)
        except Exception:
            return jsonify({"success": False, "error": "Invalid base64 image data"}), 400
        result = printer.print_image(image_data, copies=copies)
        if result["success"] or not zpl:
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        # Image printing failed but we have ZPL as fallback
    result = printer.print_zpl(zpl, copies=copies)
    status_code = 200 if result["success"] else 500
    return jsonify(result), status_code


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
    # Prefer image batch if provided
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
    # ZPL batch
    if hasattr(printer, 'print_batch_zpl'):
        result = printer.print_batch_zpl(zpls, copies_each=copies)
    else:
        printed = 0
        for zpl in zpls:
            r = printer.print_zpl(zpl, copies=copies)
            if r["success"]:
                printed += 1
        result = {"success": printed == len(zpls), "printed": printed, "total": len(zpls)}
    status_code = 200 if result["success"] else 500
    return jsonify(result), status_code


def main():
    cfg = load_config()
    port = cfg["api_port"]
    debug = "--debug" in sys.argv
    print(f"ReLIMS Print Service v{VERSION} running on http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)


if __name__ == "__main__":
    main()
