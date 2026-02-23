"""Linux printing backend using CUPS."""
import os
import shutil
import socket
import subprocess
import tempfile
from config import load_config

# Check if CUPS is available (lp command)
HAS_CUPS = shutil.which('lp') is not None


class NetworkPrinter:
    """Send ZPL to a network printer via TCP/IP on port 9100."""

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

    def print_image(self, image_data, copies=1):
        return {"success": False, "error": "Image printing not supported over network. Use ZPL or switch to CUPS backend."}

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
            return {"success": True, "printed": printed, "total": len(zpls)}
        except socket.timeout:
            return {"success": False, "printed": printed, "total": len(zpls), "error": f"Connection timed out to {self.host}:{self.port}"}
        except OSError as e:
            return {"success": False, "printed": printed, "total": len(zpls), "error": f"Network error: {e}"}


class CUPSPrinter:
    """Send ZPL to a CUPS printer using the lp command."""

    def __init__(self, printer_name=None, timeout=None):
        if not HAS_CUPS:
            raise RuntimeError("CUPS not available (lp command not found)")
        cfg = load_config()
        self.printer_name = printer_name or cfg["printer_name"]
        self.timeout = timeout or cfg.get("timeout", 30)

    def print_zpl(self, zpl, copies=1):
        if not self.printer_name:
            return {"success": False, "error": "Printer name not configured"}
        try:
            cmd = [
                'lp',
                '-d', self.printer_name,
                '-n', str(copies),
                '-o', 'raw',
                '-',
            ]
            result = subprocess.run(
                cmd,
                input=zpl.encode('utf-8'),
                capture_output=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8').strip()
                return {"success": False, "error": f"CUPS print failed: {error_msg}"}
            return {"success": True, "copies": copies, "printer": self.printer_name}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Print command timed out after {self.timeout} seconds"}
        except OSError as e:
            return {"success": False, "error": f"Failed to execute lp command: {e}"}

    def print_image(self, image_data, copies=1):
        """Print PNG image data through the CUPS driver pipeline.

        Sends PNG to CUPS without -o raw, so the printer driver
        (e.g., ctzcls for Citizen) processes and rasterizes the image.
        """
        if not self.printer_name:
            return {"success": False, "error": "Printer name not configured"}
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_data)
                tmp_path = f.name
            cmd = [
                'lp',
                '-d', self.printer_name,
                '-n', str(copies),
                '-o', 'fit-to-page',
                tmp_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8').strip()
                return {"success": False, "error": f"CUPS print failed: {error_msg}"}
            return {"success": True, "copies": copies, "printer": self.printer_name}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Print command timed out after {self.timeout} seconds"}
        except OSError as e:
            return {"success": False, "error": f"Failed to execute lp command: {e}"}
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def print_batch_zpl(self, zpls, copies_each=1):
        """Send multiple ZPL labels in a single CUPS job."""
        if not self.printer_name:
            return {"success": False, "printed": 0, "total": len(zpls), "error": "Printer name not configured"}
        try:
            combined = ''
            for zpl in zpls:
                combined += zpl * copies_each
            cmd = [
                'lp',
                '-d', self.printer_name,
                '-o', 'raw',
                '-',
            ]
            result = subprocess.run(
                cmd,
                input=combined.encode('utf-8'),
                capture_output=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8').strip()
                return {"success": False, "printed": 0, "total": len(zpls), "error": f"CUPS print failed: {error_msg}"}
            return {"success": True, "printed": len(zpls), "total": len(zpls)}
        except subprocess.TimeoutExpired:
            return {"success": False, "printed": 0, "total": len(zpls), "error": f"Print command timed out after {self.timeout} seconds"}
        except OSError as e:
            return {"success": False, "printed": 0, "total": len(zpls), "error": f"Failed to execute lp command: {e}"}

    def print_batch_images(self, images, copies_each=1):
        """Send multiple PNG images in a single CUPS job.

        Writes all images to temp files and passes them to one lp call,
        avoiding the overhead of spawning a subprocess per label.
        """
        if not self.printer_name:
            return {"success": False, "printed": 0, "total": len(images), "error": "Printer name not configured"}
        tmp_paths = []
        try:
            for image_data in images:
                f = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                f.write(image_data)
                f.close()
                tmp_paths.append(f.name)
            # Build file list with copies: [f1, f1, f2, f2, ...] for copies_each=2
            file_list = []
            for path in tmp_paths:
                for _ in range(copies_each):
                    file_list.append(path)
            cmd = [
                'lp',
                '-d', self.printer_name,
                '-o', 'fit-to-page',
            ] + file_list
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8').strip()
                return {"success": False, "printed": 0, "total": len(images), "error": f"CUPS print failed: {error_msg}"}
            return {"success": True, "printed": len(images), "total": len(images)}
        except subprocess.TimeoutExpired:
            return {"success": False, "printed": 0, "total": len(images), "error": f"Print command timed out after {self.timeout} seconds"}
        except OSError as e:
            return {"success": False, "printed": 0, "total": len(images), "error": f"Failed to execute lp command: {e}"}
        finally:
            for p in tmp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    @staticmethod
    def list_printers():
        """List available CUPS printers."""
        if not HAS_CUPS:
            return []
        try:
            result = subprocess.run(
                ['lpstat', '-a'],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            lines = result.stdout.decode('utf-8').strip().split('\n')
            printers = []
            for line in lines:
                if line:
                    # lpstat -a output: "PrinterName accepting requests since..."
                    parts = line.split()
                    if parts:
                        printers.append(parts[0])
            return printers
        except (subprocess.TimeoutExpired, OSError):
            return []

    @staticmethod
    def get_default_printer():
        """Get the default CUPS printer."""
        if not HAS_CUPS:
            return ""
        try:
            result = subprocess.run(
                ['lpstat', '-d'],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                return ""
            # Output: "system default destination: PrinterName"
            output = result.stdout.decode('utf-8').strip()
            if ':' in output:
                return output.split(':')[-1].strip()
            return ""
        except (subprocess.TimeoutExpired, OSError):
            return ""


def get_printer():
    """Get the appropriate printer based on configuration."""
    cfg = load_config()
    backend = cfg.get("backend", "cups")

    if backend == "network":
        return NetworkPrinter()

    # Default to CUPS on Linux
    if not HAS_CUPS:
        raise RuntimeError(
            "CUPS printer backend selected but lp command is not available. "
            "Install CUPS or switch to 'network' backend."
        )
    return CUPSPrinter()
