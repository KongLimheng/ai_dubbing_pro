# -*- coding: utf-8 -*-
"""
ui_download_dialog.py — Modern interactive download dialog for AI Dubber Ultimate.
Provides on-demand downloading of heavy AI models, runtimes, and dependencies
with real-time progress, speed (MB/s), ETA estimation, and cancellation support.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, List, Optional

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from runtime_paths import resource_path


class RuntimePackageDownloadWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    finished_success = pyqtSignal(list)
    finished_error = pyqtSignal(str)

    def __init__(self, package_keys: list[str], parent=None):
        super().__init__(parent)
        self.package_keys = package_keys
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            from runtime_package_manager import install_runtime_packages

            def progress_hook(percent: int, message: str):
                if self._cancelled:
                    raise RuntimeError("Download cancelled by user.")
                self.progress_changed.emit(percent, message)

            result = install_runtime_packages(
                self.package_keys,
                progress_callback=progress_hook,
                cancel_check=self.is_cancelled,
            )
            self.finished_success.emit(result.get("installed", []))
        except Exception as exc:
            if self._cancelled:
                self.finished_error.emit("Download cancelled.")
            else:
                self.finished_error.emit(str(exc))


class PackageDownloadDialog(QDialog):
    """Modal dialog displaying download & extraction progress for AI packages."""

    def __init__(
        self,
        package_keys: list[str],
        title: str = "Downloading AI Components",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.package_keys = package_keys
        self.worker: Optional[RuntimePackageDownloadWorker] = None
        self.success = False

        self.setWindowTitle(title)
        self.setFixedSize(500, 230)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        icon_path = resource_path("icon.png")
        if not icon_path or not os.path.exists(icon_path):
            icon_path = resource_path("icon.ico")
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Title / Description label
        self.lbl_title = QLabel("Preparing download...")
        font_title = QFont()
        font_title.setPointSize(12)
        font_title.setBold(True)
        self.lbl_title.setFont(font_title)
        self.lbl_title.setStyleSheet("color: #E2E8F0;")
        layout.addWidget(self.lbl_title)

        # Status & ETA text
        self.lbl_status = QLabel("Connecting to server...")
        self.lbl_status.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 6px;
                background-color: #0F172A;
                text-align: center;
                color: #F8FAFC;
                font-weight: bold;
                height: 22px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #8B5CF6);
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Buttons layout
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def start(self):
        from runtime_package_manager import describe_runtime_packages
        names = describe_runtime_packages(self.package_keys)
        self.lbl_title.setText(f"Downloading: {names}")

        self.worker = RuntimePackageDownloadWorker(self.package_keys, self)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.finished_success.connect(self._on_success)
        self.worker.finished_error.connect(self._on_error)
        self.worker.start()
        return self.exec_()

    def _on_progress(self, percent: int, message: str):
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.lbl_status.setText(message)

    def _on_success(self, installed_keys: list):
        self.success = True
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Download and installation complete!")
        self.btn_cancel.setText("Close")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.accept()

    def _on_error(self, error_message: str):
        self.lbl_status.setText(f"Error: {error_message}")
        self.btn_cancel.setText("Close")
        if not (self.worker and self.worker.is_cancelled()):
            QMessageBox.critical(self, "Download Failed", f"Failed to download components:\n\n{error_message}")
        self.reject()

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.lbl_status.setText("Cancelling download...")
            self.worker.cancel()
        else:
            self.reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        super().closeEvent(event)


def prompt_and_download_missing_packages(
    package_keys: list[str],
    parent: Optional[QWidget] = None,
    feature_label: str = "this feature",
) -> bool:
    """
    Check if packages are installed. If missing, show user prompt asking if they want
    to download. If confirmed, show PackageDownloadDialog. Returns True if all ready.
    """
    from runtime_package_manager import describe_runtime_packages, get_missing_runtime_packages, is_runtime_package_ready

    missing = [k for k in package_keys if not is_runtime_package_ready(k)]
    if not missing:
        return True

    names = describe_runtime_packages(missing)
    reply = QMessageBox.question(
        parent,
        "Additional Components Required",
        f"To use {feature_label}, the following AI component(s) need to be downloaded:\n\n"
        f"• {names}\n\n"
        f"Would you like to download them now?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if reply != QMessageBox.Yes:
        return False

    dlg = PackageDownloadDialog(missing, parent=parent)
    dlg.start()
    return dlg.success
