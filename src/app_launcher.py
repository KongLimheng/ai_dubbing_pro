# -*- coding: utf-8 -*-
"""
Application startup, splash screen, and exception handling launcher.
Ported from portable decompiled bytecode with 100% functional fidelity and cross-platform enhancements.
"""

import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime

from PyQt5.QtCore import QThread, QTimer, Qt
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QProgressBar, QSplashScreen

import license_manager
from runtime_paths import resource_path


def _append_error_log(title, details):
    try:
        from runtime_paths import get_app_dir
        log_path = os.path.join(get_app_dir(), 'app_crash.log')
        with open(log_path, 'a', encoding='utf-8', errors='replace') as log_file:
            log_file.write('\n' + '=' * 80 + '\n')
            log_file.write(
                f"{datetime.now().isoformat(timespec='seconds')} - {title}\n\n")
            log_file.write(details.rstrip() + '\n')
        return log_path
    except Exception:
        return ''


def launch_app():
    try:
        from utils import apply_khmer_font_patch, apply_ubuntu_dialog_patch
        apply_khmer_font_patch()
        apply_ubuntu_dialog_patch()
    except Exception:
        pass

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    try:
        app = QApplication(sys.argv)
    except KeyboardInterrupt:
        print('Startup cancelled.')
        return

    app.setApplicationName('AI Dubber Ultimate')
    app.setDesktopFileName('ai-dubber-ultimate')
    global_icon_path = resource_path('icon.png')
    if not os.path.exists(global_icon_path):
        global_icon_path = resource_path('icon.ico')
    if os.path.exists(global_icon_path):
        app.setWindowIcon(QIcon(global_icon_path))

    os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
    os.environ.setdefault('OMP_NUM_THREADS', '1')

    try:
        torch_lib = os.path.join(
            sys.prefix, 'Lib', 'site-packages', 'torch', 'lib')
        if os.path.isdir(torch_lib) and hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(torch_lib)
    except Exception:
        pass

    try:
        import torch  # noqa: F401
    except Exception:
        pass

    from core_app import APP_VERSION, DubbingApp

    def handle_unexpected_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            app.quit()
            return
        details = ''.join(traceback.format_exception(
            exc_type, exc_value, exc_traceback)).strip()
        summary = str(exc_value).strip() or exc_type.__name__
        log_path = _append_error_log('Unhandled exception', details)

        if QThread.currentThread() != app.thread():
            print(details, file=sys.stderr)
            return

        from PyQt5.QtWidgets import QMessageBox
        message = f"{exc_type.__name__}: {summary}" if summary != exc_type.__name__ else summary
        if log_path:
            message += f"\n\nSaved details to:\n{log_path}"
        try:
            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle('Unexpected Error')
            box.setText(message)
            box.setDetailedText(details)
            box.exec_()
        except Exception:
            print(details, file=sys.stderr)

    sys.excepthook = handle_unexpected_exception

    def handle_thread_exception(args):
        if args.exc_type is SystemExit:
            return
        details = ''.join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback)).strip()
        thread_name = getattr(args.thread, 'name', 'unknown')
        _append_error_log(f"Thread exception: {thread_name}", details)
        print(details, file=sys.stderr)

    threading.excepthook = handle_thread_exception

    if hasattr(sys, 'unraisablehook'):
        def handle_unraisable(unraisable):
            exc_type = type(unraisable.exc_value)
            details = ''.join(traceback.format_exception(
                exc_type, unraisable.exc_value, unraisable.exc_traceback)).strip()
            if unraisable.object is not None:
                details += f"\n\nObject: {repr(unraisable.object)}"
            _append_error_log('Unraisable exception', details)
            print(details, file=sys.stderr)

        sys.unraisablehook = handle_unraisable

    def handle_sigint():
        app.quit()

    signal.signal(signal.SIGINT, lambda *args: handle_sigint())
    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(200)

    default_font = QFont('Segoe UI', 10)
    default_font.setStyleHint(QFont.SansSerif)
    if hasattr(default_font, 'setFamilies'):
        default_font.setFamilies(['Segoe UI', 'Noto Color Emoji', 'DejaVu Sans',
                                 'Khmer OS System', 'Noto Sans Khmer', 'sans-serif'])
    app.setFont(default_font)

    try:
        from theme_manager import apply_theme, get_theme_mode
        apply_theme(get_theme_mode(), app)
    except Exception:
        pass

    if not license_manager.verify_activation(APP_VERSION):
        print('Activation failed. Exiting...')
        sys.exit(0)

    class CustomSplashScreen(QSplashScreen):
        def __init__(self, pixmap):
            super().__init__(pixmap, Qt.WindowStaysOnTopHint)
            self.progress_bar = QProgressBar(self)
            self.progress_bar.setStyleSheet('''
                QProgressBar {
                    border: 2px solid rgba(255, 255, 255, 100);
                    border-radius: 10px;
                    text-align: center;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    background-color: rgba(0, 0, 0, 100);
                }
                QProgressBar::chunk {
                    background-color: qlineargradient(x1: 0, y1: 0.5, x2: 1, y2: 0.5, stop: 0 #667EEA, stop: 1 #E74C3C);
                    border-radius: 8px;
                }
            ''')
            self.progress_bar.setFormat('%p% - Loading Modules...')
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(100)
            self.progress_bar.setTextVisible(False)

            self.progress_label = QLabel(self)
            self.progress_label.setAlignment(Qt.AlignCenter)
            self.progress_label.setStyleSheet('''
                QLabel {
                    color: white;
                    background-color: transparent;
                    font-family: Consolas, 'Courier New', monospace;
                    font-size: 14px;
                    font-weight: bold;
                }
            ''')
            self._set_progress_text(0, 'Loading Modules', 3)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self.progress_bar.setGeometry(
                30, self.height() - 50, self.width() - 60, 25)
            self.progress_label.setGeometry(self.progress_bar.geometry())

        def _set_progress_text(self, value, text, dot_count=0):
            clean_text = str(text).rstrip('.')
            dots = ('.' * max(0, min(3, dot_count))).ljust(3)
            self.progress_label.setText(
                f"{int(value):3d}%  {clean_text}{dots}")

        def update_progress(self, value, text):
            self.progress_bar.setValue(value)
            self._set_progress_text(
                value, text, 3 if text.endswith('...') else 0)
            app.processEvents()

        def animate_progress(self, start, end, text, duration=0.35):
            steps = max(end - start, 1)
            delay = duration / steps
            for index, value in enumerate(range(start, end + 1)):
                dot_count = (index % 3) + 1
                self.progress_bar.setValue(value)
                self._set_progress_text(value, text, dot_count)
                app.processEvents()
                time.sleep(delay)

    splash = None
    splash_started_at = None
    min_splash_seconds = 1.4
    splash_icon_path = resource_path('icon.png')
    if not os.path.exists(splash_icon_path):
        splash_icon_path = resource_path('icon.ico')

    if os.path.exists(splash_icon_path):
        splash_pix = QPixmap(splash_icon_path)
        if splash_pix.width() > 600 or splash_pix.height() > 600:
            splash_pix = splash_pix.scaled(
                600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        splash = CustomSplashScreen(splash_pix)
        splash.setMask(splash_pix.mask())
        splash.show()
        splash_started_at = time.monotonic()
        app.processEvents()
        splash.animate_progress(0, 18, 'Initializing Qt Framework', 0.25)
        splash.animate_progress(18, 42, 'Checking UI Components', 0.3)
        splash.animate_progress(42, 68, 'Loading Modules', 0.35)
        splash.animate_progress(68, 88, 'Preparing Main Window', 0.3)
        splash.update_progress(90, 'Starting AI Dubber...')

    window = DubbingApp()
    if os.path.exists(global_icon_path):
        window.setWindowIcon(QIcon(global_icon_path))

    if splash:
        splash.animate_progress(90, 100, 'Ready', 0.2)
        if splash_started_at is not None:
            while time.monotonic() - splash_started_at < min_splash_seconds:
                app.processEvents()
                time.sleep(0.03)
        splash.close()

    window.showMaximized()

    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        app.quit()
        sys.exit(130)
