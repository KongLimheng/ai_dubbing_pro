# -*- coding: utf-8 -*-
"""
Theme manager module for AI Dubber Ultimate.
Provides comprehensive Dark Mode and Light Mode stylesheets adhering to the
60-30-10 Design System, real-time theme toggling, and persistent theme configuration.
"""

import os
import sys

from ui_theme_tokens import get_modern_stylesheet

DARK_STYLESHEET = get_modern_stylesheet("dark")
LIGHT_STYLESHEET = get_modern_stylesheet("light")


def get_theme_mode():
    """Gets the saved theme mode ('dark' or 'light'). Defaults to 'dark'."""
    try:
        from settings_manager import get_theme_mode as _get_mode
        return _get_mode()
    except Exception:
        return "dark"


def apply_theme(theme_mode, target=None):
    """
    Applies the specified theme ('dark' or 'light') to target (or QApplication).
    Saves the user preference in settings.
    """
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
    except Exception:
        app = None

    is_dark = str(theme_mode).strip().lower() == "dark"
    # Dynamically evaluate stylesheet so resource paths and tokens remain current
    stylesheet = DARK_STYLESHEET if is_dark else LIGHT_STYLESHEET

    if app and hasattr(app, "setStyleSheet"):
        app.setStyleSheet(stylesheet)

    if target and hasattr(target, "setStyleSheet") and target is not app:
        target.setStyleSheet(stylesheet)

    # Save to configuration first so get_theme_mode() returns the new mode immediately
    try:
        from settings_manager import save_theme_mode
        save_theme_mode("dark" if is_dark else "light")
    except Exception:
        pass

    # Notify active top-level windows/dialogs (such as EnhancedBatchSrtMappingDialog)
    if app:
        try:
            for top_w in app.topLevelWidgets():
                if hasattr(top_w, "apply_dialog_theme") and callable(top_w.apply_dialog_theme):
                    try:
                        top_w.apply_dialog_theme(theme_mode)
                    except Exception:
                        pass
        except Exception:
            pass


def toggle_theme(target=None):
    """
    Toggles between dark and light themes and returns the new theme mode ('dark' or 'light').
    """
    current = get_theme_mode()
    new_mode = "light" if current == "dark" else "dark"
    apply_theme(new_mode, target=target)
    return new_mode
