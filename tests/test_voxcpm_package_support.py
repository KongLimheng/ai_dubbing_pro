# -*- coding: utf-8 -*-
"""
Tests for VoxCPM2 package-first enhancement.
Verifies that VoxCPM2 uses the 'voxcpm' Python package instead of requiring
a 'VoxCPM' repository folder.
"""

import os
import sys
import unittest
from unittest import mock

# Ensure src is on sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import voxcpm_support
import settings_manager


class TestVoxCPMPackageSupport(unittest.TestCase):
    """Test suite for voxcpm package integration."""

    def test_voxcpm_package_is_installed(self):
        """Verify that voxcpm package can be imported in the test environment."""
        import voxcpm
        self.assertTrue(hasattr(voxcpm, "VoxCPM"))
        self.assertIn("site-packages", voxcpm.__file__.lower())

    def test_package_detected_without_source_folder(self):
        """Verify get_voxcpm_install_status succeeds when no VoxCPM source folder is present."""
        real_model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "openbmb__VoxCPM2"))

        with mock.patch("settings_manager.get_voxcpm_install_config", return_value={
            "source_dir": "",
            "model_path": real_model_dir,
            "python_path": sys.executable,
        }):
            # Simulate no 'VoxCPM' directory anywhere on disk
            orig_isdir = os.path.isdir
            def mock_isdir(path):
                if any(k in str(path) for k in ("VoxCPM-main", "VoxCPM", "_internal/VoxCPM")):
                    return False
                return orig_isdir(path)

            with mock.patch("os.path.isdir", side_effect=mock_isdir):
                status = voxcpm_support.get_voxcpm_install_status()
                self.assertTrue(status.get("has_package"), "voxcpm package should be detected")
                self.assertTrue(status.get("ready"), f"Engine should be ready without repo folder: {status.get('message')}")
                self.assertEqual(status.get("status"), "ready")
                self.assertIn("v2.", status.get("message"))

    def test_missing_package_reports_voxcpm_package_missing(self):
        """When neither package nor source folder is available, it should report missing voxcpm package."""
        import subprocess

        orig_run = subprocess.run
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 2 and "import voxcpm" in cmd[2]:
                mock_res = mock.MagicMock()
                mock_res.returncode = 1
                mock_res.stdout = ""
                mock_res.stderr = "No module named voxcpm"
                return mock_res
            return orig_run(cmd, *args, **kwargs)

        with mock.patch("settings_manager.get_voxcpm_install_config", return_value={
            "source_dir": "/nonexistent/repo/dir",
            "model_path": "/nonexistent/model",
            "python_path": sys.executable,
        }):
            orig_isdir = os.path.isdir
            def mock_isdir(path):
                if any(k in str(path) for k in ("VoxCPM-main", "VoxCPM", "_internal/VoxCPM")):
                    return False
                return orig_isdir(path)

            with mock.patch("subprocess.run", side_effect=mock_run):
                with mock.patch("os.path.isdir", side_effect=mock_isdir):
                    status = voxcpm_support.get_voxcpm_install_status()
                    self.assertFalse(status.get("has_package"))
                    self.assertFalse(status.get("ready"))
                    self.assertIn("voxcpm package", status.get("message"))

    def test_legacy_source_dir_fallback(self):
        """When package import fails but legacy source_dir exists, it falls back to source_dir."""
        import subprocess

        orig_run = subprocess.run
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 2 and "import voxcpm" in cmd[2]:
                mock_res = mock.MagicMock()
                mock_res.returncode = 1
                mock_res.stdout = ""
                mock_res.stderr = "No module named voxcpm"
                return mock_res
            return orig_run(cmd, *args, **kwargs)

        real_model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "openbmb__VoxCPM2"))
        dummy_source = "/dummy/voxcpm_repo"

        with mock.patch("settings_manager.get_voxcpm_install_config", return_value={
            "source_dir": dummy_source,
            "model_path": real_model_dir,
            "python_path": sys.executable,
        }):
            orig_isdir = os.path.isdir
            def mock_isdir(path):
                if path == os.path.join(dummy_source, "src", "voxcpm"):
                    return True
                return orig_isdir(path)

            with mock.patch("subprocess.run", side_effect=mock_run):
                with mock.patch("os.path.isdir", side_effect=mock_isdir):
                    status = voxcpm_support.get_voxcpm_install_status()
                    self.assertFalse(status.get("has_package"))
                    self.assertTrue(status.get("ready"), "Should be ready via legacy fallback")
                    self.assertEqual(status.get("source_dir"), dummy_source)

    def test_generate_audio_runner_script_structure(self):
        """Verify runner script in generate_voxcpm_audio does not hardcode repo source_dir."""
        import subprocess

        status_mock = {
            "ready": True,
            "source_dir": "",
            "model_path": "/fake/models/openbmb__VoxCPM2",
            "python_path": sys.executable,
            "has_package": True,
        }

        with mock.patch("voxcpm_support.get_voxcpm_install_status", return_value=status_mock):
            with mock.patch("subprocess.Popen") as mock_popen:
                mock_proc = mock.MagicMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = ("SUCCESS\n", "")
                mock_popen.return_value = mock_proc

                # Mock file existence for output
                with mock.patch("os.path.exists", return_value=True):
                    with mock.patch("os.path.getsize", return_value=1024):
                        voxcpm_support.generate_voxcpm_audio(
                            text="Hello test",
                            voice_id="voxcpm2:female",
                            output_path="/tmp/test_output.wav"
                        )

                # Inspect runner command
                called_args, _ = mock_popen.call_args
                cmd = called_args[0]
                self.assertEqual(cmd[0], sys.executable)
                self.assertEqual(cmd[1], "-c")
                runner_script = cmd[2]

                # Ensure from voxcpm import VoxCPM is present
                self.assertIn("from voxcpm import VoxCPM", runner_script)
                # Ensure no unconditional sys.path.insert for an empty source_dir
                self.assertNotIn("sys.path.insert(0, os.path.join('', 'src'))", runner_script)

    def test_cross_platform_path_detection_finds_model_directly(self):
        """Verify _detect_voxcpm_cross_platform finds model folder directly without source repository."""
        import core_app

        dummy_folder = "/path/to/my_voxcpm_models"

        def mock_orig(self, folder):
            # Original detector fails to find source and model
            return "", "", ""

        with mock.patch.object(core_app.DubbingApp, "_detect_voxcpm_install_paths_in_folder", core_app._detect_voxcpm_cross_platform):
            with mock.patch("os.path.isfile", side_effect=lambda p: p == os.path.join(dummy_folder, "config.json")):
                app_dummy = core_app.DubbingApp.__new__(core_app.DubbingApp)
                source, model, py_exe = core_app._detect_voxcpm_cross_platform(app_dummy, dummy_folder)
                self.assertEqual(model, dummy_folder)
                self.assertTrue(py_exe)


if __name__ == "__main__":
    unittest.main()
