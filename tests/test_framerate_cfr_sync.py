# -*- coding: utf-8 -*-
"""
Test CFR frame rate preservation in VideoSpeedAdjustWorker and ExportWorker.
Verifies that speed-adjusted video segments and exported videos maintain
exact constant frame rate (e.g. 30.00 fps) with 0 packet timestamp jumps.
"""

import os
import sys
import json
import unittest
import tempfile
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt5.QtCore import QCoreApplication
import workers
from workers import (
    build_facebook_video_encoder_args,
    probe_video_dimensions,
    compute_target_dimensions,
    VideoSpeedAdjustWorker,
)


class TestFramerateCFRSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QCoreApplication.instance():
            cls.app = QCoreApplication(sys.argv)
        else:
            cls.app = QCoreApplication.instance()

    def test_build_facebook_video_encoder_args_fps(self):
        """Test that build_facebook_video_encoder_args injects -r {fps} when provided."""
        args_with_fps = build_facebook_video_encoder_args(
            video_encoder="cpu", target_w=1280, target_h=720, fps=30.0
        )
        self.assertIn("-r", args_with_fps)
        r_idx = args_with_fps.index("-r")
        self.assertEqual(args_with_fps[r_idx + 1], "30")

        args_nvenc_fps = build_facebook_video_encoder_args(
            video_encoder="nvenc", target_w=1080, target_h=1920, fps=29.97
        )
        self.assertIn("-r", args_nvenc_fps)
        self.assertIn("29.97", args_nvenc_fps)

    def test_video_speed_adjust_cfr_30fps(self):
        """
        Run VideoSpeedAdjustWorker on a test video with multiple speed-adjusted segments.
        Verify that the output video stream has r_frame_rate == 30/1, avg_frame_rate == 30/1,
        and 0 packet jumps.
        """
        source_video = "/home/heng/Downloads/DramaBox/My pet is the greate emperor/Episode 3 - Peliharaanku kaisar agung.mp4"
        if not os.path.exists(source_video):
            self.skipTest(f"Source video not found: {source_video}")

        # Simulate 4 segments with varying speed factors (including gap segments)
        segments_data = [
            {"row": 0, "start": 7.5, "end": 9.8, "speed_factor": 0.82, "target_duration": 2.80},
            {"row": 1, "start": 11.5, "end": 14.2, "speed_factor": 0.98, "target_duration": 2.75},
            {"row": 2, "start": 14.5, "end": 18.2, "speed_factor": 0.89, "target_duration": 4.15},
        ]

        worker = VideoSpeedAdjustWorker(
            video_path=source_video,
            segments_with_audio_duration=segments_data
        )
        worker.video_quality = "source"  # Keep source resolution to speed up test
        worker.compress_enabled = True

        result_video = [None]
        error_msg = [None]
        timeline = [None]

        def on_finished(path):
            result_video[0] = path
            cls_app = QCoreApplication.instance()
            if cls_app:
                cls_app.quit()

        def on_error(err):
            error_msg[0] = str(err)
            cls_app = QCoreApplication.instance()
            if cls_app:
                cls_app.quit()

        def on_timeline(data):
            timeline[0] = list(data) if data else []

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.timeline_updated.connect(on_timeline)

        worker.start()
        self.app.exec_()

        self.assertIsNone(error_msg[0], f"Worker error: {error_msg[0]}")
        self.assertIsNotNone(result_video[0], "Worker did not return output video")
        self.assertTrue(os.path.exists(result_video[0]), f"Output file missing: {result_video[0]}")
        self.assertGreater(len(timeline[0] or []), 0, "Timeline was not updated")

        try:
            # Probe frame rate
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate,avg_frame_rate,duration,nb_frames",
                "-of", "json", result_video[0]
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe = json.loads(res.stdout)["streams"][0]

            self.assertEqual(probe["r_frame_rate"], "30/1", f"r_frame_rate expected 30/1, got {probe['r_frame_rate']}")
            self.assertEqual(probe["avg_frame_rate"], "30/1", f"avg_frame_rate expected 30/1, got {probe['avg_frame_rate']}")

            # Verify packet timestamps have 0 jumps (strictly constant frame rate 3000 ticks)
            cmd_pkts = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "packet=pts", "-of", "json", result_video[0]
            ]
            res_pkts = subprocess.run(cmd_pkts, capture_output=True, text=True, check=True)
            pkts = json.loads(res_pkts.stdout).get("packets", [])
            sorted_pts = sorted([int(p["pts"]) for p in pkts if "pts" in p])

            jumps = []
            for i in range(1, len(sorted_pts)):
                diff = sorted_pts[i] - sorted_pts[i - 1]
                if diff != 3000:
                    jumps.append((i, sorted_pts[i - 1], sorted_pts[i], diff))

            self.assertEqual(len(jumps), 0, f"Expected 0 packet timestamp jumps, found {len(jumps)}: {jumps[:5]}")

            # Verify speed-adjusted video contains audio stream (for Demucs vocal removal)
            cmd_a = [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_type,codec_name",
                "-of", "json", result_video[0]
            ]
            res_a = subprocess.run(cmd_a, capture_output=True, text=True, check=True)
            streams_a = json.loads(res_a.stdout).get("streams", [])
            self.assertGreater(len(streams_a), 0, "Expected audio stream in speed-adjusted video")
            self.assertEqual(streams_a[0]["codec_type"], "audio")

            # Verify audio extraction succeeds (as ExportWorker does for Demucs)
            extracted_mp3 = result_video[0] + ".extracted.mp3"
            try:
                ext_cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", result_video[0],
                    "-vn", "-acodec", "libmp3lame", "-b:a", "192k",
                    extracted_mp3
                ]
                ext_res = subprocess.run(ext_cmd, capture_output=True, text=True)
                self.assertEqual(ext_res.returncode, 0, f"Audio extraction failed: {ext_res.stderr}")
                self.assertTrue(os.path.exists(extracted_mp3) and os.path.getsize(extracted_mp3) > 0, "Extracted MP3 is empty or missing")
            finally:
                if os.path.exists(extracted_mp3):
                    try:
                        os.remove(extracted_mp3)
                    except Exception:
                        pass
        finally:
            if result_video[0] and os.path.exists(result_video[0]):
                try:
                    os.remove(result_video[0])
                except Exception:
                    pass

    def test_export_worker_audio_extraction_fallback(self):
        """
        Verify that ExportWorker fallback redirects audio extraction from an audio-less
        edited_video to the original source video.
        """
        source_video = "/home/heng/Downloads/DramaBox/My pet is the greate emperor/Episode 3 - Peliharaanku kaisar agung.mp4"
        if not os.path.exists(source_video):
            self.skipTest(f"Source video not found: {source_video}")

        with tempfile.TemporaryDirectory() as td:
            # Create a silent/audio-less video
            audioless_video = os.path.join(td, "silent.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
                "-c:v", "libx264", "-an",
                audioless_video
            ], check=True)

            worker = workers.ExportWorker(
                table_data=[],
                original_video=source_video,
                output_path=os.path.join(td, "out.mp4"),
                edited_video=audioless_video,
                remove_vocal_on_export=True,
                use_demucs=True
            )

            # Test command interception
            target_mp3 = os.path.join(td, "extracted_original.mp3")
            cmd = [
                "ffmpeg", "-y", "-i", worker.original_video,
                "-vn", "-acodec", "libmp3lame", "-b:a", "192k",
                target_mp3
            ]

            # In ExportWorker.__init__, worker.original_video was set to audioless_video
            self.assertEqual(worker.original_video, audioless_video)
            self.assertEqual(worker.actual_source_video, source_video)

            # Running via _run_command will trigger the intercept
            res = worker._run_command(cmd, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(target_mp3))
            self.assertGreater(os.path.getsize(target_mp3), 0)


if __name__ == "__main__":
    unittest.main()
