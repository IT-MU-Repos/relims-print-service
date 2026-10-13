"""ReLIMS Print Service for Windows.

A headless local service that receives print jobs from the browser
and sends them to Windows or network printers via ZPL or image data.
"""
import base64
import collections
import functools
import logging
import sys
import threading
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import (
    load_config, save_config, get_config_path, filter_config_payload,
    get_allowed_origins, PRINT_OVERRIDE_KEYS,
)
from printer import get_printer, WindowsPrinter, HAS_WIN32
from version import VERSION, COMPONENT
from zpl import (
    build_restore_epilogue, carries_printer_config, hand_back, prepare_zpl,
    restore_mode, strip_persistent,
)

app = Flask(__name__, static_folder="static", static_url_path="/static")
# Not CORS(app): the service listens on loopback, but loopback is reachable
# from any page the browser has open, and every route below either prints or
# changes settings. Without an allowlist any site a lab PC visits could
# print through it or rewrite its settings.
CORS(app, origins=get_allowed_origins())

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


def require_allowed_origin(view):
    """Reject a cross-origin caller that is not on the allowlist.

    Only requests that actually carry an `Origin` are checked: a browser sets
    it on exactly the cross-site requests this is here to stop, while curl,
    the installer's smoke test and the manager tray send none.

    CORS(...) alone is not enough. It makes a browser withhold the *response*
    from a disallowed origin, but the request still arrives and the side effect
    still happens — the label is already printed, or the settings already
    saved, by the time the page is denied the reply.
    """
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        origin = request.headers.get("Origin")
        if origin and origin not in get_allowed_origins():
            logger.warning("Rejected %s from disallowed origin %s", request.path, origin)
            return jsonify({
                "success": False,
                "error": f"Origin {origin} is not allowed to use this print service.",
            }), 403
        return view(*args, **kwargs)
    return wrapped


def _printer_configured(cfg):
    if cfg.get("backend") == "network":
        return bool(cfg.get("printer_host"))
    return bool(cfg.get("printer_name"))


def _refuse_printer_config():
    logger.warning("Refused a job carrying a printer configuration block")
    return jsonify({
        "success": False,
        "error": "This job contains a printer configuration block (~!!). "
                 "The print service never changes the printer's own settings.",
    }), 400


def send_startup_restore(cfg=None):
    """Hand the printer back once when the service starts.

    Covers a crash between a label and its restore, and printers that a
    pre-2.1.0 service left holding its settings — those are cleaned up the
    moment a lab PC auto-updates, without anyone power-cycling the printer.
    """
    cfg = load_config() if cfg is None else cfg
    if not _printer_configured(cfg):
        return None
    try:
        printer = get_printer(cfg)
    except RuntimeError as e:
        logger.warning("Startup hand-back skipped: %s", e)
        return None
    return hand_back(printer, cfg, logger, "service startup")


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
    printer_configured = _printer_configured(cfg)
    return jsonify({
        "service": COMPONENT,
        "status": "ok" if backend_available and printer_configured else "degraded",
        "version": VERSION,
        "platform": "windows",
        "backend": backend,
        "backend_available": backend_available,
        "printer_configured": printer_configured,
        "restore_mode": restore_mode(cfg),
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
@require_allowed_origin
def update_config():
    data = request.get_json(force=True)
    updated = save_config(filter_config_payload(data))
    return jsonify(updated)


def resolve_request_config(data):
    """Merge a job's optional `config` override over the saved settings.

    Returns (config, overridden_keys). Nothing is written to disk: this is how
    Test Print renders through the values shown on the settings page before the
    user has decided to keep them. Saving stays the job of POST /config alone.
    """
    cfg = load_config()
    override = filter_config_payload((data or {}).get("config"), PRINT_OVERRIDE_KEYS)
    if not override:
        return cfg, []
    cfg.update(override)
    return cfg, sorted(override)


@app.route("/print", methods=["POST"])
@require_allowed_origin
def print_label():
    data = request.get_json(force=True)
    zpl = data.get("zpl", "").strip()
    image_b64 = data.get("image", "").strip()
    if not zpl and not image_b64:
        return jsonify({"success": False, "error": "No ZPL or image data provided"}), 400
    if carries_printer_config(zpl):
        return _refuse_printer_config()
    copies = max(1, int(data.get("copies", 1)))
    raw = data.get("raw", False)
    if data.get("reset_printer"):
        # Kept as an accepted key so older callers still print, but the reset
        # it asked for is gone — see zpl.py.
        logger.warning("/print: ignoring reset_printer — the service never resets the printer")
    cfg, overridden = resolve_request_config(data)
    try:
        printer = get_printer(cfg)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    logger.info("/print request: copies=%d, has_image=%s, has_zpl=%s, raw=%s, override=%s",
                copies, bool(image_b64), bool(zpl), raw, overridden or "none")

    # Prefer ZPL when available — ZPL printers (e.g. Zebra ZD220) need raw
    # ZPL commands via win32print RAW.  Image printing via PowerShell
    # PrintDocument may "succeed" at the OS/spooler level but produce no
    # output because the ZPL driver cannot render raster data.
    if zpl:
        final_zpl = strip_persistent(zpl if raw else prepare_zpl(zpl, cfg))
        # Outside the `raw` branch on purpose. `raw` means "do not rewrite my
        # ZPL", not "do not clean up after it" — a raw payload still leaves its
        # own ^PW/^LL/^CI in the printer's active configuration, and the
        # calibration ruler is raw.
        epilogue = build_restore_epilogue(cfg)
        result = printer.print_zpl(final_zpl, copies=copies, epilogue=epilogue)
        if result["success"]:
            logger.info("/print: restore sent with the job: %s", epilogue or "none (mode off)")
        else:
            # The label may have reached the printer without its restore.
            hand_back(printer, cfg, logger, "after a failed /print")
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
@require_allowed_origin
def print_batch():
    data = request.get_json(force=True)
    zpls = data.get("zpls", [])
    images_b64 = data.get("images", [])
    if not zpls and not images_b64:
        return jsonify({"success": False, "error": "No zpls or images provided"}), 400
    if any(carries_printer_config(z) for z in zpls):
        return _refuse_printer_config()
    copies = max(1, int(data.get("copies", 1)))
    # No `config` override here — batches come from the apps, which have no
    # settings form behind them. Always the saved configuration.
    cfg = load_config()
    try:
        printer = get_printer(cfg)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    logger.info("/print-batch request: copies=%d, images=%d, zpls=%d",
                copies, len(images_b64), len(zpls))

    # Prefer ZPL batch (same reasoning as /print — ZPL printers need raw commands)
    if zpls:
        shifted = [strip_persistent(prepare_zpl(z, cfg)) for z in zpls]
        epilogue = build_restore_epilogue(cfg)
        if hasattr(printer, 'print_batch_zpl'):
            result = printer.print_batch_zpl(shifted, copies_each=copies, epilogue=epilogue)
        else:
            printed = 0
            for index, zpl in enumerate(shifted):
                # Only after the last label — a restore between labels would
                # print the rest of the batch at the handed-back settings.
                last = index == len(shifted) - 1
                r = printer.print_zpl(
                    zpl, copies=copies, epilogue=epilogue if last else None
                )
                if r["success"]:
                    printed += 1
            result = {"success": printed == len(zpls), "printed": printed, "total": len(zpls)}
        if result["success"]:
            logger.info("/print-batch: restore sent with the job: %s", epilogue or "none (mode off)")
        else:
            # Some labels may have printed without the restore that follows
            # the last one — including when the last label is the one that failed.
            hand_back(printer, cfg, logger, "after a failed /print-batch")
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
    # In the background: a printer that is off or unreachable must not delay
    # the service coming up.
    threading.Thread(target=send_startup_restore, args=(cfg,), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=debug)


if __name__ == "__main__":
    main()
