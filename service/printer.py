import logging
import os
import socket
import subprocess
import tempfile
from config import load_config

try:
    import win32print
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

logger = logging.getLogger("print-service")


class NetworkPrinter:
    def __init__(self, host=None, port=None, timeout=None):
        cfg = load_config()
        self.host = host or cfg["printer_host"]
        self.port = port or cfg["printer_port"]
        self.timeout = timeout or cfg["timeout"]

    def print_zpl(self, zpl, copies=1):
        if not self.host:
            return {"success": False, "error": "Printer host not configured"}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
                for _ in range(copies):
                    sock.sendall(zpl.encode("utf-8"))
            logger.info("ZPL sent to %s:%s (%d copies)", self.host, self.port, copies)
            return {"success": True, "copies": copies}
        except socket.timeout:
            msg = f"Connection timed out to {self.host}:{self.port}"
            logger.error("ZPL print failed: %s", msg)
            return {"success": False, "error": msg}
        except OSError as e:
            logger.error("ZPL print failed: %s", e)
            return {"success": False, "error": f"Network error: {e}"}

    def print_image(self, image_data, copies=1):
        return {"success": False, "error": "Image printing not supported over network. Use ZPL or switch to Windows/CUPS backend."}

    def print_batch_zpl(self, zpls, copies_each=1):
        """Send multiple ZPL labels through a single TCP connection."""
        if not self.host:
            return {"success": False, "printed": 0, "total": len(zpls), "error": "Printer host not configured"}
        printed = 0
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
                for zpl in zpls:
                    for _ in range(copies_each):
                        sock.sendall(zpl.encode("utf-8"))
                    printed += 1
            logger.info("ZPL batch sent to %s:%s (%d/%d)", self.host, self.port, printed, len(zpls))
            return {"success": True, "printed": printed, "total": len(zpls)}
        except socket.timeout:
            msg = f"Connection timed out to {self.host}:{self.port}"
            logger.error("ZPL batch failed after %d/%d: %s", printed, len(zpls), msg)
            return {"success": False, "printed": printed, "total": len(zpls), "error": msg}
        except OSError as e:
            logger.error("ZPL batch failed after %d/%d: %s", printed, len(zpls), e)
            return {"success": False, "printed": printed, "total": len(zpls), "error": f"Network error: {e}"}


class WindowsPrinter:
    def __init__(self, printer_name=None):
        if not HAS_WIN32:
            raise RuntimeError("win32print not available (Windows only)")
        cfg = load_config()
        self.printer_name = printer_name or cfg["printer_name"] or win32print.GetDefaultPrinter()

    def print_zpl(self, zpl, copies=1):
        try:
            handle = win32print.OpenPrinter(self.printer_name)
            try:
                win32print.StartDocPrinter(handle, 1, ("ZPL Label", None, "RAW"))
                win32print.StartPagePrinter(handle)
                for _ in range(copies):
                    win32print.WritePrinter(handle, zpl.encode("utf-8"))
                win32print.EndPagePrinter(handle)
                win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
            logger.info("ZPL sent to '%s' (%d copies)", self.printer_name, copies)
            return {"success": True, "copies": copies, "printer": self.printer_name}
        except Exception as e:
            logger.error("ZPL print to '%s' failed: %s", self.printer_name, e)
            return {"success": False, "error": str(e)}

    def print_batch_zpl(self, zpls, copies_each=1):
        """Send multiple ZPL labels through a single Windows print job."""
        try:
            handle = win32print.OpenPrinter(self.printer_name)
            try:
                win32print.StartDocPrinter(handle, 1, ("ZPL Batch", None, "RAW"))
                win32print.StartPagePrinter(handle)
                printed = 0
                for zpl in zpls:
                    for _ in range(copies_each):
                        win32print.WritePrinter(handle, zpl.encode("utf-8"))
                    printed += 1
                win32print.EndPagePrinter(handle)
                win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
            logger.info("ZPL batch to '%s' (%d/%d)", self.printer_name, printed, len(zpls))
            return {"success": True, "printed": printed, "total": len(zpls), "printer": self.printer_name}
        except Exception as e:
            logger.error("ZPL batch to '%s' failed: %s", self.printer_name, e)
            return {"success": False, "printed": 0, "total": len(zpls), "error": str(e)}

    def print_image(self, image_data, copies=1):
        """Print PNG image data through the Windows printer driver.

        Uses PowerShell with .NET System.Drawing.Printing to send
        the image through the driver (e.g., Citizen driver) instead
        of sending raw data.
        """
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_data)
                tmp_path = f.name
            logger.info("Image print to '%s' (%d copies, %d bytes, tmp=%s)",
                        self.printer_name, copies, len(image_data), tmp_path)
            ps_script = (
                'Add-Type -AssemblyName System.Drawing; '
                f'$img = [System.Drawing.Image]::FromFile("{tmp_path}"); '
                '$pd = New-Object System.Drawing.Printing.PrintDocument; '
                '$pd.PrintController = New-Object System.Drawing.Printing.StandardPrintController; '
                f'$pd.PrinterSettings.PrinterName = "{self.printer_name}"; '
                f'$pd.PrinterSettings.Copies = {copies}; '
                '$pd.add_PrintPage({ param($s,$e) '
                '$e.Graphics.DrawImage($img, $e.MarginBounds) }); '
                '$pd.Print(); $img.Dispose(); $pd.Dispose()'
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive',
                 '-WindowStyle', 'Hidden', '-Command', ps_script],
                capture_output=True,
                timeout=30,
            )
            stdout = result.stdout.decode('utf-8', errors='replace').strip()
            stderr = result.stderr.decode('utf-8', errors='replace').strip()
            if stdout:
                logger.info("PowerShell stdout: %s", stdout)
            if stderr:
                logger.warning("PowerShell stderr: %s", stderr)
            if result.returncode != 0:
                logger.error("Image print failed (exit %d): %s", result.returncode, stderr)
                return {"success": False, "error": f"Print failed: {stderr}", "detail": stderr}
            logger.info("Image print succeeded (exit 0)")
            return {"success": True, "copies": copies, "printer": self.printer_name,
                    "detail": stderr if stderr else None}
        except subprocess.TimeoutExpired:
            logger.error("Image print timed out")
            return {"success": False, "error": "Print command timed out"}
        except OSError as e:
            logger.error("Image print OS error: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def list_printers():
        if not HAS_WIN32:
            return []
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        printers = win32print.EnumPrinters(flags, None, 1)
        return [p[2] for p in printers]

    @staticmethod
    def get_default_printer():
        if not HAS_WIN32:
            return ""
        try:
            return win32print.GetDefaultPrinter()
        except Exception:
            return ""


def get_printer():
    cfg = load_config()
    if cfg["backend"] == "network":
        return NetworkPrinter()
    if not HAS_WIN32:
        raise RuntimeError(
            "Windows printer backend selected but win32print is not available. "
            "Switch to 'network' backend or run on Windows."
        )
    return WindowsPrinter()
