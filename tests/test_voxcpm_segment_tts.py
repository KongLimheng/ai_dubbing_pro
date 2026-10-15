# -*- coding: utf-8 -*-
"""
Tests for VoxCPM segment TTS generation, voice presets, and Edge-TTS fallback.
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
import utils
import core_app
import workers


class TestVoxCPMSegmentTTS(unittest.TestCase):
    """Test suite for VoxCPM segment TTS features and voice presets."""

    def test_builtin_voices_defined(self):
        """Verify built-in VoxCPM voice options list is defined and non-empty."""
        self.assertTrue(len(voxcpm_support.VOXCPM_BUILTIN_VOICES) >= 6)
        voice_ids = [v[1] for v in voxcpm_support.VOXCPM_BUILTIN_VOICES]
        self.assertIn("voxcpm:female:normal", voice_ids)
        self.assertIn("voxcpm:male:normal", voice_ids)

    def test_resolve_voice_presets(self):
        """Verify resolve_voxcpm_voice_preset resolves presets and control prompts correctly."""
        preset = voxcpm_support.resolve_voxcpm_voice_preset("voxcpm:female:normal")
        self.assertEqual(preset["role"], "female")
        self.assertEqual(preset["style"], "normal")
        self.assertIn("Khmer", preset["control_prompt"])

        male_serious = voxcpm_support.resolve_voxcpm_voice_preset("voxcpm:male:serious")
        self.assertEqual(male_serious["role"], "male")
        self.assertEqual(male_serious["style"], "serious")
        self.assertIn("authoritative", male_serious["control_prompt"].lower())

    def test_is_voxcpm_builtin_voice(self):
        """Verify is_voxcpm_builtin_voice discriminates built-in vs ref vs standard voices."""
        self.assertTrue(voxcpm_support.is_voxcpm_builtin_voice("voxcpm:female:normal"))
        self.assertTrue(voxcpm_support.is_voxcpm_builtin_voice("voxcpm2:male:excited"))
        self.assertFalse(voxcpm_support.is_voxcpm_builtin_voice("km-KH-SreymomNeural"))
        self.assertFalse(voxcpm_support.is_voxcpm_builtin_voice("voxcpm2_ref:{}"))

    def test_normalize_voice_id_preserves_voxcpm(self):
        """Verify normalize_voice_id and resolve_voice_and_pitch preserve VoxCPM voice IDs."""
        norm = utils.normalize_voice_id("voxcpm:female:normal")
        self.assertEqual(norm, "voxcpm:female:normal")

        v, p = utils.resolve_voice_and_pitch("voxcpm:female:normal", "+0Hz")
        self.assertEqual(v, "voxcpm:female:normal")
        self.assertEqual(p, "+0Hz")

    def test_batch_worker_skips_existing_cached_audio(self):
        """Verify BatchVoxCPMTTSWorker skips clips that already have valid cached audio."""
        rows = [
            {
                "row": 0,
                "text": "សួស្តី",
                "voice_id": "voxcpm:female:normal",
                "dest_path": "/fake/cache/row_0.mp3",
                "pitch": "+0Hz",
                "rate": "+0%",
            }
        ]

        worker = core_app.BatchVoxCPMTTSWorker(rows)

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("os.path.getsize", return_value=2048):
                with mock.patch("voxcpm_support.generate_voxcpm_audio") as mock_gen:
                    worker.run()
                    mock_gen.assert_not_called()

    def test_export_worker_voxcpm_fallback(self):
        """Verify ExportWorker falls back to VoxCPM2 when primary TTS fails."""
        worker = workers.ExportWorker.__new__(workers.ExportWorker)
        worker.progress = mock.MagicMock()
        worker._validate_export_clip_file = mock.MagicMock()

        orig_fn = workers._orig_export_tts_clip_with_retry

        # Primary TTS raises 403 error
        def mock_failing_orig(self, *args, **kwargs):
            raise RuntimeError("403, message='Invalid response status'")

        with mock.patch.object(workers._mod.ExportWorker, "_generate_export_tts_clip_with_retry", mock_failing_orig):
            with mock.patch("voxcpm_support.get_voxcpm_install_status", return_value={"ready": True}):
                with mock.patch("voxcpm_support.generate_voxcpm_audio") as mock_vox_gen:
                    with mock.patch("os.makedirs"):
                        with mock.patch("os.path.getsize", return_value=5000):
                            result = workers._enhanced_export_tts_clip_with_retry(
                                worker,
                                text="សួស្តី",
                                voice_id="km-KH-SreymomNeural",
                                pitch="+0Hz",
                                rate="+0%",
                                clip_file="/fake/clip_0.wav",
                                clip_label="clip 1/1"
                            )
                            self.assertTrue(result.get("used_voxcpm"))
                            self.assertTrue(result.get("used_fallback"))
                            mock_vox_gen.assert_called_once()

    def test_batch_dialog_voxcpm_options_and_apply_all(self):
        """Verify EnhancedBatchSrtMappingDialog populates VoxCPM options and bulk apply works."""
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        dlg = core_app.EnhancedBatchSrtMappingDialog(["/fake/vid1.mp4", "/fake/vid2.mp4"])

        # Check bulk combo contains VoxCPM voices
        idx = dlg.bulk_voice_combo.findData("voxcpm:female:normal")
        self.assertTrue(idx >= 0, "voxcpm:female:normal missing from bulk_voice_combo")

        # Check row 0 combo contains VoxCPM voices
        row_combo = dlg.table.cellWidget(0, 3)
        self.assertIsNotNone(row_combo)
        self.assertTrue(row_combo.findData("voxcpm:male:normal") >= 0)

        # Apply to all rows
        dlg.bulk_voice_combo.setCurrentIndex(idx)
        dlg.apply_voice_to_all_rows()
        self.assertEqual(dlg.voice_assignments.get("/fake/vid1.mp4"), "voxcpm:female:normal")
        self.assertEqual(dlg.voice_assignments.get("/fake/vid2.mp4"), "voxcpm:female:normal")

        # Check jobs
        jobs = dlg.get_jobs()
        self.assertEqual(len(jobs), 2)
        for j in jobs:
            self.assertEqual(j["voice_id"], "voxcpm:female:normal")

    def test_batch_dialog_voice_labels_and_summary_badge(self):
        """Verify get_voice_label and summary badge formatting for VoxCPM voices."""
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        dlg = core_app.EnhancedBatchSrtMappingDialog(["/fake/vid1.mp4"])

        lbl = dlg.get_voice_label("voxcpm:female:normal")
        self.assertIn("VoxCPM2", lbl)
        self.assertIn("Female", lbl)

        # Assign VoxCPM voice and verify summary pill
        dlg.voice_assignments["/fake/vid1.mp4"] = "voxcpm:female:normal"
        dlg._refresh_assignment_cells()
        summary = dlg.summary_label.text()
        self.assertIn("<b>VoxCPM</b> 1", summary)

    def test_batch_job_item_voxcpm_tts_engine(self):
        """Verify BatchJobItem marks tts_engine as VoxCPM for VoxCPM jobs."""
        from batch_processor import BatchJobItem
        raw_job = {
            "video_path": "/fake/video.mp4",
            "voice_id": "voxcpm:male:serious",
        }
        item = BatchJobItem(1, raw_job, "/fake/out")
        self.assertEqual(item.voice_id, "voxcpm:male:serious")
        self.assertEqual(item.tts_engine, "VoxCPM")


if __name__ == "__main__":
    unittest.main()

