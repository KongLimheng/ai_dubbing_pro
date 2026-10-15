# -*- coding: utf-8 -*-
"""
test_social_post.py - Unit and Integration Tests for Social Post Feature.
Verifies button integration, SocialPostWindow UI, configuration persistence,
upload engine logic, and real-time Dark/Light theme adaptability.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PyQt5.QtWidgets import QApplication, QPushButton, QProgressBar
from PyQt5.QtCore import Qt

import settings_manager
import theme_manager
import core_app
import social_post_config
import social_post_uploader
from social_post_window import (
    SocialPostWindow, probe_video_meta, format_file_size,
    parse_folder_config, scan_folder_videos, BatchMetadataDialog
)


class TestSocialPostFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import tempfile
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls._temp_cfg = os.path.join(cls._temp_dir.name, ".app_config.json")
        cls._cfg_patch = patch("settings_manager.get_config_file_path", return_value=cls._temp_cfg)
        cls._cfg_patch.start()
        cls._auto_fb_patch = patch("social_post_window.SocialPostWindow._auto_fetch_fb_options", return_value=None)
        cls._auto_fb_patch.start()
        cls._pl_worker_patch = patch("social_post_window.FacebookPlaylistsWorker.start", return_value=None)
        cls._grp_worker_patch = patch("social_post_window.FacebookGroupsWorker.start", return_value=None)
        cls._pl_worker_patch.start()
        cls._grp_worker_patch.start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls._pl_worker_patch.stop()
            cls._grp_worker_patch.stop()
            cls._auto_fb_patch.stop()
            cls._cfg_patch.stop()
            cls._temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self):
        settings_manager.write_config({})
        settings_manager.save_theme_mode("dark")
        theme_manager.apply_theme("dark", self.app)

    def test_button_presence_in_main_app(self):
        """Verify btn_social_post is instantiated in DubbingApp near btn_theme_toggle."""
        win = core_app.DubbingApp()
        self.app.processEvents()

        self.assertTrue(hasattr(win, "btn_theme_toggle"), "DubbingApp must have btn_theme_toggle.")
        self.assertTrue(hasattr(win, "btn_social_post"), "DubbingApp must have btn_social_post.")
        self.assertIsNotNone(win.btn_social_post, "btn_social_post must not be None.")
        self.assertEqual(win.btn_social_post.objectName(), "btn_social_post")
        self.assertIn("Social Post", win.btn_social_post.text())

        # Test opening the window via method
        win._open_social_post_window()
        self.assertTrue(hasattr(win, "_social_post_window"))
        self.assertIsInstance(win._social_post_window, SocialPostWindow)
        win._social_post_window.close()

    def test_social_post_config_persistence(self):
        """Verify saving and retrieving social configs and upload history."""
        # Facebook
        fb_data = {
            "page_id": "test_page_123",
            "page_name": "AI Dubber Fanpage",
            "page_token": "EAA_test_token_xyz",
            "published": True,
        }
        social_post_config.save_facebook_config(fb_data)
        loaded_fb = social_post_config.get_facebook_config()
        self.assertEqual(loaded_fb["page_id"], "test_page_123")
        self.assertEqual(loaded_fb["page_name"], "AI Dubber Fanpage")
        self.assertEqual(loaded_fb["page_token"], "EAA_test_token_xyz")

        # YouTube
        yt_data = {
            "client_id": "test_client_id.apps.googleusercontent.com",
            "client_secret": "test_secret_xyz",
            "refresh_token": "1//test_refresh_token",
            "channel_title": "Dubbing Tech",
        }
        social_post_config.save_youtube_config(yt_data)
        loaded_yt = social_post_config.get_youtube_config()
        self.assertEqual(loaded_yt["client_id"], "test_client_id.apps.googleusercontent.com")
        self.assertEqual(loaded_yt["channel_title"], "Dubbing Tech")

        # TikTok
        tt_data = {
            "access_token": "act.test_tiktok_token",
            "creator_name": "DubberCreator",
        }
        social_post_config.save_tiktok_config(tt_data)
        loaded_tt = social_post_config.get_tiktok_config()
        self.assertEqual(loaded_tt["access_token"], "act.test_tiktok_token")
        self.assertEqual(loaded_tt["creator_name"], "DubberCreator")

        # History
        social_post_config.clear_upload_history()
        hist = social_post_config.get_upload_history()
        self.assertEqual(len(hist), 0)

        entry = {
            "video_name": "test_video.mp4",
            "video_path": "/fake/path/test_video.mp4",
            "title": "My Dubbed Movie",
            "platforms": {"youtube": {"success": True, "url": "https://youtu.be/123"}},
        }
        social_post_config.add_upload_history_entry(entry)
        hist = social_post_config.get_upload_history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["video_name"], "test_video.mp4")

    def test_social_post_window_ui_and_themes(self):
        """Verify SocialPostWindow builds all tabs and switches between dark and light mode."""
        sp_win = SocialPostWindow()
        self.app.processEvents()

        # Tabs verification
        self.assertEqual(sp_win.tabs.count(), 3)
        self.assertIn("Publish Video", sp_win.tabs.tabText(0))
        self.assertIn("Accounts & API Setup", sp_win.tabs.tabText(1))
        self.assertIn("Publishing History", sp_win.tabs.tabText(2))

        # Check UI components
        self.assertIsNotNone(sp_win.btn_publish)
        self.assertIsNotNone(sp_win.btn_cancel)
        self.assertIsNotNone(sp_win.bar_fb)
        self.assertIsNotNone(sp_win.bar_yt)
        self.assertIsNotNone(sp_win.bar_tt)

        # Test hashtag appending
        sp_win.desc_input.setPlainText("Exciting scene")
        sp_win._append_hashtag("#shorts")
        self.assertIn("#shorts", sp_win.desc_input.toPlainText())
        # Appending same tag shouldn't duplicate
        sp_win._append_hashtag("#shorts")
        self.assertEqual(sp_win.desc_input.toPlainText().count("#shorts"), 1)

        # Test title counter
        sp_win._update_title_counter("Hello World")
        self.assertEqual(sp_win.title_counter_lbl.text(), "11 / 100")

        # Test theme toggle to light mode
        sp_win.apply_dialog_theme("light")
        self.app.processEvents()
        self.assertIn("background-color:", sp_win.styleSheet())

        # Test theme toggle back to dark mode
        sp_win.apply_dialog_theme("dark")
        self.app.processEvents()
        self.assertIn("background-color:", sp_win.styleSheet())

        sp_win.close()

    def test_uploader_validation(self):
        """Verify that upload engines validate input parameters correctly."""
        # Non-existent file should raise FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            social_post_uploader.FacebookUploader.upload_video(
                video_path="/non/existent/path/vid.mp4",
                page_id="123",
                access_token="tok",
            )

        with self.assertRaises(FileNotFoundError):
            social_post_uploader.YouTubeUploader.upload_video(
                video_path="/non/existent/path/vid.mp4",
                access_token="tok",
                title="test",
            )

        with self.assertRaises(FileNotFoundError):
            social_post_uploader.TikTokUploader.upload_video(
                video_path="/non/existent/path/vid.mp4",
                access_token="tok",
                title="test",
            )

        # Missing credentials should raise ValueError
        with self.assertRaises(ValueError):
            social_post_uploader.FacebookUploader.test_connection("", "")

        with self.assertRaises(ValueError):
            social_post_uploader.YouTubeUploader.test_connection("")

        with self.assertRaises(ValueError):
            social_post_uploader.TikTokUploader.test_connection("")

    @patch("requests.post")
    def test_mock_facebook_upload_flow(self, mock_post):
        """Verify Facebook chunked upload flow with mocked API responses."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"0" * 1024 * 100)  # 100KB dummy video
            temp_path = f.name

        try:
            # Mock Phase 1 (start), Phase 2 (transfer), Phase 3 (finish)
            mock_res_init = MagicMock()
            mock_res_init.status_code = 200
            mock_res_init.json.return_value = {
                "upload_session_id": "sess_123",
                "video_id": "vid_456",
                "start_offset": 0,
                "end_offset": 102400,
            }

            mock_res_transfer = MagicMock()
            mock_res_transfer.status_code = 200
            mock_res_transfer.json.return_value = {
                "start_offset": 102400,
                "end_offset": 102400,
            }

            mock_res_finish = MagicMock()
            mock_res_finish.status_code = 200
            mock_res_finish.json.return_value = {
                "success": True,
                "id": "vid_456",
            }

            mock_post.side_effect = [mock_res_init, mock_res_transfer, mock_res_finish]

            progress_calls = []
            res = social_post_uploader.FacebookUploader.upload_video(
                video_path=temp_path,
                page_id="page_999",
                access_token="test_token",
                title="Test Title",
                description="Test Desc",
                progress_callback=lambda p, s: progress_calls.append((p, s)),
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["video_id"], "vid_456")
            self.assertIn("facebook.com", res["url"])
            self.assertTrue(len(progress_calls) >= 2)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_social_upload_worker_execution(self):
        """Verify SocialUploadWorker runs and signals progress and completion."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"0" * 1024 * 50)
            temp_path = f.name

        try:
            worker = social_post_uploader.SocialUploadWorker(
                video_path=temp_path,
                platforms=["facebook"],
                metadata={"title": "Test"},
                credentials={"facebook": {"page_id": "123", "page_token": "token"}},
            )

            started_events = []
            progress_events = []
            completed_events = []
            all_done = []

            worker.platform_started.connect(lambda p: started_events.append(p))
            worker.platform_progress.connect(lambda p, pct, s: progress_events.append((p, pct, s)))
            worker.platform_completed.connect(lambda p, succ, msg, url: completed_events.append((p, succ, msg, url)))
            worker.all_completed.connect(lambda d: all_done.append(d))

            # Mock _run_facebook
            worker._run_facebook = MagicMock(return_value={"success": True, "url": "https://fb.com/vid", "video_id": "111"})

            worker.run()

            self.assertEqual(started_events, ["facebook"])
            self.assertEqual(len(completed_events), 1)
            self.assertTrue(completed_events[0][1])  # success = True
            self.assertEqual(len(all_done), 1)
            self.assertEqual(all_done[0]["success_count"], 1)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("social_post_window.FacebookUploader.fetch_all_available_groups", return_value=[])
    @patch("social_post_window.FacebookUploader.fetch_page_playlists", return_value=[])
    @patch("social_post_window.FacebookUploader.inspect_token", return_value={"status_label": "Valid", "is_permanent": True})
    @patch("social_post_window.FacebookUploader.test_connection")
    def test_test_facebook_connection_runs_without_name_error(self, mock_test, mock_insp, mock_pl, mock_grp):
        """Verify _test_facebook_connection executes without NameError on QApplication."""
        mock_test.return_value = {
            "name": "Mock Page",
            "fans": 1200,
            "id": "12345",
        }
        sp_win = SocialPostWindow()
        self.app.processEvents()

        sp_win.input_fb_page_id.setText("12345")
        sp_win.input_fb_page_token.setText("valid_token")
        sp_win._fetch_facebook_playlists = MagicMock()
        sp_win._fetch_facebook_groups = MagicMock()

        # Call method directly - should not raise NameError: name 'QApplication' is not defined
        sp_win._test_facebook_connection()
        self.assertIn("Connected", sp_win.lbl_fb_status.text())
        self.assertEqual(sp_win.input_fb_page_name.text(), "Mock Page")
        sp_win.close()

    @patch("PyQt5.QtWidgets.QInputDialog.getItem")
    @patch("social_post_uploader.FacebookUploader.fetch_user_pages")
    def test_fetch_user_pages_runs_without_attribute_error(self, mock_fetch, mock_input):
        """Verify _fetch_user_facebook_pages executes without AttributeError on QInputDialog."""
        mock_fetch.return_value = [
            {"name": "Page A", "id": "111", "access_token": "tok_a"}
        ]
        mock_input.return_value = ("Page A (ID: 111)", True)

        sp_win = SocialPostWindow()
        self.app.processEvents()

        sp_win.input_fb_page_token.setText("user_token")
        sp_win._fetch_user_facebook_pages()

        self.assertEqual(sp_win.input_fb_page_id.text(), "111")
        self.assertEqual(sp_win.input_fb_page_name.text(), "Page A")
        self.assertEqual(sp_win.input_fb_page_token.text(), "tok_a")
        sp_win.close()


    def test_parse_folder_config(self):
        """Verify config.txt parser handles key-value, plain text, utf-8 Khmer, and missing file."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            # 1. Missing file
            res_missing = parse_folder_config(temp_dir)
            self.assertFalse(res_missing["found"])
            self.assertEqual(res_missing["title"], "")

            # 2. Key-value format
            cfg_path = os.path.join(temp_dir, "config.txt")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write("Title: ដំណើរផ្សងព្រេង Episode 01\n")
                f.write("Description:\nសម្រាយរឿងភាគថ្មី #shorts #khmer\nភាគទី 1\n")

            res_kv = parse_folder_config(temp_dir)
            self.assertTrue(res_kv["found"])
            self.assertEqual(res_kv["title"], "ដំណើរផ្សងព្រេង Episode 01")
            self.assertIn("សម្រាយរឿងភាគថ្មី", res_kv["description"])
            self.assertIn("ភាគទី 1", res_kv["description"])

            # 3. Simple format (line 1 title, rest description)
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write("Simple Movie Title\nThis is line 2 of description.\nAnd line 3.")

            res_simple = parse_folder_config(temp_dir)
            self.assertTrue(res_simple["found"])
            self.assertEqual(res_simple["title"], "Simple Movie Title")
            self.assertIn("This is line 2 of description.", res_simple["description"])
            self.assertIn("And line 3.", res_simple["description"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scan_folder_videos(self):
        """Verify scan_folder_videos naturally sorts video files and ignores non-videos."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            for name in ["ep10.mp4", "ep2.mp4", "ep1.mp4", "notes.txt", "sub.srt"]:
                with open(os.path.join(temp_dir, name), "w") as f:
                    f.write("dummy")

            videos = scan_folder_videos(temp_dir)
            self.assertEqual(len(videos), 3)
            base_names = [os.path.basename(v) for v in videos]
            self.assertEqual(base_names, ["ep1.mp4", "ep2.mp4", "ep10.mp4"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_batch_metadata_dialog_logic(self):
        """Verify BatchMetadataDialog sets title, description, and writes config.txt."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            dlg = BatchMetadataDialog(temp_dir, 3)
            dlg.txt_title.setText("My Batch Title {index}")
            dlg.txt_desc.setPlainText("Batch description #viral")
            dlg.chk_save.setChecked(True)
            dlg._on_apply()

            self.assertEqual(dlg.applied_title, "My Batch Title {index}")
            self.assertEqual(dlg.applied_description, "Batch description #viral")

            # Check config.txt was written
            cfg_path = os.path.join(temp_dir, "config.txt")
            self.assertTrue(os.path.exists(cfg_path))
            with open(cfg_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("My Batch Title {index}", content)
            self.assertIn("Batch description #viral", content)
            dlg.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("requests.get")
    @patch("requests.post")
    def test_facebook_playlists_and_groups_api(self, mock_post, mock_get):
        """Verify FacebookUploader fetch_page_playlists, add_video_to_playlist, fetch_user_groups, share_video_to_group."""
        # 1. fetch_page_playlists
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {
            "data": [
                {"id": "pl_100", "title": "Series A", "description": "Desc A"},
                {"id": "pl_200", "title": "Series B", "description": "Desc B"},
            ]
        }
        mock_get.return_value = mock_get_resp

        playlists = social_post_uploader.FacebookUploader.fetch_page_playlists("page_123", "tok_xyz")
        self.assertEqual(len(playlists), 2)
        self.assertEqual(playlists[0]["id"], "pl_100")
        self.assertEqual(playlists[0]["title"], "Series A")

        # 2. add_video_to_playlist
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"success": True}
        mock_post.return_value = mock_post_resp

        res_pl = social_post_uploader.FacebookUploader.add_video_to_playlist("pl_100", "vid_999", "tok_xyz")
        self.assertTrue(res_pl)

        # 3. fetch_user_groups
        mock_get_resp.json.return_value = {
            "data": [
                {"id": "grp_555", "name": "Drama Fans Cambodia", "privacy": "CLOSED", "administrator": True}
            ]
        }
        groups = social_post_uploader.FacebookUploader.fetch_user_groups("tok_xyz")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "Drama Fans Cambodia")

        # 4. share_video_to_group
        mock_post_resp.json.return_value = {"id": "feed_post_777"}
        share_res = social_post_uploader.FacebookUploader.share_video_to_group("grp_555", "https://fb.watch/123", "Title", "tok_xyz")
        self.assertTrue(share_res["success"])
        self.assertEqual(share_res["post_id"], "feed_post_777")

    @patch("requests.post")
    @patch("social_post_uploader.FacebookUploader.add_video_to_playlist")
    @patch("social_post_uploader.FacebookUploader.share_video_to_group")
    def test_facebook_upload_disable_caption_and_playlist(self, mock_share, mock_add_pl, mock_post):
        """Verify upload_video respects disable_caption, playlist_id, and group_id."""
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_file.write(b"0" * 1024)
        temp_file.close()

        try:
            # Phase 1: init session
            resp_init = MagicMock()
            resp_init.status_code = 200
            resp_init.json.return_value = {
                "upload_session_id": "sess_1",
                "start_offset": 0,
                "end_offset": 1024,
            }
            # Phase 2: transfer chunk
            resp_transfer = MagicMock()
            resp_transfer.status_code = 200
            resp_transfer.json.return_value = {"start_offset": 1024, "end_offset": 1024}
            # Phase 3: finish session
            resp_finish = MagicMock()
            resp_finish.status_code = 200
            resp_finish.json.return_value = {"success": True, "id": "vid_final_1"}

            mock_post.side_effect = [resp_init, resp_transfer, resp_finish]

            res = social_post_uploader.FacebookUploader.upload_video(
                video_path=temp_file.name,
                page_id="page_123",
                access_token="tok_abc",
                title="Episode 1",
                description="Original description text",
                published=True,
                disable_caption=True,
                playlist_id="pl_999",
                group_id="grp_888",
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["video_id"], "vid_final_1")

            # Verify finish payload had description="" because disable_caption was True
            finish_call_args = mock_post.call_args_list[2]
            payload = finish_call_args[1].get("data", {})
            self.assertEqual(payload.get("description"), "")

            # Verify playlist and group helpers were called
            mock_add_pl.assert_called_once_with("pl_999", "vid_final_1", "tok_abc")
            mock_share.assert_called_once()
        finally:
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)

    @patch("social_post_uploader.FacebookUploader.upload_video")
    def test_social_upload_worker_batch_queue(self, mock_upload):
        """Verify SocialUploadWorker executes multiple videos in queue with token replacement."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            v1 = os.path.join(temp_dir, "ep1.mp4")
            v2 = os.path.join(temp_dir, "ep2.mp4")
            for p in (v1, v2):
                with open(p, "wb") as f:
                    f.write(b"0" * 512)

            mock_upload.return_value = {
                "success": True,
                "video_id": "v101",
                "url": "https://fb.watch/test",
                "platform": "facebook",
            }

            metadata = {
                "title": "Series Episode {index} ({filename})",
                "description": "Watch {filename}",
                "fb_published": True,
                "fb_disable_caption": True,
            }
            credentials = {
                "facebook": {"page_id": "111", "page_token": "tok"},
            }

            worker = social_post_uploader.SocialUploadWorker(
                video_paths=[v1, v2],
                platforms=["facebook"],
                metadata=metadata,
                credentials=credentials,
            )

            started_events = []
            completed_events = []
            worker.video_queue_started.connect(lambda idx, tot, name: started_events.append((idx, tot, name)))
            worker.video_queue_completed.connect(lambda idx, tot, name, res: completed_events.append((idx, tot, name)))

            worker.run()

            self.assertEqual(len(started_events), 2)
            self.assertEqual(started_events[0], (1, 2, "ep1.mp4"))
            self.assertEqual(started_events[1], (2, 2, "ep2.mp4"))

            self.assertEqual(mock_upload.call_count, 2)
            # Check token replacement in call 1
            call1_kwargs = mock_upload.call_args_list[0][1]
            self.assertEqual(call1_kwargs["title"], "Series Episode 1 (ep1)")
            self.assertTrue(call1_kwargs["disable_caption"])

            # Check token replacement in call 2
            call2_kwargs = mock_upload.call_args_list[1][1]
            self.assertEqual(call2_kwargs["title"], "Series Episode 2 (ep2)")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ui_folder_mode_and_facebook_widgets(self):
        """Verify UI elements for folder mode, disable caption checkbox, playlist & group selectors."""
        import tempfile
        import shutil

        sp_win = SocialPostWindow()
        self.app.processEvents()

        # Check widget presence
        self.assertTrue(hasattr(sp_win, "btn_browse_folder"))
        self.assertTrue(hasattr(sp_win, "chk_fb_disable_caption"))
        self.assertTrue(hasattr(sp_win, "cmb_fb_playlist"))
        self.assertTrue(hasattr(sp_win, "btn_refresh_fb_playlists"))
        self.assertTrue(hasattr(sp_win, "cmb_fb_group"))
        self.assertTrue(hasattr(sp_win, "btn_refresh_fb_groups"))
        self.assertTrue(hasattr(sp_win, "folder_queue_badge"))

        # Test selecting a folder with config.txt
        temp_dir = tempfile.mkdtemp()
        try:
            for name in ["scene1.mp4", "scene2.mp4"]:
                with open(os.path.join(temp_dir, name), "wb") as f:
                    f.write(b"0" * 512)
            with open(os.path.join(temp_dir, "config.txt"), "w", encoding="utf-8") as f:
                f.write("Title: Adventure Saga\nDescription: Best series 2026 #saga")

            sp_win.set_selected_folder(temp_dir)
            self.assertTrue(sp_win.is_folder_mode)
            self.assertEqual(len(sp_win.folder_queue), 2)
            self.assertEqual(sp_win.title_input.text(), "Adventure Saga")
            self.assertIn("Best series 2026", sp_win.desc_input.toPlainText())
            self.assertIn("Auto Post 2 Videos", sp_win.btn_publish.text())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            sp_win.close()

    def test_facebook_schedule_preset_buttons_and_preview(self):
        """Verify schedule preset buttons apply correct offsets and update live preview."""
        from PyQt5.QtCore import QDateTime
        sp_win = SocialPostWindow()
        sp_win.show()
        self.app.processEvents()

        try:
            # Switch to Schedule Public
            sp_win.cmb_fb_publish.setCurrentIndex(1)
            self.assertFalse(sp_win.fb_schedule_container.isHidden())
            self.assertTrue(sp_win.fb_schedule_container.isVisible())

            # Test +30m
            sp_win._apply_schedule_offset(1800)
            now_dt = QDateTime.currentDateTime()
            self.assertGreater(sp_win.dt_fb_schedule.dateTime(), now_dt.addSecs(600))
            self.assertIn("Will publish:", sp_win.lbl_schedule_preview.text())

            # Test Tomorrow 9AM
            sp_win._apply_schedule_tomorrow_9am()
            self.assertGreater(sp_win.dt_fb_schedule.dateTime(), now_dt.addSecs(3600))
            self.assertEqual(sp_win.dt_fb_schedule.time().hour(), 9)
            self.assertEqual(sp_win.dt_fb_schedule.time().minute(), 0)
            self.assertIn("09:00 AM", sp_win.lbl_schedule_preview.text())

            # Test Tomorrow 6PM
            sp_win._apply_schedule_tomorrow_6pm()
            self.assertEqual(sp_win.dt_fb_schedule.time().hour(), 18)
            self.assertIn("06:00 PM", sp_win.lbl_schedule_preview.text())

            # Test Tomorrow 8PM
            sp_win._apply_schedule_tomorrow_8pm()
            self.assertEqual(sp_win.dt_fb_schedule.time().hour(), 20)
            self.assertIn("08:00 PM", sp_win.lbl_schedule_preview.text())

            # Test Reset (+1h)
            sp_win._apply_schedule_reset_1h()
            self.assertGreater(sp_win.dt_fb_schedule.dateTime(), now_dt.addSecs(3000))
        finally:
            sp_win.close()

    def test_facebook_schedule_layout_and_button_dimensions(self):
        """Verify preset buttons have spacious clickable dimensions and pointer cursors."""
        sp_win = SocialPostWindow()
        sp_win.resize(1000, 780)
        sp_win.cmb_fb_publish.setCurrentIndex(1)
        sp_win.show()
        self.app.processEvents()

        try:
            self.assertGreaterEqual(sp_win.fb_schedule_container.width(), 350)
            preset_btns = [
                b for b in sp_win.fb_schedule_container.findChildren(QPushButton)
                if b.objectName() == "schedulePresetBtn"
            ]
            self.assertEqual(len(preset_btns), 10, "Must have exactly 10 schedule preset buttons.")
            for btn in preset_btns:
                self.assertGreaterEqual(btn.width(), 50, f"Button '{btn.text()}' width too narrow: {btn.width()}px")
                self.assertGreaterEqual(btn.height(), 26, f"Button '{btn.text()}' height too short: {btn.height()}px")
                self.assertEqual(btn.cursor().shape(), Qt.PointingHandCursor, f"Button '{btn.text()}' must have pointer cursor")
        finally:
            sp_win.close()

    def test_facebook_graph_api_schedule_upload_params(self):
        """Verify Facebook Graph API chunked upload correctly sets published=false and scheduled_publish_time."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        dummy_mp4 = os.path.join(temp_dir, "test_video.mp4")
        with open(dummy_mp4, "wb") as f:
            f.write(b"0" * 1024)

        try:
            with patch("requests.post") as mock_post:
                # Mock phase 1 (start), phase 2 (transfer), phase 3 (finish)
                mock_init = MagicMock(status_code=200)
                mock_init.json.return_value = {"upload_session_id": "sess_123", "video_id": "vid_999"}

                mock_chunk = MagicMock(status_code=200)
                mock_chunk.json.return_value = {"start_offset": 1024, "end_offset": 1024}

                mock_finish = MagicMock(status_code=200)
                mock_finish.json.return_value = {"success": True, "id": "vid_999"}

                mock_post.side_effect = [mock_init, mock_chunk, mock_finish]

                sched_time = 1754150400
                res = social_post_uploader.FacebookUploader.upload_video(
                    video_path=dummy_mp4,
                    page_id="page_123",
                    access_token="tok_abc",
                    title="Scheduled Title",
                    description="Scheduled Desc",
                    published=False,
                    scheduled_publish_time=sched_time,
                    check_closed_caption=False,
                )

                self.assertTrue(res["success"])
                self.assertEqual(res["status"], "scheduled")
                self.assertEqual(res["scheduled_publish_time"], sched_time)

                # Check phase 3 finish payload
                finish_call = mock_post.call_args_list[2]
                finish_data = finish_call[1]["data"]
                self.assertEqual(finish_data["upload_phase"], "finish")
                self.assertEqual(finish_data["published"], "false")
                self.assertEqual(finish_data["scheduled_publish_time"], sched_time)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_schedule_datetime_and_spinbox_theme_colors(self):
        """Verify QDateTimeEdit and QSpinBox do not have white background in dark mode and adapt to light mode."""
        sp_win = SocialPostWindow()
        sp_win.cmb_fb_publish.setCurrentIndex(1)
        sp_win.show()
        self.app.processEvents()

        try:
            # 1. Dark Mode
            sp_win.apply_dialog_theme("dark")
            self.app.processEvents()

            dt_dark = sp_win.dt_fb_schedule.grab().toImage().pixelColor(10, 10).name().lower()
            spin_dark = sp_win.spin_fb_schedule_interval.grab().toImage().pixelColor(10, 10).name().lower()

            # Must not be white (#ffffff)
            self.assertNotEqual(dt_dark, "#ffffff", "Scheduled Date & Time textbox must not be white in dark mode.")
            self.assertNotEqual(spin_dark, "#ffffff", "Batch interval spinbox must not be white in dark mode.")

            # 2. Light Mode
            sp_win.apply_dialog_theme("light")
            self.app.processEvents()

            dt_light = sp_win.dt_fb_schedule.grab().toImage().pixelColor(10, 10).name().lower()
            spin_light = sp_win.spin_fb_schedule_interval.grab().toImage().pixelColor(10, 10).name().lower()

            # Must be light/white in light mode
            self.assertEqual(dt_light, "#ffffff", "Scheduled Date & Time textbox must be white in light mode.")
            self.assertEqual(spin_light, "#ffffff", "Batch interval spinbox must be white in light mode.")
        finally:
            sp_win.close()


if __name__ == "__main__":
    unittest.main()
