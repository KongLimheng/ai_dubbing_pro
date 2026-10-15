# -*- coding: utf-8 -*-
"""
tests/test_facebook_bulk_composer.py - Comprehensive Unit Tests for Meta Business Suite
Bulk Upload Composer Browser Automation.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure src is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from facebook_browser_poster import (
    DEFAULT_ASSET_ID,
    MBS_BULK_COMPOSER_URL,
    MBS_COMPOSER_URL,
    FacebookBrowserPoster,
    extract_episode_number,
    format_video_description,
)
from social_post_window import parse_folder_config
from social_post_uploader import SocialUploadWorker


class TestFacebookBulkComposer(unittest.TestCase):
    """Test suite for Bulk Upload Composer automation and helpers."""

    @classmethod
    def setUpClass(cls):
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

    def test_default_constants(self):
        """Verify default asset ID and bulk composer URL."""
        self.assertEqual(DEFAULT_ASSET_ID, "364039971101203")
        self.assertEqual(MBS_BULK_COMPOSER_URL, "https://business.facebook.com/latest/bulk_upload_composer")
        self.assertTrue(MBS_COMPOSER_URL.endswith("/composer"))

    def test_extract_episode_number(self):
        """Verify episode number regex extraction across varied naming formats."""
        cases = [
            ("Drama Episode 01.mp4", 1),
            ("Episode 12.mkv", 12),
            ("Drama_Ep.05.mp4", 5),
            ("Series_Ep_3.mov", 3),
            ("Clip E04.mp4", 4),
            ("Show E6.webm", 6),
            ("Part 07.mp4", 7),
            ("Part_2.mp4", 2),
            ("Tập 10.mp4", 10),
            ("Tap 08.mp4", 8),
            ("09.mp4", 9),
            ("Movie - 15 - Clip.mp4", 15),
            ("Random_Video_Without_Number.mp4", 99),  # Fallback
        ]
        for filename, expected in cases:
            with self.subTest(filename=filename):
                extracted = extract_episode_number(filename, fallback_idx=99)
                self.assertEqual(extracted, expected, f"Failed for {filename}")

    def test_format_video_description_default(self):
        """Test default dynamic description construction."""
        desc = format_video_description(
            template="",
            title="My Drama",
            episode_num=5,
            filename="drama_05.mp4",
            extra_desc="Dubbed with AI Dubber\n#dubbing",
        )
        self.assertIn("My Drama Episode 5", desc)
        self.assertIn("Dubbed with AI Dubber", desc)
        self.assertIn("#dubbing", desc)

    def test_format_video_description_custom_template(self):
        """Test placeholder replacement in custom templates."""
        template = "Watch {title} Ep {episode}! Best moments #{filename}"
        desc = format_video_description(
            template=template,
            title="Action Show",
            episode_num=8,
            filename="ActionShow_E08.mp4",
        )
        self.assertEqual(desc, "Watch Action Show Ep 8! Best moments #ActionShow_E08")

    def test_parse_folder_config_with_playlist_and_asset_id(self):
        """Test parsing config.txt containing playlist and asset_id."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "config.txt")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(
                    "Title: Romance in the City\n"
                    "Playlist: Season 1 Romance Series\n"
                    "Asset_ID: 364039971101203\n"
                    "Description:\n"
                    "An emotional modern drama series.\n"
                    "#romance #drama #viral\n"
                )

            res = parse_folder_config(tmp_dir)
            self.assertTrue(res["found"])
            self.assertEqual(res["title"], "Romance in the City")
            self.assertEqual(res["playlist"], "Season 1 Romance Series")
            self.assertEqual(res["asset_id"], "364039971101203")
            self.assertIn("An emotional modern drama series.", res["description"])
            self.assertIn("#romance", res["description"])

    @patch("playwright.sync_api.sync_playwright")
    def test_upload_bulk_videos_via_playwright_mock(self, mock_playwright):
        """Test bulk upload browser flow with mock Playwright context and elements."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            v1 = os.path.join(tmp_dir, "Episode 01.mp4")
            v2 = os.path.join(tmp_dir, "Episode 02.mp4")
            with open(v1, "wb") as f:
                f.write(b"video1")
            with open(v2, "wb") as f:
                f.write(b"video2")

            # Mock Playwright hierarchy
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/latest/bulk_upload_composer"

            # Mock file input
            mock_file_input = MagicMock()
            mock_page.query_selector.side_effect = lambda sel: (
                mock_file_input if 'input[type="file"]' in sel else MagicMock()
            )

            mock_context = MagicMock()
            mock_context.pages = [mock_page]
            mock_pw_instance = MagicMock()
            mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
            mock_playwright.return_value.__enter__.return_value = mock_pw_instance

            poster = FacebookBrowserPoster(profile_name="Default", headless=True)
            res = poster.bulk_post(
                video_paths=[v1, v2],
                title="Romance Series",
                description="Enjoy the show!",
                asset_id=DEFAULT_ASSET_ID,
                playlist="Romance Playlist",
                disable_caption=True,
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "bulk_browser_automation")
            self.assertEqual(res["video_count"], 2)
            self.assertEqual(res["asset_id"], "364039971101203")
            self.assertEqual(res["playlist"], "Romance Playlist")
            mock_page.goto.assert_called_once()
            self.assertIn("364039971101203", mock_page.goto.call_args[0][0])

    @patch("facebook_browser_poster.FacebookBrowserPoster.bulk_post")
    def test_social_upload_worker_browser_bulk_delegation(self, mock_bulk_post):
        """Verify SocialUploadWorker delegates batch videos to bulk_post once."""
        mock_bulk_post.return_value = {
            "success": True,
            "method": "bulk_browser_automation",
            "video_count": 2,
            "url": "https://business.facebook.com/latest/bulk_upload_composer?asset_id=364039971101203",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            v1 = os.path.join(tmp_dir, "Ep1.mp4")
            v2 = os.path.join(tmp_dir, "Ep2.mp4")
            with open(v1, "wb") as f:
                f.write(b"v1")
            with open(v2, "wb") as f:
                f.write(b"v2")

            credentials = {
                "facebook": {
                    "post_method": "browser",
                    "browser_profile": "Default",
                    "page_id": "364039971101203",
                }
            }
            metadata = {
                "title": "Drama Show",
                "description": "Episode details",
                "fb_playlist_id": "Drama Playlist",
                "fb_disable_caption": True,
            }

            worker = SocialUploadWorker(
                video_paths=[v1, v2],
                platforms=["facebook"],
                metadata=metadata,
                credentials=credentials,
            )

            # Run Facebook uploader for first video
            res1 = worker._run_facebook(v1, metadata)
            self.assertTrue(res1["success"])
            self.assertEqual(mock_bulk_post.call_count, 1)
            mock_args = mock_bulk_post.call_args[1]
            self.assertEqual(mock_args["asset_id"], "364039971101203")
            self.assertEqual(mock_args["playlist"], "Drama Playlist")
            self.assertTrue(mock_args["disable_caption"])

            # Run Facebook uploader for second video in the batch - should reuse bulk session
            res2 = worker._run_facebook(v2, metadata)
            self.assertTrue(res2["success"])
            # Should NOT have invoked bulk_post a second time
            self.assertEqual(mock_bulk_post.call_count, 1)

    def test_handle_checkpoint_no_checkpoint(self):
        """Verify _handle_checkpoint_or_login returns immediately if no checkpoint in URL."""
        poster = FacebookBrowserPoster(profile_name="Default", headless=True)
        mock_page = MagicMock()
        mock_page.url = "https://business.facebook.com/latest/composer?asset_id=123"
        mock_context = MagicMock()

        ctx, pg = poster._handle_checkpoint_or_login(
            mock_page, mock_context, mock_page.url, lambda pct, msg: None, None
        )
        self.assertIs(ctx, mock_context)
        self.assertIs(pg, mock_page)
        mock_context.close.assert_not_called()

    def test_handle_checkpoint_headless_switches_to_headful(self):
        """Verify headless mode automatically launches headful Chrome on checkpoint and saves cookies."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            poster = FacebookBrowserPoster(user_data_dir=tmp_dir, profile_name="TestProf", headless=True)
            mock_headless_page = MagicMock()
            mock_headless_page.url = "https://www.facebook.com/login.php?next=composer"
            mock_headless_context = MagicMock()

            # Mock new headful context
            mock_headful_context = MagicMock()
            mock_headful_page = MagicMock()
            mock_headful_context.pages = [mock_headful_page]

            mock_p = MagicMock()
            mock_p.chromium.launch_persistent_context.return_value = mock_headful_context

            reports = []
            def report_cb(p, m):
                reports.append((p, m))

            ctx, pg = poster._handle_checkpoint_or_login(
                mock_headless_page,
                mock_headless_context,
                "https://business.facebook.com/latest/composer",
                report_cb,
                mock_p,
            )

            # Headless context was closed
            mock_headless_context.close.assert_called_once()
            # Headful context was launched with headless=False
            mock_p.chromium.launch_persistent_context.assert_called_once()
            call_kwargs = mock_p.chromium.launch_persistent_context.call_args[1]
            self.assertFalse(call_kwargs["headless"])
            # wait_for_url was called on new page
            mock_headful_page.wait_for_url.assert_called_once()
            # Storage state was saved
            mock_headful_context.storage_state.assert_called_once()
            # Returned context is the headful one
            self.assertIs(ctx, mock_headful_context)
            self.assertIs(pg, mock_headful_page)

            # Verify reported status messages
            report_texts = [r[1] for r in reports]
            self.assertTrue(any("checkpoint" in t.lower() for t in report_texts))
            self.assertTrue(any("saved" in t.lower() for t in report_texts))

    def test_handle_checkpoint_timeout_raises_runtime_error(self):
        """Verify timeout during checkpoint waiting raises informative RuntimeError."""
        poster = FacebookBrowserPoster(profile_name="Default", headless=False)
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/checkpoint/82823/"
        mock_context = MagicMock()
        mock_page.wait_for_url.side_effect = Exception("Timeout 120000ms exceeded")

        with self.assertRaises(RuntimeError) as ctx:
            poster._handle_checkpoint_or_login(
                mock_page, mock_context, mock_page.url, lambda pct, msg: None, None
            )
        self.assertIn("Facebook login / checkpoint was not completed", str(ctx.exception))
        self.assertIn("Open Chrome to Log In", str(ctx.exception))

    @patch("playwright.sync_api.sync_playwright")
    def test_bulk_composer_sanitizes_asset_id_12345(self, mock_playwright):
        """Verify upload_bulk_videos_via_playwright falls back to DEFAULT_ASSET_ID when given '12345'."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            v1 = os.path.join(tmp_dir, "test.mp4")
            with open(v1, "wb") as f:
                f.write(b"video")

            mock_p = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_page.url = f"{MBS_BULK_COMPOSER_URL}?asset_id={DEFAULT_ASSET_ID}"
            mock_context.pages = [mock_page]
            mock_p.chromium.launch_persistent_context.return_value = mock_context

            # Mock successful flow elements
            mock_page.query_selector.return_value = MagicMock()
            mock_page.query_selector_all.return_value = []
            mock_page.wait_for_selector.return_value = MagicMock()

            poster = FacebookBrowserPoster(profile_name="Default", user_data_dir=tmp_dir)
            poster.upload_bulk_videos_via_playwright(
                video_paths=[v1],
                asset_id="12345",  # Should be sanitized to DEFAULT_ASSET_ID
            )

            # Check that page.goto navigated with DEFAULT_ASSET_ID and NOT 12345
            goto_url = mock_page.goto.call_args[0][0]
            self.assertIn(f"asset_id={DEFAULT_ASSET_ID}", goto_url)
            self.assertNotIn("asset_id=12345", goto_url)


if __name__ == "__main__":
    unittest.main()
