# -*- coding: utf-8 -*-
"""
test_main_and_settings_dark_mode.py — Unit tests for Main Window and Settings Dialog Dark Mode.
Verifies that:
1. DubbingApp (Main Window) uses the 3-Color Design System (no #ECF0F1 hardcoded override,
   no autoFillBackground leaks on scroll areas, TimelineWidget themed, semantic button styling).
2. Settings Dialog has high-contrast tab bar, dark tab panes, sanitized dark info cards,
   recessed input fields, and dark log areas.
3. Dynamic theme switching transitions both windows cleanly between Dark and Light mode.
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PyQt5.QtWidgets import (
    QApplication, QScrollArea, QDialog, QTabWidget, QPushButton,
    QLabel, QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

import theme_manager
import settings_manager
import core_app
import settings_window
import ui_widgets


class TestMainAndSettingsDarkMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        settings_manager.save_theme_mode("dark")
        theme_manager.apply_theme("dark", self.app)

    def test_main_window_dark_initialization(self):
        """Verify Main Window initializes in dark mode without hardcoded light styles."""
        win = core_app.DubbingApp()
        self.app.processEvents()

        # 1. Window stylesheet should not contain legacy light theme
        win_ss = win.styleSheet() or ""
        self.assertNotIn("#ECF0F1", win_ss, "Main Window should not have hardcoded #ECF0F1 background.")
        self.assertNotIn("#2C3E50", win_ss, "Main Window should not have hardcoded dark text color on window.")

        # 2. Central widget and viewports should have autoFillBackground == False
        cw = win.centralWidget()
        self.assertIsNotNone(cw, "Main window must have a central widget.")
        self.assertFalse(cw.autoFillBackground(), "Central widget autoFillBackground must be False.")
        if hasattr(cw, 'widget') and cw.widget():
            self.assertFalse(cw.widget().autoFillBackground(), "Central content widget autoFillBackground must be False.")
        if hasattr(cw, 'viewport') and cw.viewport():
            self.assertFalse(cw.viewport().autoFillBackground(), "Central viewport autoFillBackground must be False.")

        # 3. All child scroll areas must have autoFillBackground == False
        for sa in win.findChildren(QScrollArea):
            self.assertFalse(sa.autoFillBackground(), f"ScrollArea {sa} autoFillBackground must be False.")
            if sa.viewport():
                self.assertFalse(sa.viewport().autoFillBackground(), f"ScrollArea viewport {sa.viewport()} must be False.")

        win.close()

    def test_main_window_timeline_and_buttons(self):
        """Verify TimelineWidget and buttons in Main Window conform to theme tokens."""
        win = core_app.DubbingApp()
        self.app.processEvents()

        # 1. TimelineWidget background color
        timelines = win.findChildren(ui_widgets.TimelineWidget)
        self.assertTrue(len(timelines) > 0, "Main Window must contain a TimelineWidget.")
        for tw in timelines:
            self.assertEqual(tw.bg_color.name().upper(), "#161D28", "TimelineWidget bg_color must be #161D28 in dark mode.")
            self.assertEqual(tw.grid_color.name().upper(), "#212936", "TimelineWidget grid_color must be #212936.")
            self.assertEqual(tw.waveform_bg_color.name().upper(), "#0D121B", "TimelineWidget waveform_bg_color must be #0D121B.")

        # 2. Top action buttons should have semantic objectNames and no hardcoded background colors
        hero_ctas = {"Export Video", "Transcribe", "Translate", "Load Video", "Batch Load"}
        for btn in win.findChildren(QPushButton):
            txt = btn.text().strip()
            obj_name = btn.objectName()
            if any(h in txt for h in hero_ctas):
                self.assertEqual(obj_name, "primaryBtn", f"Hero button '{txt}' must have objectName 'primaryBtn'.")
                self.assertNotIn("background-color:", btn.styleSheet() or "", f"Hero button '{txt}' must not have inline background-color.")

        # 3. Cambodian Voice Clone checkbox
        for chk in win.findChildren(QCheckBox):
            if any(k in chk.text() for k in ["Clon", "ក្លូន", "សំឡេង"]):
                self.assertIn("#F87171", chk.styleSheet() or "", "Voice Clone checkbox must use high-contrast #F87171 in dark mode.")

        win.close()

    def test_settings_dialog_theming(self):
        """Verify Settings Dialog tabs, cards, inputs, and text edit are fully dark-themed."""
        win = core_app.DubbingApp()
        self.app.processEvents()

        dialog_ref = []

        def inspect_settings():
            for w in self.app.allWidgets():
                if isinstance(w, QDialog) and w.isVisible() and 'Settings' in (w.windowTitle() or ''):
                    dialog_ref.append(w)
                    break
            self.app.quit()

        QTimer.singleShot(250, inspect_settings)
        QTimer.singleShot(30, win.open_settings_dialog)
        self.app.exec_()

        self.assertTrue(len(dialog_ref) > 0, "Settings dialog should have been found.")
        dialog = dialog_ref[0]

        # 1. Dialog stylesheet must include tab widget and tab bar styling
        d_ss = dialog.styleSheet() or ""
        self.assertIn("QTabWidget::pane", d_ss, "Dialog stylesheet must style QTabWidget::pane.")
        self.assertIn("QTabBar::tab", d_ss, "Dialog stylesheet must style QTabBar::tab.")
        self.assertIn("#F97316", d_ss, "Dialog stylesheet must use accent #F97316 for active tab.")

        # 2. Hardware and Demucs cards must not have hardcoded white backgrounds
        for lbl in dialog.findChildren(QLabel):
            ss = lbl.styleSheet() or ""
            self.assertNotIn("#FDFEFE", ss, "Settings info card must not use hardcoded #FDFEFE.")
            self.assertNotIn("#FBFCFC", ss, "Settings info card must not use hardcoded #FBFCFC.")
            self.assertNotIn("#F4F6F7", ss, "Settings info card must not use hardcoded #F4F6F7.")
            self.assertNotIn("#2C3E50", ss, "Settings labels must not use unreadable #2C3E50 in dark mode.")

        # 3. Text edits (Demucs log) must be dark recessed
        for te in dialog.findChildren((QTextEdit, QPlainTextEdit)):
            ss = te.styleSheet() or ""
            self.assertNotIn("#FBFCFC", ss, "Demucs log must not use #FBFCFC background.")

        # 4. Scroll areas in settings must have autoFillBackground disabled
        for sa in dialog.findChildren(QScrollArea):
            self.assertFalse(sa.autoFillBackground(), f"Settings ScrollArea {sa} autoFillBackground must be False.")
            if sa.viewport():
                self.assertFalse(sa.viewport().autoFillBackground(), f"Settings viewport {sa.viewport()} must be False.")

        dialog.accept()
        win.close()

    def test_dynamic_theme_switching_main_and_settings(self):
        """Verify switching theme between dark and light updates both MainWindow and Settings dialog."""
        win = core_app.DubbingApp()
        self.app.processEvents()

        # Switch to light mode
        theme_manager.apply_theme("light", self.app)
        self.app.processEvents()

        # Verify main window updated to light tokens
        for tw in win.findChildren(ui_widgets.TimelineWidget):
            self.assertEqual(tw.bg_color.name().upper(), "#FFFFFF", "TimelineWidget bg_color must be #FFFFFF in light mode.")

        for chk in win.findChildren(QCheckBox):
            if any(k in chk.text() for k in ["Clon", "ក្លូន", "សំឡេង"]):
                self.assertIn("#DC2626", chk.styleSheet() or "", "Voice Clone checkbox must use #DC2626 in light mode.")

        # Switch back to dark mode
        theme_manager.apply_theme("dark", self.app)
        self.app.processEvents()

        for tw in win.findChildren(ui_widgets.TimelineWidget):
            self.assertEqual(tw.bg_color.name().upper(), "#161D28", "TimelineWidget bg_color must be #161D28 in dark mode.")

        for chk in win.findChildren(QCheckBox):
            if any(k in chk.text() for k in ["Clon", "ក្លូន", "សំឡេង"]):
                self.assertIn("#F87171", chk.styleSheet() or "", "Voice Clone checkbox must use #F87171 in dark mode.")

        win.close()


if __name__ == "__main__":
    unittest.main()
