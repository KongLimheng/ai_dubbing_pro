from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from typing import Optional


class TeeTextIO(io.TextIOBase):
    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary

    def write(self, s):
        written = 0
        try:
            written = self._primary.write(s)
        except Exception:
            pass

        try:
            self._secondary.write(s)
        except Exception:
            pass

        return written

    def flush(self):
        for stream in (self._primary, self._secondary):
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return bool(self._primary.isatty())
        except Exception:
            return False


def setup_vscode_debug_log(log_path: Optional[str] = None):
    """
    Mirror stdout/stderr to a log file while keeping terminal output.
    """
    if not log_path:
        log_path = os.path.join(os.getcwd(), "app_debug.log")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    try:
        log_file = open(log_path, "a", encoding="utf-8", errors="replace")
        log_file.write("\n" + "=" * 80 + "\n")
        log_file.write(f"{datetime.now().isoformat(timespec='seconds')} - app start\n")
        log_file.write(f"python_executable: {sys.executable}\n")
        log_file.write(f"python_version: {sys.version}\n")
        log_file.flush()
    except Exception:
        return log_path

    sys.stdout = TeeTextIO(sys.stdout, log_file)
    sys.stderr = TeeTextIO(sys.stderr, log_file)
    return log_path
