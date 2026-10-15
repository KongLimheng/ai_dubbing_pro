# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime_paths import (
    get_app_dir,
    get_user_bin_dir,
    get_user_cache_dir,
    get_user_data_dir,
    get_user_models_dir,
    is_app_dir_writable,
    resolve_binary_path,
)


class TestRuntimePaths(unittest.TestCase):
    def test_user_data_dir_exists_and_writable(self):
        data_dir = get_user_data_dir()
        self.assertTrue(os.path.isdir(data_dir), f"Directory {data_dir} should exist")
        test_file = os.path.join(data_dir, "_test_write.tmp")
        with open(test_file, "w") as f:
            f.write("test")
        self.assertTrue(os.path.isfile(test_file))
        os.remove(test_file)

    def test_user_cache_dir_exists_and_writable(self):
        cache_dir = get_user_cache_dir()
        self.assertTrue(os.path.isdir(cache_dir), f"Cache directory {cache_dir} should exist")
        sub_dir = get_user_cache_dir("test_sub")
        self.assertTrue(os.path.isdir(sub_dir))
        try:
            os.rmdir(sub_dir)
        except Exception:
            pass

    def test_user_models_and_bin_dirs(self):
        models_dir = get_user_models_dir()
        self.assertTrue(os.path.isdir(models_dir))
        self.assertTrue(models_dir.endswith("models"))

        bin_dir = get_user_bin_dir()
        self.assertTrue(os.path.isdir(bin_dir))
        self.assertTrue(bin_dir.endswith("bin"))

    def test_app_dir_writable_check(self):
        res = is_app_dir_writable()
        self.assertIsInstance(res, bool)

    def test_resolve_binary_path(self):
        resolved = resolve_binary_path("python")
        self.assertTrue(resolved)


if __name__ == "__main__":
    unittest.main()
