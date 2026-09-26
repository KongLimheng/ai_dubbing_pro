import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class FullDetectConfig:
    sample_fps: float = 2.0
    min_face_area_ratio: float = 0.02
    require_single_face: bool = True


def _safe_progress(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if not cb:
        return
    try:
        cb(msg)
    except Exception:
        pass


def _load_haar_face_detector():
    import cv2

    cascade_path = None
    try:
        base = getattr(cv2.data, "haarcascades", None)
        if base:
            candidate = os.path.join(base, "haarcascade_frontalface_default.xml")
            if os.path.exists(candidate):
                cascade_path = candidate
    except Exception:
        cascade_path = None

    if not cascade_path or not os.path.exists(cascade_path):
        raise RuntimeError("OpenCV haarcascade_frontalface_default.xml not found.")
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise RuntimeError("Failed to load OpenCV Haar face detector.")
    return detector


def _iter_sample_times(
    start_s: float, end_s: float, sample_fps: float
) -> List[float]:
    start_s = float(start_s or 0.0)
    end_s = float(end_s or 0.0)
    if end_s <= start_s:
        return [start_s]
    duration = end_s - start_s
    if sample_fps <= 0:
        return [start_s + duration / 2]
    step = 1.0 / sample_fps
    times: List[float] = []
    t = start_s
    while t < end_s:
        times.append(t)
        t += step
        if len(times) >= 60:
            break
    if not times:
        times = [start_s + duration / 2]
    return times


def _detect_faces_on_frame(detector, frame_bgr):
    import cv2

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
    )
    if faces is None or len(faces) == 0:
        return []
    return list(faces)


def compute_visible_single_face_flags(
    video_path: str,
    segments: List[dict],
    *,
    cfg: Optional[FullDetectConfig] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> List[bool]:
    """
    Return a list of booleans (same length as segments): True if we believe exactly
    one sufficiently-large face is visible during that segment (sampled frames).
    """
    if not cfg:
        cfg = FullDetectConfig()
    import cv2

    if not video_path or not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    detector = _load_haar_face_detector()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video for Full Detect.")

    try:
        frame_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0
        frame_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0
        frame_area = max(1.0, float(frame_w * frame_h))
        min_area = frame_area * float(cfg.min_face_area_ratio)

        flags: List[bool] = []
        total = len(segments)
        for idx, seg in enumerate(segments):
            start_s = (
                seg.get("start_s", 0.0)
                if isinstance(seg, dict)
                else getattr(seg, "start_s", 0.0)
            )
            end_s = (
                seg.get("end_s", 0.0)
                if isinstance(seg, dict)
                else getattr(seg, "end_s", 0.0)
            )
            times = _iter_sample_times(start_s, end_s, cfg.sample_fps)

            saw_single_large_face = False
            max_face_count = 0
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue
                faces = _detect_faces_on_frame(detector, frame)
                large_faces = [f for f in faces if f[2] * f[3] >= min_area]
                count = len(large_faces)
                if count > max_face_count:
                    max_face_count = count
                if count == 1:
                    saw_single_large_face = True
                if count >= 2:
                    break

            visible = saw_single_large_face and (
                not cfg.require_single_face or max_face_count == 1
            )
            flags.append(bool(visible))

            if idx % 10 == 0 and total:
                _safe_progress(
                    progress, f"Full Detect: scanning faces... {idx + 1}/{total}"
                )

        visible_count = sum(1 for v in flags if v)
        try:
            _safe_progress(
                progress,
                f"Full Detect: face scan complete ({visible_count}/{total} segments single-face).",
            )
        except Exception:
            pass
        return flags
    finally:
        try:
            cap.release()
        except Exception:
            pass
