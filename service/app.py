"""ReLIMS Print Service for Windows.

A headless local service that receives print jobs from the browser
and sends them to Windows or network printers via ZPL or image data.
"""
import base64
import collections
import logging
import re
import sys
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import load_config, save_config, get_config_path
from printer import get_printer, WindowsPrinter, HAS_WIN32
from version import VERSION, COMPONENT

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

_START_TIME = time.time()

# Recall factory settings (^JUF — active only, never saved, so a power cycle
# restores the printer's own config) then re-run media calibration (~JC), which
# ^JUF discards along with the learned label length. Mirrors the legacy VB pair
# RestoreDefaults() + Calibrate() in LIMS_App/DarkerPrint.vb.
PRINTER_RESET_ZPL = "^XA^JUF^XZ~JC"
# Must cover the whole ~JC media feed on its own. Kept in step with app_linux.py,
# where a CUPS usb-backend stall used to mask most of the feed until a `unidir`
# USB quirk removed it. Raised from the legacy 2.0s — it is the value to re-tune
# if a calibration label ever renders while the media is still feeding.
PRINTER_RESET_SETTLE_SECONDS = 6.0

# ^MD is a RELATIVE darkness adjustment layered on the printer's own setting
# (~SD / front panel), so 0 means "leave the printer alone". Zebra's documented
# range is -30..+30.
DARKNESS_MIN = -30
DARKNESS_MAX = 30


def reset_printer_defaults(printer):
    """Send a factory-recall + media-calibration job and wait for it to settle.

    Sent as its own job rather than glued onto the caller's ZPL so the media
    feed finishes before the next label renders — the same reason the legacy
    app slept 2s after resetting.
    """
    result = printer.print_zpl(PRINTER_RESET_ZPL, copies=1)
    if not result.get("success"):
        logger.warning("Printer reset failed: %s", result.get("error"))
        return result
    logger.info("Printer reset to factory defaults + media calibration")
    time.sleep(PRINTER_RESET_SETTLE_SECONDS)
    return result


def apply_zpl_offsets(zpl):
    """Adjust ZPL positioning using calibrated origin + fine-tune offsets.

    When calibration is active (label_origin_x/y > 0), REPLACES the ^LH
    in incoming ZPL with the calibrated label-edge position. This means
    Django's ^LH140,30 (a guess) gets replaced with the measured position,
    and all ^FO content positions are preserved relative to the label edge.

    When calibration is NOT active, falls back to additive fine-tune only.
    """
    cfg = load_config()
    origin_x = int(cfg.get("label_origin_x", 0))
    origin_y = int(cfg.get("label_origin_y", 0))
    fine_x = int(cfg.get("label_offset_x", 0))
    fine_y = int(cfg.get("label_offset_y", 0))
    calibrated = origin_x > 0 or origin_y > 0

    if calibrated:
        # REPLACE mode: set ^LH to the calibrated label edge + fine-tune.
        # This overrides whatever ^LH Django sent (e.g., ^LH140,30) with
        # the measured printhead-to-label offset.
        lh_x = max(0, origin_x + fine_x)
        lh_y = max(0, origin_y + fine_y)

        def replace_lh(match):
            return f"^LH{lh_x},{lh_y}"

        if re.search(r'\^LH\d+,\d+', zpl, re.IGNORECASE):
            zpl = re.sub(r'\^LH(\d+),(\d+)', replace_lh, zpl, flags=re.IGNORECASE)
        else:
            zpl = re.sub(r'(\^XA)', rf'\1^LH{lh_x},{lh_y}', zpl, flags=re.IGNORECASE)

        # Override ^PW to full printhead width so content at the calibrated
        # offset isn't clipped by the printer's stored print width.
        if re.search(r'\^PW\d+', zpl, re.IGNORECASE):
            zpl = re.sub(r'\^PW\d+', '^PW832', zpl, flags=re.IGNORECASE)
        else:
            zpl = re.sub(r'(\^XA)', r'\1^PW832', zpl, flags=re.IGNORECASE)
    else:
        # ADDITIVE mode (no calibration): just add fine-tune to existing ^LH.
        if fine_x == 0 and fine_y == 0:
            return zpl

        def adjust_lh(match):
            x = int(match.group(1)) + fine_x
            y = int(match.group(2)) + fine_y
            return f"^LH{max(0, x)},{max(0, y)}"

        if re.search(r'\^LH\d+,\d+', zpl, re.IGNORECASE):
            zpl = re.sub(r'\^LH(\d+),(\d+)', adjust_lh, zpl, flags=re.IGNORECASE)
        else:
            lh = f"^LH{max(0, fine_x)},{max(0, fine_y)}"
            zpl = re.sub(r'(\^XA)', r'\1' + lh, zpl, flags=re.IGNORECASE)

    return zpl


def apply_zpl_darkness(zpl):
    """Inject ^MD<n> so labels print lighter (negative) or darker (positive).

    ^MD is relative to the printer's own darkness (~SD / front panel), so a
    configured 0 emits nothing at all and leaves the outgoing ZPL byte-identical
    to what an unconfigured service would send.

    Darkness is label-global — it affects barcodes and graphics along with text.
    ZPL has no text-only darkness; the Django renderer's `bold` double-strike is
    the closest equivalent for text alone.
    """
    cfg = load_config()
    try:
        darkness = int(cfg.get("label_darkness", 0))
    except (TypeError, ValueError):
        return zpl
    # Clamp rather than reject, so a hand-edited config.json can never produce
    # out-of-range ZPL.
    darkness = max(DARKNESS_MIN, min(DARKNESS_MAX, darkness))
    if darkness == 0:
        return zpl
    # Strip any ^MD already present — Zebra treats multiple ^MD commands within
    # one format as CUMULATIVE, so layering ours on top would compound.
    zpl = re.sub(r'\^MD-?\d+', '', zpl, flags=re.IGNORECASE)
    # Unbounded: one ^MD per format, so a multi-format payload is covered too.
    return re.sub(r'(\^XA)', rf'\1^MD{darkness}', zpl, flags=re.IGNORECASE)


def prepare_zpl(zpl):
    """Apply every outbound ZPL transform: position first, then darkness.

    Darkness is deliberately NOT folded into apply_zpl_offsets — that function
    returns early when no fine-tune is set, which would skip darkness entirely.
    """
    return apply_zpl_darkness(apply_zpl_offsets(zpl))


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/status")
def status():
    return jsonify({"status": "ok", "version": VERSION, "win32": HAS_WIN32, "platform": "windows"})


@app.route("/health")
def health():
    """Rich health check for frontend integrations (see docs/INTEGRATION.md)."""
    cfg = load_config()
    backend = cfg.get("backend", "windows")
    backend_available = HAS_WIN32 if backend == "windows" else True
    printer_configured = bool(
        cfg.get("printer_host") if backend == "network" else cfg.get("printer_name")
    )
    return jsonify({
        "service": COMPONENT,
        "status": "ok" if backend_available and printer_configured else "degraded",
        "version": VERSION,
        "platform": "windows",
        "backend": backend,
        "backend_available": backend_available,
        "printer_configured": printer_configured,
        "uptime_seconds": int(time.time() - _START_TIME),
    })


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
    allowed = {"printer_name", "printer_host", "printer_port", "backend", "api_port", "timeout",
               "label_offset_x", "label_offset_y",
               "label_origin_x", "label_origin_y", "label_width", "label_height",
               "label_darkness"}
    filtered = {k: v for k, v in data.items() if k in allowed}
    for int_key in ("printer_port", "api_port", "timeout", "label_offset_x", "label_offset_y",
                    "label_origin_x", "label_origin_y", "label_width", "label_height",
                    "label_darkness"):
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
    raw = data.get("raw", False)
    reset_printer = data.get("reset_printer", False)
    try:
        printer = get_printer()
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    logger.info("/print request: copies=%d, has_image=%s, has_zpl=%s, raw=%s, reset=%s",
                copies, bool(image_b64), bool(zpl), raw, reset_printer)

    # Prefer ZPL when available — ZPL printers (e.g. Zebra ZD220) need raw
    # ZPL commands via win32print RAW.  Image printing via PowerShell
    # PrintDocument may "succeed" at the OS/spooler level but produce no
    # output because the ZPL driver cannot render raster data.
    if zpl:
        # A failed reset is logged but does not block the print — a non-Zebra
        # unit that rejects ^JUF should still be able to print.
        if reset_printer:
            reset_printer_defaults(printer)
        final_zpl = zpl if raw else prepare_zpl(zpl)
        result = printer.print_zpl(final_zpl, copies=copies)
        if result["success"] or not image_b64:
            status_code = 200 if result["success"] else 500
            return jsonify(result), status_code
        # ZPL failed but we have image as fallback
        logger.info("ZPL print failed, falling back to image")
    # Image fallback (or image-only request for Citizen/driver-based printers)
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

    # Prefer ZPL batch (same reasoning as /print — ZPL printers need raw commands)
    if zpls:
        shifted = [prepare_zpl(z) for z in zpls]
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
    app.run(host="127.0.0.1", port=port, debug=debug)


if __name__ == "__main__":
    main()
