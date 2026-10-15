# -*- coding: utf-8 -*-
"""
Automated unit tests for the Ubuntu Native Dialog Bridge (Zenity / GTK file chooser).
Verifies that QFileDialog methods are intercepted, arguments/filters converted properly,
and that subprocess executions produce correct return signatures.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure src is on path
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import utils
from utils import _convert_qt_filter_to_zenity, _extract_dialog_args, apply_ubuntu_dialog_patch
from PyQt5.QtWidgets import QApplication, QFileDialog

app = QApplication.instance() or QApplication([])


class TestUbuntuDialogPatch(unittest.TestCase):

    def setUp(self):
        apply_ubuntu_dialog_patch()
        self.assertTrue(getattr(QFileDialog, "_ubuntu_dialog_patched", False))

    def test_filter_converter(self):
        # Multi-filter with wildcards
        f1 = "Video Files (*.mp4 *.mkv *.avi);;All Files (*.*)"
        res1 = _convert_qt_filter_to_zenity(f1)
        self.assertEqual(res1, [
            "--file-filter=Video Files | *.mp4 *.mkv *.avi",
            "--file-filter=All Files | *"
        ])

        # Single filter
        f2 = "SRT Files (*.srt)"
        res2 = _convert_qt_filter_to_zenity(f2)
        self.assertEqual(res2, ["--file-filter=SRT Files | *.srt"])

        # Empty filter
        self.assertEqual(_convert_qt_filter_to_zenity(""), [])

    def test_extract_dialog_args(self):
        file_params = ['parent', 'caption', 'directory', 'filter', 'initialFilter', 'options']
        args = (None, "Open Video", "/home/user/Videos", "Video Files (*.mp4)")
        d = _extract_dialog_args(args, {}, file_params)
        self.assertIsNone(d['parent'])
        self.assertEqual(d['caption'], "Open Video")
        self.assertEqual(d['directory'], "/home/user/Videos")
        self.assertEqual(d['filter'], "Video Files (*.mp4)")

        # Mixed positional and kwargs
        d2 = _extract_dialog_args((None, "Select Title"), {"filter": "SRT (*.srt)"}, file_params)
        self.assertEqual(d2['caption'], "Select Title")
        self.assertEqual(d2['filter'], "SRT (*.srt)")

    @patch("subprocess.run")
    def test_get_open_file_name_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/path/to/movie.mp4\n")

        res = QFileDialog.getOpenFileName(None, "Select Movie", "/home/user", "Video (*.mp4)")
        self.assertEqual(res, ("/path/to/movie.mp4", ""))

        # Verify command arguments passed to zenity
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "zenity")
        self.assertEqual(cmd[1], "--file-selection")
        self.assertIn("--title=Select Movie", cmd)
        self.assertIn("--file-filter=Video | *.mp4", cmd)

    @patch("subprocess.run")
    def test_get_open_file_name_cancel(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        res = QFileDialog.getOpenFileName(None, "Select Movie", "/home/user")
        self.assertEqual(res, ("", ""))

    @patch("subprocess.run")
    def test_get_open_file_names_multiple(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="/path/to/sub1.srt|/path/to/sub2.srt\n"
        )

        res = QFileDialog.getOpenFileNames(None, "Import Subtitles", "/home/user", "SRT (*.srt)")
        self.assertEqual(res, (["/path/to/sub1.srt", "/path/to/sub2.srt"], ""))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("--multiple", cmd)
        self.assertIn("--separator=|", cmd)

    @patch("subprocess.run")
    def test_get_existing_directory_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/home/user/output_dir\n")

        res = QFileDialog.getExistingDirectory(None, "Select Output Directory", "/home/user")
        self.assertEqual(res, "/home/user/output_dir")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("--directory", cmd)
        self.assertIn("--title=Select Output Directory", cmd)

    @patch("subprocess.run")
    def test_get_existing_directory_cancel(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        res = QFileDialog.getExistingDirectory(None, "Select Output Directory")
        self.assertEqual(res, "")

    @patch("subprocess.run")
    def test_get_save_file_name(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/home/user/saved.mp4\n")

        res = QFileDialog.getSaveFileName(None, "Save Video", "/home/user/saved.mp4", "MP4 (*.mp4)")
        self.assertEqual(res, ("/home/user/saved.mp4", ""))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("--save", cmd)
        self.assertIn("--confirm-overwrite", cmd)

    @patch("subprocess.run")
    def test_bytecode_dubbing_app_integration(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/home/user/test_video.mp4\n")

        # Simulate calling QFileDialog as DubbingApp does
        chosen, _ = QFileDialog.getOpenFileName(None, "Video", "", "All Video Files (*.*)")
        self.assertEqual(chosen, "/home/user/test_video.mp4")


if __name__ == "__main__":
    unittest.main()
