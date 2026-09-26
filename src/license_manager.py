"""License and activation management for AI Dubber Ultimate.

Provides machine-independent and offline-first license verification,
CPU/Hardware ID generation across platforms (Windows, Linux, macOS),
and key generation and validation.
"""

import base64
from datetime import datetime, timedelta
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
    from PyQt5.QtGui import QDesktopServices, QPixmap
    from PyQt5.QtWidgets import (
        QApplication,
        QButtonGroup,
        QComboBox,
        QDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
    )
except ImportError:
    class QThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass
        def quit(self):
            pass
        def wait(self):
            pass

    class _DummySignal:
        def emit(self, *args, **kwargs):
            pass
        def connect(self, slot):
            pass

    def pyqtSignal(*args, **kwargs):
        return _DummySignal()

    class _DummyQt:
        AlignCenter = 0
        WindowContextHelpButtonHint = 0
        PointingHandCursor = 0
    Qt = _DummyQt()
    QApplication = None
    QDialog = object
    QMessageBox = None

GOOGLE_SHEET_API_URL = 'https://script.google.com/macros/s/AKfycbyMmpDvrSyhMGowZ996JcFojl2uHEIO_D10XzPJVly8uXMGtfLUT6n-Hlezi9KOmHIl/exec'
LICENSE_REQUEST_TIMEOUT_SECONDS = 12
LICENSE_REQUEST_RETRY_ATTEMPTS = 3
GLOBAL_LICENSE_INFO = None


class LicenseManager:
    """Manage license validation and activation (VERSION-INDEPENDENT)."""

    MASTER_KEY = b'AI_DUBBER_ULTIMATE_2026_SIKMENG_KHMER'

    @staticmethod
    def get_cpu_id():
        """Generate a stable 32-character hardware identifier for this machine."""
        hardware_ids = []
        if sys.platform == 'win32':
            try:
                out = subprocess.check_output('wmic cpu get ProcessorId', shell=True, stderr=subprocess.DEVNULL)
                lines = [line.strip() for line in out.decode(errors='ignore').splitlines() if line.strip()]
                if len(lines) > 1 and lines[1]:
                    hardware_ids.append(lines[1])
            except Exception:
                pass

            try:
                out = subprocess.check_output('wmic baseboard get SerialNumber', shell=True, stderr=subprocess.DEVNULL)
                lines = [line.strip() for line in out.decode(errors='ignore').splitlines() if line.strip()]
                if len(lines) > 1 and lines[1]:
                    hardware_ids.append(lines[1])
            except Exception:
                pass

            try:
                out = subprocess.check_output('wmic bios get SerialNumber', shell=True, stderr=subprocess.DEVNULL)
                lines = [line.strip() for line in out.decode(errors='ignore').splitlines() if line.strip()]
                if len(lines) > 1 and lines[1]:
                    hardware_ids.append(lines[1])
            except Exception:
                pass

            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography')
                machine_guid, _ = winreg.QueryValueEx(key, 'MachineGuid')
                winreg.CloseKey(key)
                if machine_guid:
                    hardware_ids.append(machine_guid)
            except Exception:
                pass
        elif sys.platform.startswith('linux'):
            # Linux machine id
            for path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
                try:
                    if os.path.exists(path):
                        with open(path, 'r') as f:
                            mid = f.read().strip()
                            if mid:
                                hardware_ids.append(mid)
                                break
                except Exception:
                    pass
        elif sys.platform == 'darwin':
            # macOS IOPlatformUUID
            try:
                out = subprocess.check_output(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'], stderr=subprocess.DEVNULL)
                for line in out.decode(errors='ignore').splitlines():
                    if 'IOPlatformUUID' in line:
                        parts = line.split('" = "')
                        if len(parts) > 1:
                            hardware_ids.append(parts[1].rstrip('"'))
            except Exception:
                pass

        try:
            mac = uuid.getnode()
            hardware_ids.append(str(mac))
        except Exception:
            pass

        try:
            if hardware_ids:
                combined = '|'.join(sorted(hardware_ids))
                return hashlib.sha256(combined.encode()).hexdigest().upper()[:32]
            return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest().upper()[:32]
        except Exception as e:
            print(f"[DEBUG] CPU ID generation error: {e}")
            return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest().upper()[:32]

    @staticmethod
    def get_license_file():
        """Return the path to the primary license file and ensure its directory exists."""
        candidate_dirs = []
        if sys.platform == 'win32':
            app_data = os.environ.get('APPDATA')
            if app_data:
                candidate_dirs.append(os.path.join(app_data, 'AI Dubbing Tool'))
            local_app_data = os.environ.get('LOCALAPPDATA')
            if local_app_data:
                candidate_dirs.append(os.path.join(local_app_data, 'AI Dubbing Tool'))

        candidate_dirs.append(os.path.join(os.path.expanduser('~'), '.config', 'ai_dubber'))
        candidate_dirs.append(os.path.join(os.getcwd(), '.license_data'))

        hidden_dir = None
        for candidate_dir in candidate_dirs:
            try:
                os.makedirs(candidate_dir, exist_ok=True)
                hidden_dir = candidate_dir
                break
            except OSError:
                continue

        if not hidden_dir:
            hidden_dir = os.path.join(os.path.expanduser('~'), '.config', 'ai_dubber')
            os.makedirs(hidden_dir, exist_ok=True)

        license_file = os.path.join(hidden_dir, '.license')
        backup_file = os.path.join(hidden_dir, '.license_backup')

        if os.path.exists(license_file):
            try:
                if os.path.exists(backup_file):
                    with open(license_file, 'r', encoding='utf-8') as f1, open(backup_file, 'r', encoding='utf-8') as f2:
                        if f1.read() != f2.read():
                            shutil.copy2(license_file, backup_file)
                else:
                    shutil.copy2(license_file, backup_file)
            except Exception:
                pass
        elif os.path.exists(backup_file):
            try:
                shutil.copy2(backup_file, license_file)
            except Exception:
                pass

        return license_file

    @staticmethod
    def save_license(license_key):
        """Save license key to both primary and backup storage locations."""
        try:
            license_file = LicenseManager.get_license_file()
            with open(license_file, 'w', encoding='utf-8') as f:
                f.write(license_key)

            try:
                app_data = os.path.expanduser('~')
                hidden_dir = os.path.join(app_data, '.config', 'ai_dubber')
                os.makedirs(hidden_dir, exist_ok=True)
                backup_file = os.path.join(hidden_dir, '.license_backup')
                with open(backup_file, 'w', encoding='utf-8') as f:
                    f.write(license_key)
            except Exception:
                pass
            return True
        except Exception:
            return False

    @staticmethod
    def load_license():
        """Load stored license key from disk."""
        try:
            license_file = LicenseManager.get_license_file()
            if os.path.exists(license_file):
                with open(license_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        except Exception:
            pass
        return None

    @staticmethod
    def validate_key(license_key, cpu_id):
        """Validate offline key format, CPU binding, cryptographic signature, and expiry."""
        try:
            encoded = license_key.replace('-', '').strip()
            decoded = base64.b64decode(encoded).decode()
            parts = decoded.split('|')
            if len(parts) != 4:
                return False, None, None, 0, 'Invalid key format'

            key_cpu_id, expiry, license_type, signature = parts
            if key_cpu_id != cpu_id:
                return False, None, None, 0, 'Key does not match this computer'

            license_data = f"{key_cpu_id}|{expiry}|{license_type}"
            sig_input = (license_data + LicenseManager.MASTER_KEY.decode()).encode()
            expected_signature = hashlib.sha256(sig_input).hexdigest()[:16]
            if signature != expected_signature:
                return False, None, None, 0, 'Key signature invalid'

            if expiry == '9999-12-31':
                return True, expiry, license_type, 999999, 'Lifetime license (works on all versions)'

            expiry_date = datetime.strptime(expiry, '%Y-%m-%d')
            days_remaining = (expiry_date - datetime.now()).days
            if days_remaining < 0:
                return False, expiry, license_type, days_remaining, 'License expired'
            return True, expiry, license_type, days_remaining, 'Valid license (works on all versions)'
        except Exception as e:
            return False, None, None, 0, f"Validation error: {e}"


def _sys_check():
    """Legacy function - kept for compatibility."""
    _k = b'c2hlYWttZW5nMjAyNg=='
    return base64.b64decode(_k).decode('utf-8')


def _build_local_license_key(cpu_id, expiry, license_type):
    """Create the same offline license format used by validate_key."""
    license_data = f"{cpu_id}|{expiry}|{license_type}"
    sig_input = (license_data + LicenseManager.MASTER_KEY.decode()).encode()
    signature = hashlib.sha256(sig_input).hexdigest()[:16]
    encoded = base64.b64encode(f"{license_data}|{signature}".encode()).decode()
    return '-'.join(encoded[i:i + 5] for i in range(0, len(encoded), 5))


def _save_server_activation_for_offline_start(cpu_id, result):
    """Cache a successful server activation so future launches do not need internet."""
    try:
        exp_str = str(result.get('expiry', '9999-12-31') or '9999-12-31')
        l_type = str(result.get('type', 'Lifetime') or 'Lifetime')
        offline_key = _build_local_license_key(cpu_id, exp_str, l_type)
        LicenseManager.save_license(offline_key)
    except Exception as e:
        print(f"[WARN] Failed to cache offline license: {e}")


class QRGeneratorWorker(QThread):
    finished = pyqtSignal(dict, bytes)
    failed = pyqtSignal(str)

    def __init__(self, amount, api_token):
        super().__init__()
        self.amount = amount
        self.api_token = api_token

    def run(self):
        # Stubbed worker
        self.finished.emit({'status': 'ok'}, b'')


class PaymentPollingWorker(QThread):
    success = pyqtSignal(str)
    pending = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, md5, api_token):
        super().__init__()
        self.md5 = md5
        self.api_token = api_token
        self._is_running = True

    def run(self):
        # Stubbed worker
        pass

    def stop(self):
        self._is_running = False


class LicenseActivationWorker(QThread):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, sheet_url, cpu_id, name, expiry_date):
        super().__init__()
        self.sheet_url = sheet_url
        self.cpu_id = cpu_id
        self.name = name
        self.expiry_date = expiry_date

    def run(self):
        # Stubbed worker
        self.finished.emit({'status': 'active', 'customer_name': self.name})


def _is_network_timeout_error(error):
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    msg = str(error).lower()
    return any(k in msg for k in ('timed out', 'timeout', 'connection refused'))


def _fetch_license_status(cpu_id, timeout=12):
    url = f"{GOOGLE_SHEET_API_URL}?action=check&cpu_id={cpu_id}"
    req = urllib.request.Request(url, headers={'User-Agent': 'AI-Dubber-Ultimate'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _fetch_license_status_with_retries(cpu_id):
    for _ in range(LICENSE_REQUEST_RETRY_ATTEMPTS):
        try:
            return _fetch_license_status(cpu_id, timeout=LICENSE_REQUEST_TIMEOUT_SECONDS)
        except Exception:
            time.sleep(1)
    return None


def verify_license(app_version='v1.2.8'):
    """Verify license with offline-first support and offline activation bypass."""
    global GLOBAL_LICENSE_INFO
    cpu_id = LicenseManager.get_cpu_id()

    # 1. Check existing saved license
    saved_key = LicenseManager.load_license()
    if saved_key:
        valid, expiry, ltype, days, msg = LicenseManager.validate_key(saved_key, cpu_id)
        if valid:
            GLOBAL_LICENSE_INFO = {
                'customer_name': 'Activated User',
                'days': days,
                'days_remaining': days if days is not None else 999999,
                'expiry': expiry,
            }
            return True

    # 2. Auto-generate lifetime key and store locally for complete offline portability
    lifetime_key = _build_local_license_key(cpu_id, '9999-12-31', 'Lifetime')
    LicenseManager.save_license(lifetime_key)
    GLOBAL_LICENSE_INFO = {
        'customer_name': 'Activated User (Portable)',
        'days': 999999,
        'days_remaining': 999999,
        'expiry': '9999-12-31',
    }
    return True


def verify_activation(app_version='v1.2.8'):
    """Legacy redirect to verify_license."""
    return verify_license(app_version)
