# -*- coding: utf-8 -*-
"""
test_browser_automation_ui.py - Tests for Facebook Browser Automation UI integration,
Chrome profile scanning, mode switching, and upload worker routing.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PyQt5.QtWidgets import QApplication

import social_post_config
from social_post_uploader import SocialUploadWorker, FacebookUploader
from social_post_window import SocialPostWindow
from facebook_browser_poster import list_chrome_profiles, is_playwright_ready, FacebookBrowserPoster


class TestBrowserAutomationUI(unittest.TestCase):
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

    def test_chrome_profile_discovery(self):
        """Verify list_chrome_profiles returns valid profiles on the system."""
        profiles = list_chrome_profiles()
        self.assertIsInstance(profiles, list)
        self.assertTrue(len(profiles) > 0)
        p0 = profiles[0]
        self.assertIn("key", p0)
        self.assertIn("name", p0)
        self.assertIn("path", p0)

    def test_config_persistence_browser_mode(self):
        """Verify browser automation fields persist in configuration."""
        data = {
            "post_method": "browser",
            "browser_profile": "Profile 2",
            "browser_headless": True,
        }
        social_post_config.save_facebook_config(data)
        loaded = social_post_config.get_facebook_config()

        self.assertEqual(loaded["post_method"], "browser")
        self.assertEqual(loaded["browser_profile"], "Profile 2")
        self.assertTrue(loaded["browser_headless"])

    @patch("facebook_browser_poster.FacebookBrowserPoster.post")
    def test_worker_routes_to_browser_poster(self, mock_browser_post):
        """Verify worker calls FacebookBrowserPoster when post_method is 'browser'."""
        mock_browser_post.return_value = {
            "success": True,
            "method": "browser_automation",
            "video_path": "/fake/video.mp4",
        }

        creds = {
            "facebook": {
                "post_method": "browser",
                "browser_profile": "Default",
                "browser_headless": True,
                "page_id": "12345",
            }
        }
        meta = {
            "title": "Automated Title",
            "description": "Automated Description",
        }

        worker = SocialUploadWorker(
            video_path="/fake/video.mp4",
            platforms=["facebook"],
            metadata=meta,
            credentials=creds,
        )

        res = worker._run_facebook(video_path="/fake/video.mp4", meta=meta)
        self.assertTrue(res["success"])
        self.assertEqual(res["method"], "browser_automation")
        mock_browser_post.assert_called_once()
        call_kwargs = mock_browser_post.call_args[1]
        self.assertEqual(call_kwargs["video_path"], "/fake/video.mp4")
        self.assertEqual(call_kwargs["title"], "Automated Title")
        self.assertEqual(call_kwargs["description"], "Automated Description")

    @patch("social_post_uploader.FacebookUploader.upload_video")
    def test_worker_routes_to_graph_api(self, mock_api_upload):
        """Verify worker calls FacebookUploader.upload_video when post_method is 'graph_api'."""
        mock_api_upload.return_value = {
            "success": True,
            "platform": "facebook",
            "video_id": "999888",
        }

        creds = {
            "facebook": {
                "post_method": "graph_api",
                "page_id": "page_123",
                "page_token": "token_abc",
            }
        }
        meta = {
            "title": "API Title",
            "description": "API Description",
        }

        worker = SocialUploadWorker(
            video_path="/fake/video.mp4",
            platforms=["facebook"],
            metadata=meta,
            credentials=creds,
        )

        res = worker._run_facebook(video_path="/fake/video.mp4", meta=meta)
        self.assertTrue(res["success"])
        mock_api_upload.assert_called_once()

    def test_ui_mode_toggle_and_widgets(self):
        """Verify SocialPostWindow contains mode toggle radios and switches panels properly."""
        win = SocialPostWindow()
        win.show()
        self.app.processEvents()

        # Check UI widgets exist
        self.assertTrue(hasattr(win, "rb_fb_mode_api"))
        self.assertTrue(hasattr(win, "rb_fb_mode_browser"))
        self.assertTrue(hasattr(win, "panel_fb_api"))
        self.assertTrue(hasattr(win, "panel_fb_browser"))
        self.assertTrue(hasattr(win, "cmb_fb_browser_profile"))
        self.assertTrue(hasattr(win, "btn_refresh_chrome_profiles"))
        self.assertTrue(hasattr(win, "btn_fb_launch_chrome"))
        self.assertTrue(hasattr(win, "chk_fb_browser_headless"))
        self.assertTrue(hasattr(win, "lbl_fb_engine_status"))
        self.assertTrue(hasattr(win, "btn_fb_install_engine"))
        self.assertTrue(hasattr(win, "lbl_fb_mode_active"))

        # Test switching to Browser Mode
        win.rb_fb_mode_browser.setChecked(True)
        self.app.processEvents()
        self.assertFalse(win.panel_fb_browser.isHidden())
        self.assertTrue(win.panel_fb_api.isHidden())
        self.assertIn("Browser", win.lbl_fb_mode_active.text())

        # Test switching back to API Mode
        win.rb_fb_mode_api.setChecked(True)
        self.app.processEvents()
        self.assertFalse(win.panel_fb_api.isHidden())
        self.assertTrue(win.panel_fb_browser.isHidden())
        self.assertIn("Graph API", win.lbl_fb_mode_active.text())

        win.close()

    @patch("social_post_window.install_playwright")
    @patch("social_post_window.is_playwright_ready")
    @patch("social_post_window.QMessageBox.information")
    def test_install_playwright_engine_no_name_error(self, mock_msg, mock_ready, mock_install):
        """Verify _install_playwright_engine finishes without throwing NameError: name 'yt' is not defined."""
        mock_install.return_value = True
        mock_ready.return_value = True

        win = SocialPostWindow()
        win.show()
        self.app.processEvents()

        # Trigger install engine action
        try:
            win._install_playwright_engine()
        except NameError as e:
            self.fail(f"_install_playwright_engine raised unexpected NameError: {e}")

        self.assertIn("Ready", win.lbl_fb_engine_status.text())
        win.close()

    def test_update_badges_all_platforms(self):
        """Verify _update_badges updates Facebook, YouTube, and TikTok badges without error."""
        win = SocialPostWindow()
        self.app.processEvents()

        win._update_badges()
        self.assertTrue(hasattr(win, "badge_fb"))
        self.assertTrue(hasattr(win, "badge_yt"))
        self.assertTrue(hasattr(win, "badge_tt"))
        self.assertTrue(len(win.badge_fb.text()) > 0)
        self.assertTrue(len(win.badge_yt.text()) > 0)
        self.assertTrue(len(win.badge_tt.text()) > 0)

        win.close()

    def test_get_profile_storage_dir_isolation(self):
        """Verify get_profile_storage_dir uses isolated ai_dubber_profiles directory."""
        poster = FacebookBrowserPoster(profile_name="Profile 2")
        p_dir = poster.get_profile_storage_dir()
        self.assertIn("ai_dubber_profiles", p_dir)
        self.assertTrue(p_dir.endswith("Profile 2"))
        self.assertTrue(os.path.isdir(p_dir))
        state_path = poster.get_storage_state_path()
        self.assertTrue(state_path.endswith("facebook_storage_state.json"))

    def test_check_session_status_empty_and_valid(self):
        """Verify check_session_status detects missing session vs logged-in cookies."""
        import tempfile
        import json

        with tempfile.TemporaryDirectory() as tmp_dir:
            poster = FacebookBrowserPoster(user_data_dir=tmp_dir, profile_name="TestProf")
            # 1. Empty state
            status1 = poster.check_session_status()
            self.assertFalse(status1["logged_in"])
            self.assertEqual(status1["cookies_count"], 0)

            # 2. Write mock facebook_storage_state.json
            state_file = poster.get_storage_state_path()
            mock_data = {
                "cookies": [
                    {"name": "c_user", "value": "100012345678", "domain": ".facebook.com"},
                    {"name": "xs", "value": "2:token:hash", "domain": ".facebook.com"},
                    {"name": "datr", "value": "datr_val", "domain": ".facebook.com"},
                ]
            }
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(mock_data, f)

            status2 = poster.check_session_status()
            self.assertTrue(status2["logged_in"])
            self.assertEqual(status2["user_id"], "100012345678")
            self.assertEqual(status2["cookies_count"], 3)
            self.assertIn("100012345678", status2["status_text"])

    def test_ui_profile_change_autosaves(self):
        """Verify changing Chrome profile in UI automatically saves to config."""
        win = SocialPostWindow()
        self.app.processEvents()

        # Add mock profile and select it
        win.cmb_fb_browser_profile.addItem("Mock Profile 99", "Profile 99")
        idx = win.cmb_fb_browser_profile.findData("Profile 99")
        win.cmb_fb_browser_profile.setCurrentIndex(idx)
        self.app.processEvents()

        loaded = social_post_config.get_facebook_config()
        self.assertEqual(loaded["browser_profile"], "Profile 99")
        win.close()

    @patch("facebook_browser_poster.FacebookBrowserPoster.post")
    def test_worker_auto_fallbacks_to_default_profile(self, mock_post):
        """Verify worker automatically falls back to 'Default' if requested profile lacks cookies but Default is active."""
        def fake_status(self_poster):
            if self_poster.profile_name == "Default":
                return {"logged_in": True, "user_id": "100008285234936"}
            return {"logged_in": False, "user_id": ""}

        mock_post.return_value = {"success": True}

        creds = {
            "facebook": {
                "post_method": "browser",
                "browser_profile": "Profile 2",
                "browser_headless": True,
            }
        }
        worker = SocialUploadWorker(
            video_path="/fake/vid.mp4",
            platforms=["facebook"],
            metadata={"title": "Test Title"},
            credentials=creds,
        )

        with patch.object(FacebookBrowserPoster, "check_session_status", autospec=True, side_effect=fake_status):
            res = worker._run_facebook("/fake/vid.mp4", {"title": "Test Title"})
            self.assertTrue(res["success"])
            self.assertEqual(mock_post.call_count, 1)

    def test_browser_asset_id_ui_field_and_sanitization(self):
        """Verify Target Page / Asset ID input exists in UI, auto-saves, and sanitizes '12345'."""
        from facebook_browser_poster import DEFAULT_ASSET_ID
        win = SocialPostWindow()
        self.app.processEvents()

        self.assertTrue(hasattr(win, "input_fb_browser_asset_id"))
        # Set dummy 12345
        win.input_fb_browser_asset_id.setText("12345")
        self.app.processEvents()

        # Save should sanitize 12345 to DEFAULT_ASSET_ID
        win._save_accounts_data(show_msg=False)
        cfg = social_post_config.get_facebook_config()
        self.assertEqual(cfg["browser_asset_id"], DEFAULT_ASSET_ID)

        # Set custom real ID
        win.input_fb_browser_asset_id.setText("987654321098765")
        self.app.processEvents()
        cfg2 = social_post_config.get_facebook_config()
        self.assertEqual(cfg2["browser_asset_id"], "987654321098765")
        win.close()

    @patch("facebook_browser_poster.FacebookBrowserPoster.bulk_post")
    def test_worker_sanitizes_asset_id_12345_fallback(self, mock_bulk):
        """Verify SocialUploadWorker sanitizes page_id='12345' and falls back to DEFAULT_ASSET_ID."""
        import tempfile
        from facebook_browser_poster import DEFAULT_ASSET_ID
        mock_bulk.return_value = {"success": True}

        with tempfile.TemporaryDirectory() as tmp_dir:
            v1 = os.path.join(tmp_dir, "vid1.mp4")
            v2 = os.path.join(tmp_dir, "vid2.mp4")
            with open(v1, "wb") as f:
                f.write(b"1")
            with open(v2, "wb") as f:
                f.write(b"2")

            creds = {
                "facebook": {
                    "post_method": "browser",
                    "browser_profile": "Default",
                    "browser_headless": True,
                    "page_id": "12345",
                }
            }
            worker = SocialUploadWorker(
                video_paths=[v1, v2],
                platforms=["facebook"],
                metadata={"title": "Test Title"},
                credentials=creds,
            )

            with patch.object(FacebookBrowserPoster, "check_session_status", return_value={"logged_in": True, "user_id": "100"}):
                res = worker._run_facebook(v1, {"title": "Test Title"})
                self.assertTrue(res["success"])
                self.assertEqual(mock_bulk.call_count, 1)
                call_kwargs = mock_bulk.call_args[1]
                self.assertEqual(call_kwargs["asset_id"], DEFAULT_ASSET_ID)


if __name__ == "__main__":
    unittest.main()

