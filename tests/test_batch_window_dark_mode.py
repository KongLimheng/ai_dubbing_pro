# -*- coding: utf-8 -*-
"""
Automated unit tests for Batch Video + SRT Mapping window dark mode and fields enhancement.
Verifies that EnhancedBatchSrtMappingDialog renders adhering to the 3-Color Design System,
that input fields and container widgets do not leak system light gray palette,
and that dynamic Dark/Light theme switching updates open dialogs seamlessly.
"""

import os
import sys
import unittest

src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from PyQt5.QtWidgets import QApplication, QFrame
from PyQt5.QtGui import QColor, QPalette

app = QApplication.instance() or QApplication([])

import theme_manager
from ui_theme_tokens import (
    COLOR_CANVAS, COLOR_SURFACE, COLOR_SURFACE_INPUT,
    LIGHT_COLOR_CANVAS, LIGHT_COLOR_SURFACE, LIGHT_COLOR_SURFACE_INPUT
)
import core_app


class TestBatchWindowDarkMode(unittest.TestCase):

    def setUp(self):
        theme_manager.apply_theme("dark", target=app)
        self.mock_videos = ["/tmp/mock_ep01.mp4", "/tmp/mock_ep02.mp4"]
        self.dlg = core_app.EnhancedBatchSrtMappingDialog(self.mock_videos)

    def tearDown(self):
        if hasattr(self, 'dlg') and self.dlg:
            self.dlg.close()
            self.dlg.deleteLater()
        theme_manager.apply_theme("dark", target=app)

    def test_dark_mode_initialization(self):
        """Verify dialog initializes with dark canvas and content widget is properly configured."""
        self.assertFalse(self.dlg._content_widget.autoFillBackground(),
                         "Content widget must not have autoFillBackground enabled to prevent system palette leakage.")
        self.assertEqual(self.dlg._content_widget.objectName(), "BatchContentWidget")
        
        # Verify stylesheet contains dark tokens
        ss = self.dlg.styleSheet()
        self.assertIn(COLOR_CANVAS, ss, "Dialog stylesheet must include dark canvas color (#0F141C).")
        self.assertIn(COLOR_SURFACE, ss, "Dialog stylesheet must include dark surface color (#161D28).")
        self.assertIn(COLOR_SURFACE_INPUT, ss, "Dialog stylesheet must include dark input surface color (#0D121B).")
        
        # Verify palette window color matches dark canvas
        self.assertEqual(self.dlg.palette().window().color().name().lower(), COLOR_CANVAS.lower())

    def test_table_and_cells_dark_mode(self):
        """Verify table rows, cell widgets, and transparent containers."""
        self.assertEqual(self.dlg.table.rowCount(), 2)

        for r in range(self.dlg.table.rowCount()):
            # Col 3: Voice ComboBox
            voice_combo = self.dlg.table.cellWidget(r, 3)
            self.assertIsNotNone(voice_combo)
            self.assertEqual(voice_combo.metaObject().className(), "QComboBox")

            # Col 4: Pitch LineEdit
            pitch_edit = self.dlg.table.cellWidget(r, 4)
            self.assertIsNotNone(pitch_edit)
            self.assertEqual(pitch_edit.metaObject().className(), "QLineEdit")

            # Col 5: Speed LineEdit
            speed_edit = self.dlg.table.cellWidget(r, 5)
            self.assertIsNotNone(speed_edit)
            self.assertEqual(speed_edit.metaObject().className(), "QLineEdit")

            # Col 6: Echo container
            echo_w = self.dlg.table.cellWidget(r, 6)
            self.assertIsNotNone(echo_w)
            self.assertIn("transparent", echo_w.styleSheet().lower())

            # Col 7: Actions container
            actions_w = self.dlg.table.cellWidget(r, 7)
            self.assertIsNotNone(actions_w)
            self.assertIn("transparent", actions_w.styleSheet().lower())

            # Verify action buttons exist in container
            buttons = [c for c in actions_w.children() if hasattr(c, 'objectName')]
            btn_names = [b.objectName() for b in buttons]
            self.assertIn("BatchRowBrowseButton", btn_names)
            self.assertIn("BatchRowEditButton", btn_names)
            self.assertIn("BatchRowGenderButton", btn_names)
            self.assertIn("BatchRowClearButton", btn_names)
            self.assertIn("dangerBtn", btn_names)

    def test_summary_badges_theme_formatting(self):
        """Verify summary badges format with high contrast dark pills in dark mode and light pills in light mode."""
        summary_text_dark = self.dlg.summary_label.text()
        self.assertIn("#143322", summary_text_dark, "Dark mode Mapped pill must use #143322 background.")
        self.assertIn("#4ADE80", summary_text_dark, "Dark mode Mapped pill must use #4ADE80 text.")

        # Switch to light mode
        theme_manager.apply_theme("light")
        summary_text_light = self.dlg.summary_label.text()
        self.assertIn("#EAFBF3", summary_text_light, "Light mode Mapped pill must use #EAFBF3 background.")
        self.assertIn("#16A34A", summary_text_light, "Light mode Mapped pill must use #16A34A text.")

    def test_realtime_theme_switching(self):
        """Verify dynamic Dark -> Light -> Dark switching on active dialog."""
        # Initial: dark mode
        self.assertIn(COLOR_CANVAS, self.dlg.styleSheet())
        self.assertEqual(self.dlg.palette().window().color().name().lower(), COLOR_CANVAS.lower())

        # Switch to light mode
        theme_manager.apply_theme("light")
        self.assertIn(LIGHT_COLOR_CANVAS, self.dlg.styleSheet())
        self.assertEqual(self.dlg.palette().window().color().name().lower(), LIGHT_COLOR_CANVAS.lower())

        # Switch back to dark mode
        theme_manager.apply_theme("dark")
        self.assertIn(COLOR_CANVAS, self.dlg.styleSheet())
        self.assertEqual(self.dlg.palette().window().color().name().lower(), COLOR_CANVAS.lower())

    def test_vocal_removal_card_styling(self):
        """Verify Vocal Removal group card and spinboxes are properly accessible and styled."""
        vocal_frame = self.dlg.findChild(QFrame, "BatchVocalRemovalFrame")
        self.assertIsNotNone(vocal_frame, "BatchVocalRemovalFrame must exist.")
        self.assertTrue(hasattr(self.dlg, "chk_batch_demucs"))
        self.assertTrue(hasattr(self.dlg, "spin_batch_bg_mix"))
        self.assertTrue(hasattr(self.dlg, "spin_batch_ai_mix"))
        self.assertTrue(hasattr(self.dlg, "chk_batch_auto_sync"))


if __name__ == "__main__":
    unittest.main()
