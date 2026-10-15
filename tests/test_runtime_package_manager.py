# -*- coding: utf-8 -*-
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime_package_manager import (
    _format_size,
    _format_time,
    _safe_extract_zip,
    get_missing_runtime_packages,
    get_runtime_package_entry,
    load_runtime_package_manifest,
)


class TestRuntimePackageManager(unittest.TestCase):
    def test_load_manifest(self):
        manifest = load_runtime_package_manifest()
        self.assertIn("packages", manifest)
        packages = manifest["packages"]
        self.assertIn("funasr_models", packages)
        self.assertIn("demucs_models", packages)
        self.assertIn("ffmpeg_binaries", packages)

    def test_get_package_entry(self):
        entry = get_runtime_package_entry("funasr_models")
        self.assertEqual(entry.get("key"), "funasr_models")
        self.assertTrue(entry.get("label"))
        self.assertGreater(entry.get("approx_size_mb", 0), 0)

    def test_format_helpers(self):
        self.assertEqual(_format_size(500), "0.5 KB")
        self.assertEqual(_format_size(1024 * 1024 * 50), "50.0 MB")
        self.assertEqual(_format_size(1024 * 1024 * 1024 * 2), "2.00 GB")

        self.assertEqual(_format_time(65), "01:05")
        self.assertEqual(_format_time(3665), "01:01:05")

    def test_safe_extract_zip_prevents_path_traversal(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", "malicious content")
        buf.seek(0)

        test_zip_path = os.path.join(os.path.dirname(__file__), "_test_evil.zip")
        with open(test_zip_path, "wb") as f:
            f.write(buf.getvalue())

        dest_dir = os.path.join(os.path.dirname(__file__), "_test_extract_target")
        try:
            with self.assertRaises(RuntimeError):
                _safe_extract_zip(test_zip_path, dest_dir)
        finally:
            if os.path.isfile(test_zip_path):
                os.remove(test_zip_path)
            if os.path.isdir(dest_dir):
                import shutil
                shutil.rmtree(dest_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
