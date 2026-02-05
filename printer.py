import socket
from config import load_config

try:
    import win32print
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


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
            return {"success": True, "copies": copies}
        except socket.timeout:
            return {"success": False, "error": f"Connection timed out to {self.host}:{self.port}"}
        except OSError as e:
            return {"success": False, "error": f"Network error: {e}"}


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
            return {"success": True, "copies": copies, "printer": self.printer_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
