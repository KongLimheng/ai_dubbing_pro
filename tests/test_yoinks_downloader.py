# -*- coding: utf-8 -*-
"""
Tests for Yoinks-inspired enhanced video downloader engine and GUI integration.
Covers:
- URL & platform detection (detect_platform, parse_youtube_url, is_probably_url)
- Range parsing (parse_item_range)
- Dynamic choices generation (build_choices, build_playlist_choices)
- Binary resolution (BinaryResolver)
- Filename sanitization & partial cleanup
- GUI components (YouTubeTargetDialog, DownloadQueueItemWidget)
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from dramabox.yoinks_engine import (
    detect_platform,
    parse_youtube_url,
    is_probably_url,
    parse_item_range,
    build_choices,
    build_playlist_choices,
    BinaryResolver,
    sanitize_filename,
    clean_partials,
    score_video_format,
    probe_video_codec,
    convert_av1_to_h264,
    PlatformInfo,
    YouTubeUrlInfo,
    RangeResult,
    DownloadChoice,
)
from core_app import ensure_compatible_video
from dramabox.gui_downloader import YouTubeTargetDialog, DownloadQueueItemWidget


class TestPlatformDetection(unittest.TestCase):
    def test_is_probably_url(self):
        self.assertTrue(is_probably_url("https://www.youtube.com/watch?v=123"))
        self.assertTrue(is_probably_url("http://facebook.com/reel/456"))
        self.assertTrue(is_probably_url("  https://vm.tiktok.com/ZM8x/  "))
        self.assertFalse(is_probably_url("not a url"))
        self.assertFalse(is_probably_url("ftp://server/file"))
        self.assertFalse(is_probably_url(""))

    def test_parse_youtube_url(self):
        # Standard video
        res = parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(res.is_youtube)
        self.assertEqual(res.video_id, "dQw4w9WgXcQ")
        self.assertIsNone(res.playlist_id)
        self.assertFalse(res.has_playlist)
        self.assertTrue(res.has_video)

        # Short link
        res = parse_youtube_url("https://youtu.be/dQw4w9WgXcQ?t=10")
        self.assertTrue(res.is_youtube)
        self.assertEqual(res.video_id, "dQw4w9WgXcQ")
        self.assertIsNone(res.playlist_id)

        # Shorts
        res = parse_youtube_url("https://www.youtube.com/shorts/abc987xyz")
        self.assertTrue(res.is_youtube)
        self.assertEqual(res.video_id, "abc987xyz")
        self.assertIsNone(res.playlist_id)

        # Playlist link
        res = parse_youtube_url("https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
        self.assertTrue(res.is_youtube)
        self.assertIsNone(res.video_id)
        self.assertEqual(res.playlist_id, "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
        self.assertTrue(res.has_playlist)
        self.assertFalse(res.has_video)

        # Combo video + playlist link
        res = parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
        self.assertTrue(res.is_youtube)
        self.assertEqual(res.video_id, "dQw4w9WgXcQ")
        self.assertEqual(res.playlist_id, "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
        self.assertTrue(res.has_video)
        self.assertTrue(res.has_playlist)

    def test_detect_platform(self):
        # YouTube
        p = detect_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(p.key, "youtube")

        # Facebook
        for url in [
            "https://www.facebook.com/reel/1234567890",
            "https://fb.watch/abCdEfGhIj/",
            "https://www.facebook.com/watch/?v=987654321",
        ]:
            p = detect_platform(url)
            self.assertEqual(p.key, "facebook")

        # TikTok
        for url in [
            "https://www.tiktok.com/@user/video/7123456789012345678",
            "https://vm.tiktok.com/ZM8abcd12/",
            "https://vt.tiktok.com/ZS9876543/",
        ]:
            p = detect_platform(url)
            self.assertEqual(p.key, "tiktok")

        # Generic & Unknown
        p = detect_platform("https://vimeo.com/123456")
        self.assertEqual(p.key, "vimeo")
        p = detect_platform("not a url at all")
        self.assertEqual(p.key, "unknown")


class TestRangeParser(unittest.TestCase):
    def test_parse_item_range_single(self):
        res = parse_item_range("1", max_items=10)
        self.assertTrue(res.valid)
        self.assertEqual(res.indices, [1])

        res = parse_item_range("5", max_items=10)
        self.assertTrue(res.valid)
        self.assertEqual(res.indices, [5])

    def test_parse_item_range_sequence(self):
        res = parse_item_range("1-5", max_items=10)
        self.assertTrue(res.valid)
        self.assertEqual(res.indices, [1, 2, 3, 4, 5])

        res = parse_item_range("3 - 6", max_items=10)
        self.assertTrue(res.valid)
        self.assertEqual(res.indices, [3, 4, 5, 6])

    def test_parse_item_range_mixed_and_duplicates(self):
        res = parse_item_range("1, 3-5, 2, 4", max_items=10)
        self.assertTrue(res.valid)
        self.assertEqual(res.indices, [1, 2, 3, 4, 5])

    def test_parse_item_range_bounds_clamping(self):
        res = parse_item_range("5-15", max_items=8)
        self.assertTrue(res.valid)
        self.assertEqual(res.indices, [5, 6, 7, 8])

        # Exceeds max_items completely
        res = parse_item_range("12-20", max_items=8)
        self.assertFalse(res.valid)
        self.assertEqual(res.indices, [])

    def test_parse_item_range_invalid_tokens(self):
        res = parse_item_range("abc, foo-bar, 0, -2, 3", max_items=5)
        self.assertFalse(res.valid)  # Contains syntax/token errors
        self.assertIsNotNone(res.error)

        res = parse_item_range("", max_items=10)
        self.assertFalse(res.valid)

        res = parse_item_range("   ", max_items=10)
        self.assertFalse(res.valid)


class TestChoiceBuilder(unittest.TestCase):
    def test_build_choices_video_and_mp3(self):
        formats = [
            {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 50000000},
            {"format_id": "136", "vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 25000000},
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "filesize": 5000000},
        ]
        info = {
            "duration": 120,
            "formats": formats,
        }
        choices = build_choices(info)
        self.assertGreater(len(choices), 0)

        # Ensure 1080p and 720p choices exist
        heights = [c.height for c in choices if not c.is_audio]
        self.assertIn(1080, heights)
        self.assertIn(720, heights)

        # Check MP3 audio-only choice
        audio_choices = [c for c in choices if c.is_audio]
        self.assertEqual(len(audio_choices), 1)
        mp3_choice = audio_choices[0]
        self.assertIn("audio only", mp3_choice.label.lower())
        self.assertIn("mp3", mp3_choice.label.lower())
        self.assertTrue(mp3_choice.is_audio)
        self.assertIn("-x", mp3_choice.args)
        self.assertIn("mp3", mp3_choice.args)

    def test_build_playlist_choices(self):
        choices = build_playlist_choices()
        self.assertGreater(len(choices), 0)
        labels = [c.label.lower() for c in choices]
        self.assertTrue(any("best" in l for l in labels))
        self.assertTrue(any("1080p" in l for l in labels))
        self.assertTrue(any("720p" in l for l in labels))
        self.assertTrue(any("audio only" in l and "mp3" in l for l in labels))

    def test_score_video_format_av1_penalty(self):
        # AVC1 / H.264 format
        h264_fmt = {"format_id": "137", "vcodec": "avc1.640028", "ext": "mp4", "tbr": 2500}
        # AV1 format with higher bitrate
        av1_fmt = {"format_id": "399", "vcodec": "av01.0.08M.08", "ext": "mp4", "tbr": 3500}

        score_h264 = score_video_format(h264_fmt)
        score_av1 = score_video_format(av1_fmt)

        # H.264 must score higher than AV1 to guarantee hardware playback compatibility
        self.assertGreater(score_h264, score_av1)

    def test_build_choices_h264_args(self):
        info = {
            "duration": 60,
            "formats": [
                {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 50000000},
                {"format_id": "399", "vcodec": "av01", "acodec": "none", "height": 1080, "filesize": 60000000},
            ],
        }
        choices = build_choices(info)
        video_choice = [c for c in choices if c.height == 1080][0]
        # Verify args contain H.264/AVC priority strings
        format_arg = video_choice.args[video_choice.args.index("-f") + 1]
        self.assertIn("vcodec^=avc1", format_arg)
        self.assertIn("vcodec!*=av01", format_arg)

    def test_ensure_compatible_video_passthrough(self):
        # Non-existent or empty returns safely
        self.assertEqual(ensure_compatible_video(""), "")
        self.assertEqual(ensure_compatible_video("/path/does/not/exist.mp4"), "/path/does/not/exist.mp4")


class TestBinaryResolver(unittest.TestCase):
    def test_resolve_binaries(self):
        ytdlp = BinaryResolver.resolve_ytdlp()
        ffmpeg = BinaryResolver.resolve_ffmpeg()
        self.assertIsNotNone(ytdlp)
        self.assertTrue(os.path.exists(ytdlp) or ytdlp == "yt-dlp")
        self.assertIsNotNone(ffmpeg)
        self.assertTrue(os.path.exists(ffmpeg) or ffmpeg == "ffmpeg")


class TestUtilities(unittest.TestCase):
    def test_sanitize_filename(self):
        bad_name = 'Video: "Best" <Title> / Test? * 2026 | Part 1'
        clean = sanitize_filename(bad_name)
        for char in '<>:"/\\|?*':
            self.assertNotIn(char, clean)
        self.assertTrue(len(clean) > 0)

    def test_clean_partials(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "video.mp4")
            part_file = os.path.join(tmpdir, "video.mp4.part")
            ytdl_file = os.path.join(tmpdir, "video.mp4.ytdl")
            with open(test_file, "w") as f:
                f.write("real")
            with open(part_file, "w") as f:
                f.write("part")
            with open(ytdl_file, "w") as f:
                f.write("ytdl")

            clean_partials(test_file)
            self.assertTrue(os.path.exists(test_file))
            self.assertFalse(os.path.exists(part_file))
            self.assertFalse(os.path.exists(ytdl_file))


class TestGUIComponents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_target_dialog_selection(self):
        dialog = YouTubeTargetDialog(parent=None)
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.choice, "video")

        # Choose playlist
        dialog._choose_playlist()
        self.assertEqual(dialog.choice, "playlist")

    def test_queue_item_widget_open_button(self):
        widget = DownloadQueueItemWidget(task_id=1, title="Test Video Title", ep_label="Ep 1")
        self.assertTrue(widget.btn_open.isHidden())

        # Update to completed
        widget.set_completed("/path/to/video.mp4")
        self.assertFalse(widget.btn_open.isHidden())
        self.assertEqual(widget.dest_path, "/path/to/video.mp4")


if __name__ == "__main__":
    unittest.main()
