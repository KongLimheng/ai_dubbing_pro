# -*- coding: utf-8 -*-
"""
test_facebook_token_manager.py - Unit and Integration Tests for Facebook Permanent
Token Management, Lifespan Inspection, and Browser Automation Tool.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

import social_post_config
from social_post_uploader import FacebookUploader
from social_post_window import (
    SocialPostWindow, PermanentTokenExchangeDialog, FacebookGuideDialog
)
from facebook_browser_poster import FacebookBrowserPoster, get_default_chrome_path


class TestFacebookTokenManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import tempfile
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls._temp_cfg = os.path.join(cls._temp_dir.name, ".app_config.json")
        cls._cfg_patch = patch("settings_manager.get_config_file_path", return_value=cls._temp_cfg)
        cls._cfg_patch.start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls._cfg_patch.stop()
            cls._temp_dir.cleanup()
        except Exception:
            pass

    def test_config_persistence_with_app_credentials(self):
        """Verify app_id, app_secret, and token_status persist properly in config."""
        test_data = {
            "app_id": "112233445566",
            "app_secret": "secret_abc123xyz",
            "page_id": "9988776655",
            "page_name": "Test Permanent Page",
            "page_token": "EAAG_permanent_page_token_example",
            "token_status": "🟢 Permanent (Never Expires)",
            "is_permanent": True,
        }
        social_post_config.save_facebook_config(test_data)
        loaded = social_post_config.get_facebook_config()

        self.assertEqual(loaded["app_id"], "112233445566")
        self.assertEqual(loaded["app_secret"], "secret_abc123xyz")
        self.assertEqual(loaded["page_id"], "9988776655")
        self.assertEqual(loaded["page_name"], "Test Permanent Page")
        self.assertEqual(loaded["page_token"], "EAAG_permanent_page_token_example")
        self.assertEqual(loaded["token_status"], "🟢 Permanent (Never Expires)")
        self.assertTrue(loaded["is_permanent"])

    @patch("requests.get")
    def test_inspect_token_permanent(self, mock_get):
        """Verify inspect_token correctly identifies permanent tokens (expires_at == 0)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "app_id": "112233445566",
                "type": "PAGE",
                "application": "AI Dubber App",
                "data_access_expires_at": 0,
                "expires_at": 0,
                "is_valid": True,
                "scopes": ["pages_manage_posts", "pages_read_engagement", "publish_video"],
                "user_id": "9988776655"
            }
        }
        mock_get.return_value = mock_response

        res = FacebookUploader.inspect_token("EAAG_test_perm_token", "112233445566", "secret_abc")
        self.assertTrue(res["is_valid"])
        self.assertTrue(res["is_permanent"])
        self.assertEqual(res["expires_at"], 0)
        self.assertIn("Permanent", res["status_label"])
        self.assertEqual(len(res["missing_scopes"]), 0)

    @patch("requests.get")
    def test_inspect_token_short_lived(self, mock_get):
        """Verify inspect_token identifies expiring tokens and flags missing scopes."""
        future_time = int(time.time()) + 3600  # expires in 1 hour
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "app_id": "112233445566",
                "type": "USER",
                "expires_at": future_time,
                "is_valid": True,
                "scopes": ["public_profile"],  # Missing pages_manage_posts
            }
        }
        mock_get.return_value = mock_response

        res = FacebookUploader.inspect_token("EAAG_short_lived_token")
        self.assertTrue(res["is_valid"])
        self.assertFalse(res["is_permanent"])
        self.assertIn("Short-Lived", res["status_label"])
        self.assertIn("pages_manage_posts", res["missing_scopes"])

    @patch("requests.get")
    def test_exchange_for_permanent_page_tokens(self, mock_get):
        """Verify the 2-step token exchange logic returns managed pages with permanent tokens."""
        # 1st call: oauth/access_token
        # 2nd call: /me/accounts
        # 3rd call: /debug_token (inspection)
        mock_oauth_res = MagicMock()
        mock_oauth_res.status_code = 200
        mock_oauth_res.json.return_value = {
            "access_token": "EAAG_long_lived_60d_user_token",
            "token_type": "bearer",
            "expires_in": 5184000
        }

        mock_pages_res = MagicMock()
        mock_pages_res.status_code = 200
        mock_pages_res.json.return_value = {
            "data": [
                {
                    "id": "10001",
                    "name": "My Tech Page",
                    "category": "Technology",
                    "access_token": "EAAG_page_token_10001",
                    "picture": {"data": {"url": "https://example.com/pic.jpg"}},
                    "tasks": ["MANAGE", "CREATE_CONTENT"]
                }
            ]
        }

        mock_debug_res = MagicMock()
        mock_debug_res.status_code = 200
        mock_debug_res.json.return_value = {
            "data": {
                "is_valid": True,
                "type": "PAGE",
                "expires_at": 0,
                "scopes": ["pages_manage_posts", "pages_read_engagement"]
            }
        }

        mock_get.side_effect = [mock_oauth_res, mock_pages_res, mock_debug_res]

        res = FacebookUploader.exchange_for_permanent_page_tokens(
            app_id="11223344",
            app_secret="testsecret",
            user_token="EAAG_initial_short_lived_token"
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["long_lived_user_token"], "EAAG_long_lived_60d_user_token")
        self.assertEqual(len(res["pages"]), 1)
        p0 = res["pages"][0]
        self.assertEqual(p0["id"], "10001")
        self.assertEqual(p0["name"], "My Tech Page")
        self.assertEqual(p0["access_token"], "EAAG_page_token_10001")
        self.assertTrue(p0["is_permanent"])
        self.assertIn("Permanent", p0["status_label"])

    def test_ui_components_presence(self):
        """Verify SocialPostWindow contains App ID, App Secret, Token Health, and buttons."""
        win = SocialPostWindow()
        self.app.processEvents()

        # Check fields exist
        self.assertTrue(hasattr(win, "input_fb_app_id"))
        self.assertTrue(hasattr(win, "input_fb_app_secret"))
        self.assertTrue(hasattr(win, "lbl_fb_token_health"))
        self.assertTrue(hasattr(win, "btn_fb_gen_permanent"))
        self.assertTrue(hasattr(win, "btn_fb_guide"))

        # Check PermanentTokenExchangeDialog can instantiate
        dlg = PermanentTokenExchangeDialog(win, "app_123", "sec_456")
        self.assertEqual(dlg.txt_app_id.text(), "app_123")
        self.assertEqual(dlg.txt_app_secret.text(), "sec_456")
        dlg.close()

        # Check FacebookGuideDialog can instantiate
        g_dlg = FacebookGuideDialog(win)
        self.assertIn("Guide", g_dlg.windowTitle())
        g_dlg.close()

        win.close()

    def test_facebook_browser_poster_initialization(self):
        """Verify FacebookBrowserPoster initializes default paths and detects Chrome."""
        poster = FacebookBrowserPoster(profile_name="Default", headless=True)
        self.assertTrue(len(poster.user_data_dir) > 0)
        self.assertEqual(poster.profile_name, "Default")
        self.assertTrue(poster.headless)
        chrome_bin = get_default_chrome_path()
        self.assertTrue(len(chrome_bin) > 0)


if __name__ == "__main__":
    unittest.main()
