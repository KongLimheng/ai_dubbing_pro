# -*- coding: utf-8 -*-
"""
yoinks_engine.py - High-Performance Multi-Platform Video Downloader Engine.
Ported from https://github.com/KongLimheng/yoinks architecture and flow.

Supports:
- YouTube (videos, shorts, playlists, combo v+list URLs)
- TikTok (standard, vm, vt links)
- Facebook (Watch, Reels, post video links)
- Instagram, X/Twitter, Threads, Vimeo, Twitch, Reddit, and generic sites.

Features:
- Subprocess-based yt-dlp execution with auto-discovery and fallback
- Fast metadata probe with info.json caching (--load-info-json)
- Dynamic resolution options with estimated file size calculation
- High-quality Audio-Only MP3 extraction (-x --audio-format mp3)
- Multi-connection chunk downloading (-N 4)
- Precise progress telemetry: speed, ETA, percent, and part indicator
- Clean cancellation and partial file cleanup
"""

import dataclasses
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

_log = logging.getLogger("yoinks.engine")

PROGRESS_PREFIX = "YOINK|"
PROGRESS_TEMPLATE = f"{PROGRESS_PREFIX}%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s"


# ── Data Models ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class PlatformInfo:
    key: str
    label: str
    icon: str


@dataclasses.dataclass
class YouTubeUrlInfo:
    is_youtube: bool = False
    has_video: bool = False
    has_playlist: bool = False
    video_id: Optional[str] = None
    playlist_id: Optional[str] = None


@dataclasses.dataclass
class DownloadChoice:
    kind: str  # 'video' or 'audio'
    label: str
    args: List[str]
    height: Optional[int] = None
    estimated_size: Optional[int] = None
    is_audio: bool = False


@dataclasses.dataclass
class PlaylistEntry:
    id: str
    title: str
    duration: Optional[float] = None
    url: Optional[str] = None
    index: int = 1


@dataclasses.dataclass
class VideoInfo:
    title: str
    id: str
    uploader: str = ""
    duration: Optional[float] = None
    thumbnail: str = ""
    webpage_url: str = ""
    formats: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    is_playlist: bool = False
    item_count: int = 1
    entries: List[PlaylistEntry] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DownloadProgress:
    downloaded_bytes: int = 0
    total_bytes: int = 0
    percent: float = 0.0
    speed: float = 0.0  # bytes per sec
    eta: Optional[int] = None  # seconds left
    part: int = 1
    total_parts: int = 1
    item_index: Optional[int] = None
    total_items: Optional[int] = None
    item_title: Optional[str] = None
    status_text: str = ""


# ── Format & String Helpers ─────────────────────────────────────────────────

def format_bytes(bytes_count: Optional[float]) -> str:
    """Format byte count into human-readable size (e.g. 14.5 MB)."""
    if bytes_count is None or bytes_count <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(bytes_count)
    unit_idx = 0
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} B"
    return f"{val:.1f} {units[unit_idx]}"


def format_speed(bytes_per_sec: Optional[float]) -> str:
    """Format speed into human-readable rate (e.g. 3.2 MB/s)."""
    if not bytes_per_sec or bytes_per_sec <= 0:
        return ""
    return f"{format_bytes(bytes_per_sec)}/s"


def format_duration(seconds: Optional[float]) -> str:
    """Format duration into MM:SS or HH:MM:SS."""
    if seconds is None or seconds <= 0:
        return ""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_eta(seconds: Optional[int]) -> str:
    """Format ETA in seconds to friendly string (e.g. 45s left or 2m 10s left)."""
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return f"{seconds}s left"
    m = seconds // 60
    s = seconds % 60
    if m < 60:
        return f"{m}m {s}s left" if s > 0 else f"{m}m left"
    h = m // 60
    m = m % 60
    return f"{h}h {m}m left"


def sanitize_filename(filename: str, max_length: int = 80) -> str:
    """Sanitize title into safe filesystem filename."""
    if not filename:
        return "video"
    cleaned = re.sub(r'[\\/*?:"<>|]', "", filename).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned or "video"


# ── Platform Detection ──────────────────────────────────────────────────────

PLATFORM_DEFINITIONS = [
    {
        "hosts": ["youtube.com", "youtu.be", "music.youtube.com"],
        "info": PlatformInfo(key="youtube", label="YouTube", icon="▶️"),
    },
    {
        "hosts": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
        "info": PlatformInfo(key="tiktok", label="TikTok", icon="🎵"),
    },
    {
        "hosts": ["facebook.com", "fb.watch", "fb.com", "m.facebook.com"],
        "info": PlatformInfo(key="facebook", label="Facebook", icon="👥"),
    },
    {
        "hosts": ["instagram.com"],
        "info": PlatformInfo(key="instagram", label="Instagram", icon="📸"),
    },
    {
        "hosts": ["x.com", "twitter.com"],
        "info": PlatformInfo(key="x", label="X / Twitter", icon="🐦"),
    },
    {
        "hosts": ["threads.net", "threads.com"],
        "info": PlatformInfo(key="threads", label="Threads", icon="🧵"),
    },
    {
        "hosts": ["vimeo.com"],
        "info": PlatformInfo(key="vimeo", label="Vimeo", icon="🎬"),
    },
    {
        "hosts": ["twitch.tv"],
        "info": PlatformInfo(key="twitch", label="Twitch", icon="🟣"),
    },
    {
        "hosts": ["reddit.com"],
        "info": PlatformInfo(key="reddit", label="Reddit", icon="🤖"),
    },
]


def is_probably_url(input_str: str) -> bool:
    """Check if input text looks like an HTTP/HTTPS URL."""
    if not input_str or not isinstance(input_str, str):
        return False
    text = input_str.strip()
    try:
        parsed = urlparse(text)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def detect_platform(url: str) -> PlatformInfo:
    """Identify platform from URL hostname."""
    if not is_probably_url(url):
        return PlatformInfo(key="unknown", label="Unknown Site", icon="🌐")
    try:
        hostname = urlparse(url.strip()).netloc.lower()
    except Exception:
        return PlatformInfo(key="unknown", label="Unknown Site", icon="🌐")

    for entry in PLATFORM_DEFINITIONS:
        for host in entry["hosts"]:
            if hostname == host or hostname.endswith(f".{host}"):
                return entry["info"]

    return PlatformInfo(key="generic", label=hostname or "Web Video", icon="🌐")


def parse_youtube_url(input_str: str) -> YouTubeUrlInfo:
    """
    Parse YouTube URL and check for video ID, playlist ID, shorts, live, etc.
    Matches Yoinks parseYouTubeUrl logic.
    """
    try:
        u = urlparse(input_str.strip())
    except Exception:
        return YouTubeUrlInfo()

    hostname = u.netloc.lower()
    is_yt = any(
        hostname == h or hostname.endswith(f".{h}")
        for h in ("youtube.com", "youtu.be", "music.youtube.com")
    )
    if not is_yt:
        return YouTubeUrlInfo(is_youtube=False)

    video_id: Optional[str] = None
    qs = parse_qs(u.query)
    playlist_id = qs.get("list", [None])[0]

    if hostname == "youtu.be" or hostname.endswith(".youtu.be"):
        segment = u.path.lstrip("/").split("/")[0]
        if segment:
            video_id = segment
    elif u.path == "/watch":
        video_id = qs.get("v", [None])[0]
    elif u.path.startswith("/shorts/") or u.path.startswith("/live/") or u.path.startswith("/embed/"):
        parts = u.path.strip("/").split("/")
        if len(parts) >= 2:
            video_id = parts[1]

    return YouTubeUrlInfo(
        is_youtube=True,
        has_video=bool(video_id),
        has_playlist=bool(playlist_id),
        video_id=video_id,
        playlist_id=playlist_id,
    )


# ── Range Parser ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class RangeResult:
    valid: bool
    indices: List[int]
    error: Optional[str] = None


def parse_item_range(input_str: str, max_items: int) -> RangeResult:
    """
    Parse range strings like '1-5', '1, 3, 5-8' into 1-based sorted unique indices.
    Matches Yoinks range.ts.
    """
    raw = (input_str or "").strip()
    if not raw:
        return RangeResult(valid=False, indices=[], error="Empty range input")

    indices: Set[int] = set()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return RangeResult(valid=False, indices=[], error="No valid items found")

    for part in parts:
        if "-" in part:
            sub = part.split("-")
            if len(sub) != 2:
                return RangeResult(valid=False, indices=[], error=f"Invalid range syntax: '{part}'")
            try:
                start = int(sub[0].strip())
                end = int(sub[1].strip())
            except ValueError:
                return RangeResult(valid=False, indices=[], error=f"Non-numeric range values: '{part}'")

            if start < 1 or end < 1:
                return RangeResult(valid=False, indices=[], error="Episode numbers must be >= 1")
            if start > end:
                return RangeResult(valid=False, indices=[], error=f"Start cannot exceed end: '{part}'")

            clamped_end = min(end, max_items)
            for idx in range(start, clamped_end + 1):
                indices.add(idx)
        else:
            try:
                num = int(part)
            except ValueError:
                return RangeResult(valid=False, indices=[], error=f"Non-numeric episode value: '{part}'")
            if num < 1:
                return RangeResult(valid=False, indices=[], error="Episode numbers must be >= 1")
            if num <= max_items:
                indices.add(num)

    sorted_indices = sorted(indices)
    if not sorted_indices:
        return RangeResult(valid=False, indices=[], error=f"Specified indices exceed total items ({max_items})")

    return RangeResult(valid=True, indices=sorted_indices)


# ── Binary Resolution ───────────────────────────────────────────────────────

class BinaryResolver:
    """Finds or validates usable yt-dlp and ffmpeg binaries across systems."""

    _cached_ytdlp: Optional[str] = None
    _cached_ffmpeg: Optional[str] = None

    @classmethod
    def resolve_ytdlp(cls) -> Optional[str]:
        if cls._cached_ytdlp and cls._is_runnable(cls._cached_ytdlp):
            return cls._cached_ytdlp

        candidates = []

        # 1. Virtualenv bin
        venv_ytdlp = os.path.join(sys.prefix, "bin", "yt-dlp")
        if sys.platform == "win32":
            venv_ytdlp = os.path.join(sys.prefix, "Scripts", "yt-dlp.exe")
        candidates.append(venv_ytdlp)

        # 2. System PATH
        which_path = shutil.which("yt-dlp")
        if which_path:
            candidates.append(which_path)

        # 3. User local bin (~/.local/bin/yt-dlp)
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, ".local", "bin", "yt-dlp"))
        candidates.append(os.path.join(home, ".yoinks", "bin", "yt-dlp" if sys.platform != "win32" else "yt-dlp.exe"))

        # 4. Project internal / vendor directory
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates.append(os.path.join(app_dir, "_internal", "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"))
        candidates.append(os.path.join(app_dir, "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"))

        for c in candidates:
            if c and os.path.exists(c) and cls._is_runnable(c):
                cls._cached_ytdlp = c
                return c

        # 5. Check if python -m yt_dlp works
        try:
            res = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, timeout=5)
            if res.returncode == 0:
                cls._cached_ytdlp = f"{sys.executable} -m yt_dlp"
                return cls._cached_ytdlp
        except Exception:
            pass

        return None

    @classmethod
    def resolve_ffmpeg(cls) -> Optional[str]:
        if cls._cached_ffmpeg and cls._is_ffmpeg_runnable(cls._cached_ffmpeg):
            return cls._cached_ffmpeg

        # 1. System PATH
        which_ff = shutil.which("ffmpeg")
        if which_ff and cls._is_ffmpeg_runnable(which_ff):
            cls._cached_ffmpeg = which_ff
            return which_ff

        # 2. Project directory
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ff_candidates = [
            os.path.join(app_dir, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"),
            os.path.join(app_dir, "_internal", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"),
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]
        for c in ff_candidates:
            if c and os.path.exists(c) and cls._is_ffmpeg_runnable(c):
                cls._cached_ffmpeg = c
                return c

        return None

    @staticmethod
    def _is_runnable(cmd_path: str) -> bool:
        try:
            cmd = cmd_path.split() if " -m " in cmd_path else [cmd_path]
            res = subprocess.run(cmd + ["--version"], capture_output=True, timeout=5)
            return res.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _is_ffmpeg_runnable(cmd_path: str) -> bool:
        try:
            res = subprocess.run([cmd_path, "-version"], capture_output=True, timeout=5)
            return res.returncode == 0
        except Exception:
            return False


# ── Choice Builder ──────────────────────────────────────────────────────────

def score_video_format(f: Dict[str, Any]) -> int:
    """Score video format favoring higher bitrate, MP4 container, and AVC codec."""
    score = int(f.get("tbr") or 0)
    ext = (f.get("ext") or "").lower()
    if ext == "mp4":
        score += 10000
    vcodec = (f.get("vcodec") or "").lower()
    if vcodec.startswith("avc") or "h264" in vcodec:
        score += 5000
    return score


def build_choices(info: Any) -> List[DownloadChoice]:
    """
    Build dynamic quality choices from probed video formats.
    Includes resolution grouping, file size estimation, and Audio-Only MP3.
    Matches Yoinks buildChoices.
    """
    if isinstance(info, dict):
        formats = info.get("formats") or []
    else:
        formats = getattr(info, "formats", []) or []
    choices: List[DownloadChoice] = []

    # Find best audio for size calculation
    audio_only = [
        f for f in formats
        if (f.get("acodec") and f.get("acodec") != "none" and (not f.get("vcodec") or f.get("vcodec") == "none"))
    ]
    best_audio = None
    if audio_only:
        best_audio = sorted(
            audio_only,
            key=lambda a: float(a.get("abr") or a.get("tbr") or 0),
            reverse=True,
        )[0]
    audio_size = (best_audio.get("filesize") or best_audio.get("filesize_approx")) if best_audio else None

    # Filter video formats with height
    videos = [
        f for f in formats
        if f.get("vcodec") and f.get("vcodec") != "none" and f.get("height")
    ]
    heights = sorted({int(f["height"]) for f in videos if f.get("height")}, reverse=True)

    for height in heights[:8]:  # Limit to top 8 distinct heights
        candidates = [f for f in videos if int(f.get("height") or 0) == height]
        if not candidates:
            continue
        best = sorted(candidates, key=score_video_format, reverse=True)[0]
        has_muxed_audio = bool(best.get("acodec") and best.get("acodec") != "none")
        v_size = best.get("filesize") or best.get("filesize_approx") or 0
        total_size = v_size + (0 if has_muxed_audio else (audio_size or 0))
        size_label = f" · ~{format_bytes(total_size)}" if total_size > 0 else ""

        choices.append(DownloadChoice(
            kind="video",
            label=f"{height}p · mp4{size_label}",
            args=[
                "-f",
                f"bv*[height={height}]+ba/b[height={height}]/bv*[height<={height}]+ba/b",
                "--merge-output-format",
                "mp4",
            ],
            height=height,
            estimated_size=total_size if total_size > 0 else None,
            is_audio=False,
        ))

    if not choices:
        choices.append(DownloadChoice(
            kind="video",
            label="best available · mp4",
            args=["-f", "bv*+ba/b", "--merge-output-format", "mp4"],
            height=1080,
            is_audio=False,
        ))

    # Add Audio-Only MP3
    audio_size_label = f" · ~{format_bytes(audio_size)}" if audio_size else ""
    choices.append(DownloadChoice(
        kind="audio",
        label=f"audio only · mp3{audio_size_label}",
        args=["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"],
        estimated_size=audio_size,
        is_audio=True,
    ))

    return choices


def build_playlist_choices() -> List[DownloadChoice]:
    """
    Standard choices for playlists where individual formats vary across videos.
    Matches Yoinks buildPlaylistChoices.
    """
    return [
        DownloadChoice(
            kind="video",
            label="best quality · mp4",
            args=["-f", "bv*+ba/b", "--merge-output-format", "mp4"],
            height=2160,
            is_audio=False,
        ),
        DownloadChoice(
            kind="video",
            label="1080p max · mp4",
            args=["-f", "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b", "--merge-output-format", "mp4"],
            height=1080,
            is_audio=False,
        ),
        DownloadChoice(
            kind="video",
            label="720p max · mp4",
            args=["-f", "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b", "--merge-output-format", "mp4"],
            height=720,
            is_audio=False,
        ),
        DownloadChoice(
            kind="video",
            label="480p max · mp4",
            args=["-f", "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b", "--merge-output-format", "mp4"],
            height=480,
            is_audio=False,
        ),
        DownloadChoice(
            kind="audio",
            label="audio only · mp3",
            args=["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"],
            is_audio=True,
        ),
    ]


# ── Probing Engine ──────────────────────────────────────────────────────────

@dataclasses.dataclass
class VideoProbeResult:
    info: VideoInfo
    info_json_path: Optional[str] = None
    choices: List[DownloadChoice] = dataclasses.field(default_factory=list)


def probe_video(url: str, cancel_check: Optional[Callable[[], bool]] = None) -> VideoProbeResult:
    """
    Fast video metadata probe using yt-dlp -J.
    Saves JSON output to a temporary file for fast reuse with --load-info-json.
    """
    ytdlp = BinaryResolver.resolve_ytdlp()
    if not ytdlp:
        raise RuntimeError("yt-dlp executable not found. Please install or configure yt-dlp.")

    cmd = (ytdlp.split() if " -m " in ytdlp else [ytdlp]) + [
        "-J",
        "--no-playlist",
        "--no-warnings",
        url,
    ]

    ffmpeg = BinaryResolver.resolve_ffmpeg()
    if ffmpeg:
        cmd.extend(["--ffmpeg-location", ffmpeg])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stdout_data, stderr_data = "", ""
    start_t = time.time()
    try:
        while True:
            if cancel_check and cancel_check():
                proc.kill()
                proc.communicate()
                raise RuntimeError("Probing cancelled by user")
            try:
                stdout_data, stderr_data = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if time.time() - start_t > 60:
                    proc.kill()
                    proc.communicate()
                    raise RuntimeError("Probing timed out after 60 seconds")
    except Exception:
        proc.kill()
        raise

    if proc.returncode != 0:
        err_msg = (stderr_data or stdout_data or "").strip()
        clean_err = err_msg.splitlines()[-1] if err_msg else f"yt-dlp exited with code {proc.returncode}"
        raise RuntimeError(clean_err)

    try:
        raw = json.loads(stdout_data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse yt-dlp metadata JSON: {e}")

    # Save to temp file for --load-info-json
    info_json_path = os.path.join(
        tempfile.gettempdir(),
        f"yoinks-info-{os.getpid()}-{int(time.time() * 1000)}.json",
    )
    try:
        with open(info_json_path, "w", encoding="utf-8") as f:
            f.write(stdout_data)
    except Exception:
        info_json_path = None

    thumbnail = raw.get("thumbnail") or ""
    if not thumbnail and raw.get("thumbnails"):
        thumbnail = str(raw["thumbnails"][-1].get("url") or "")

    video_info = VideoInfo(
        title=str(raw.get("title") or "Video").strip(),
        id=str(raw.get("id") or ""),
        uploader=str(raw.get("uploader") or raw.get("channel") or "").strip(),
        duration=raw.get("duration"),
        thumbnail=thumbnail,
        webpage_url=raw.get("webpage_url") or url,
        formats=raw.get("formats") or [],
        is_playlist=False,
        item_count=1,
    )
    choices = build_choices(video_info)

    return VideoProbeResult(info=video_info, info_json_path=info_json_path, choices=choices)


def probe_playlist(url: str, cancel_check: Optional[Callable[[], bool]] = None) -> VideoProbeResult:
    """
    Fast flat-playlist probe using yt-dlp -J --flat-playlist.
    Extracts playlist titles and video list instantly without loading each video's formats.
    """
    ytdlp = BinaryResolver.resolve_ytdlp()
    if not ytdlp:
        raise RuntimeError("yt-dlp executable not found. Please install or configure yt-dlp.")

    cmd = (ytdlp.split() if " -m " in ytdlp else [ytdlp]) + [
        "-J",
        "--flat-playlist",
        "--no-warnings",
        url,
    ]

    ffmpeg = BinaryResolver.resolve_ffmpeg()
    if ffmpeg:
        cmd.extend(["--ffmpeg-location", ffmpeg])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stdout_data, stderr_data = "", ""
    start_t = time.time()
    try:
        while True:
            if cancel_check and cancel_check():
                proc.kill()
                proc.communicate()
                raise RuntimeError("Playlist probing cancelled by user")
            try:
                stdout_data, stderr_data = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if time.time() - start_t > 60:
                    proc.kill()
                    proc.communicate()
                    raise RuntimeError("Playlist probing timed out after 60 seconds")
    except Exception:
        proc.kill()
        raise

    if proc.returncode != 0:
        err_msg = (stderr_data or stdout_data or "").strip()
        clean_err = err_msg.splitlines()[-1] if err_msg else f"yt-dlp exited with code {proc.returncode}"
        raise RuntimeError(clean_err)

    try:
        raw = json.loads(stdout_data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse playlist metadata JSON: {e}")

    raw_entries = raw.get("entries") or []
    entries: List[PlaylistEntry] = []
    for idx, e in enumerate(raw_entries, start=1):
        if not isinstance(e, dict):
            continue
        v_url = e.get("url") or (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else "")
        entries.append(PlaylistEntry(
            id=str(e.get("id") or f"item_{idx}"),
            title=str(e.get("title") or f"Video {idx}").strip(),
            duration=e.get("duration"),
            url=v_url,
            index=idx,
        ))

    title = str(raw.get("title") or "Playlist").strip()
    uploader = str(raw.get("uploader") or raw.get("channel") or "").strip()
    thumbnail = ""
    if raw.get("thumbnails"):
        thumbnail = str(raw["thumbnails"][-1].get("url") or "")

    info = VideoInfo(
        title=title,
        id=str(raw.get("id") or ""),
        uploader=uploader,
        thumbnail=thumbnail,
        webpage_url=raw.get("webpage_url") or url,
        formats=[],
        is_playlist=True,
        item_count=len(entries),
        entries=entries,
    )
    choices = build_playlist_choices()

    return VideoProbeResult(info=info, info_json_path=None, choices=choices)


# ── Download Engine ─────────────────────────────────────────────────────────

def clean_partials(destinations: Any):
    """Clean up partial download files (.part, .ytdl) after cancellation."""
    if isinstance(destinations, str):
        dest_list = [destinations]
    elif isinstance(destinations, (list, tuple, set)):
        dest_list = list(destinations)
    else:
        dest_list = []

    for d in dest_list:
        if not d or not isinstance(d, str):
            continue
        try:
            # Remove any matching .part or .ytdl files
            base = os.path.splitext(d)[0]
            for partial in glob.glob(f"{glob.escape(base)}*"):
                if partial.endswith((".part", ".ytdl")):
                    try:
                        os.remove(partial)
                    except Exception:
                        pass
        except Exception:
            pass


def execute_download(
    url: str,
    choice: DownloadChoice,
    output_dir: str,
    info_json_path: Optional[str] = None,
    is_playlist: bool = False,
    playlist_items: Optional[str] = None,
    item_index: Optional[int] = None,
    total_items: Optional[int] = None,
    item_title: Optional[str] = None,
    progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Execute download using yt-dlp subprocess with:
    - Multi-chunk download: -N 4
    - Standardized progress template (PROGRESS_TEMPLATE)
    - Direct audio extraction to MP3 when audio choice is selected
    - Accurate destination capture via --print after_move:FILE:%(filepath)s
    - Output filename: %(title).60s.%(ext)s or %(playlist_index)02d - %(title).60s.%(ext)s
    """
    ytdlp = BinaryResolver.resolve_ytdlp()
    if not ytdlp:
        raise RuntimeError("yt-dlp executable not found. Please install or configure yt-dlp.")

    os.makedirs(output_dir, exist_ok=True)
    ffmpeg = BinaryResolver.resolve_ffmpeg()

    out_tmpl = (
        os.path.join(output_dir, "%(playlist_index)02d - %(title).60s.%(ext)s")
        if is_playlist
        else os.path.join(output_dir, "%(title).60s.%(ext)s")
    )

    cmd = ytdlp.split() if " -m " in ytdlp else [ytdlp]

    # Use cached info.json if available to bypass re-extraction
    if info_json_path and os.path.exists(info_json_path) and not is_playlist:
        cmd.extend(["--load-info-json", info_json_path])
    else:
        cmd.append(url)

    # Choice arguments (e.g. format selection or audio extraction)
    cmd.extend(choice.args)

    # Playlist flags
    cmd.append("--yes-playlist" if is_playlist else "--no-playlist")
    if is_playlist:
        cmd.append("--ignore-errors")
        if playlist_items:
            cmd.extend(["--playlist-items", str(playlist_items)])

    # Multi-chunk performance flag
    cmd.extend(["-N", "4"])

    # Output & progress flags
    cmd.extend([
        "--no-warnings",
        "--newline",
        "--no-quiet",
        "--progress",
        "--progress-template",
        f"download:{PROGRESS_TEMPLATE}",
        "--print",
        "after_move:FILE:%(filepath)s",
        "--no-simulate",
        "-o",
        out_tmpl,
    ])

    if ffmpeg:
        cmd.extend(["--ffmpeg-location", ffmpeg])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    destinations: List[str] = []
    last_filepath = ""
    part = 1
    total_parts = 1
    last_downloaded = 0
    stderr_lines: List[str] = []

    def _to_float(v: str) -> Optional[float]:
        try:
            return float(v.strip()) if v and v.strip() != "NA" else None
        except Exception:
            return None

    def _to_int(v: str) -> Optional[int]:
        try:
            return int(float(v.strip())) if v and v.strip() != "NA" else None
        except Exception:
            return None

    try:
        while True:
            if cancel_check and cancel_check():
                proc.terminate()
                clean_partials(destinations)
                raise RuntimeError("Download cancelled by user")

            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break

            line_str = line.strip()
            if not line_str:
                continue

            if line_str.startswith(PROGRESS_PREFIX):
                fields = line_str[len(PROGRESS_PREFIX):].split("|")
                if len(fields) >= 5:
                    downloaded_b = _to_int(fields[0]) or 0
                    total_b = _to_int(fields[1]) or _to_int(fields[2]) or 0
                    speed_v = _to_float(fields[3]) or 0.0
                    eta_v = _to_int(fields[4])

                    if downloaded_b < last_downloaded:
                        part += 1
                    last_downloaded = downloaded_b

                    pct = (min(100.0, (downloaded_b / total_b * 100.0)) if total_b > 0 else 0.0)

                    status_msg = f"{format_bytes(downloaded_b)}"
                    if total_b > 0:
                        status_msg += f" / {format_bytes(total_b)}"
                    if speed_v > 0:
                        status_msg += f" • {format_speed(speed_v)}"
                    if eta_v:
                        status_msg += f" • {format_eta(eta_v)}"

                    prog = DownloadProgress(
                        downloaded_bytes=downloaded_b,
                        total_bytes=total_b,
                        percent=pct,
                        speed=speed_v,
                        eta=eta_v,
                        part=part,
                        total_parts=total_parts,
                        item_index=item_index,
                        total_items=total_items,
                        item_title=item_title,
                        status_text=status_msg,
                    )
                    if progress_callback:
                        progress_callback(prog)

            elif line_str.startswith("FILE:"):
                target = line_str[len("FILE:"):].strip()
                if target:
                    destinations.append(target)
                    last_filepath = target

            elif "Downloading 1 format(s):" in line_str:
                parts_str = line_str.split("format(s):")[1].strip()
                total_parts = max(1, len(parts_str.split("+")))

            elif line_str.startswith("[download] Destination: "):
                dest = line_str[len("[download] Destination: "):].strip()
                destinations.append(dest)

            elif "[Merger]" in line_str or "[ExtractAudio]" in line_str:
                if progress_callback:
                    progress_callback(DownloadProgress(
                        downloaded_bytes=last_downloaded,
                        total_bytes=last_downloaded,
                        percent=99.0,
                        speed=0.0,
                        status_text="Processing & Merging format with FFmpeg...",
                    ))

        returncode = proc.wait()
        if returncode != 0:
            err_output = proc.stderr.read() if proc.stderr else ""
            clean_err = err_output.strip().splitlines()[-1] if err_output else f"Exit code {returncode}"
            raise RuntimeError(f"Download failed: {clean_err}")

        # Final progress 100%
        if progress_callback:
            progress_callback(DownloadProgress(
                percent=100.0,
                status_text="Download complete",
            ))

        # Check completed destination
        if last_filepath and os.path.exists(last_filepath):
            return last_filepath
        for d in destinations:
            if os.path.exists(d):
                return d

        return output_dir
    except Exception:
        proc.kill()
        clean_partials(destinations)
        raise
