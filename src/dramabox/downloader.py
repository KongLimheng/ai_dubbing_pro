# -*- coding: utf-8 -*-
"""
DramaBox & multi-platform video downloader support.
Ported from portable decompiled bytecode with 100% functional fidelity.
"""

import base64
import importlib.util as importlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urljoin, urlparse
import requests

try:
    from .portable_video import PortableVideoSupport
except ImportError:
    from portable_video import PortableVideoSupport

try:
    from .reelshort import ReelShortBypassManager
except ImportError:
    try:
        from reelshort import ReelShortBypassManager
    except ImportError:
        ReelShortBypassManager = None

try:
    from .shortmax_decrypt import decrypt_shortmax_segment
except ImportError:
    try:
        from shortmax_decrypt import decrypt_shortmax_segment
    except ImportError:
        decrypt_shortmax_segment = lambda b: b

try:
    from .sekai_api import SekaiDramaAPI
except ImportError:
    try:
        from sekai_api import SekaiDramaAPI
    except ImportError:
        SekaiDramaAPI = None

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.dramaboxdb.com/',
}

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_optional_class(module_name, relative_path, class_name):
    candidate_roots = [PROJECT_ROOT]
    extra_root = os.environ.get('DRAMABOX_LEGACY_ROOT', '').strip()
    if extra_root:
        candidate_roots.append(extra_root)
    for root in candidate_roots:
        file_path = os.path.join(root, relative_path)
        if not os.path.exists(file_path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                module_name, file_path)
            if not spec or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return getattr(module, class_name, None)
        except Exception:
            continue
    return None


YouTubeMixin = _load_optional_class('legacy_youtube_mixin', os.path.join(
    'platforms', 'youtube.py'), 'YouTubeMixin')
FacebookMixin = _load_optional_class('legacy_facebook_mixin', os.path.join(
    'platforms', 'facebook.py'), 'FacebookMixin')

if YouTubeMixin is None:
    class YouTubeMixin:
        pass

if FacebookMixin is None:
    class FacebookMixin:
        pass


class DramaboxDownloader(YouTubeMixin, FacebookMixin):
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    MIN_FILE_SIZE = 1024
    MIN_EPISODE_SIZE = 65536

    def __init__(self, progress_callback=None, status_callback=None):
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._cancelled = False
        self.portable_video = PortableVideoSupport(
            session=self.session,
            status_callback=self._report_status,
            progress_callback=self._report_progress,
            ffmpeg_finder=self._find_ffmpeg,
        )

    def cancel(self):
        self._cancelled = True

    def reset(self):
        self._cancelled = False

    def _report_status(self, message):
        if self.status_callback:
            self.status_callback(message)

    def _report_progress(self, value, callback=None):
        cb = callback if callback is not None else self.progress_callback
        if cb:
            cb(value)

    def _base_url_from(self, url):
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return ""

    def fetch_page(self, url, timeout=20):
        headers = dict(DEFAULT_HEADERS)
        headers['Referer'] = self._base_url_from(url) + '/'
        response = self.session.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text

    def get_youtube_info(self, url):
        if self.portable_video.available:
            try:
                return self.portable_video.get_youtube_info(url)
            except Exception as exc:
                self._report_status(
                    f"Portable YouTube extraction failed: {exc}")
        html = ''
        try:
            html = self.fetch_page(url)
        except Exception:
            self._report_status(
                'Page fetch blocked; falling back to yt-dlp for YouTube info...')
        if not hasattr(self, '_youtube_drama_info'):
            return self.portable_video.make_single_episode_info(url, 'YouTube')
        title, episodes, thumbnail = self._youtube_drama_info(
            html, url, self._base_url_from(url), 'YouTube')
        return {
            'title': title or 'YouTube',
            'episodes': episodes or [],
            'thumbnail': thumbnail or '',
        }

    def get_facebook_info(self, url):
        if self.portable_video.available:
            try:
                return self.portable_video.get_facebook_info(url)
            except Exception as exc:
                self._report_status(
                    f"Portable Facebook extraction failed: {exc}")
        html = ''
        try:
            html = self.fetch_page(url)
        except Exception:
            self._report_status(
                'Page fetch blocked; falling back to yt-dlp for Facebook info...')
        if not hasattr(self, '_facebook_drama_info'):
            return self.portable_video.make_single_episode_info(url, 'Facebook')
        title, episodes, thumbnail = self._facebook_drama_info(
            html, url, self._base_url_from(url), 'Facebook')
        return {
            'title': title or 'Facebook',
            'episodes': episodes or [],
            'thumbnail': thumbnail or '',
        }

    def get_tiktok_info(self, url):
        if self.portable_video.available:
            try:
                return self.portable_video.get_tiktok_info(url)
            except Exception as exc:
                self._report_status(
                    f"Portable TikTok extraction failed: {exc}")
        return self.portable_video.make_single_episode_info(url, 'TikTok')

    def get_reelshort_info(self, url):
        if ReelShortBypassManager:
            try:
                mgr = ReelShortBypassManager(session=self.session, status_callback=self._report_status)
                title, episodes = mgr.get_drama_info(url)
                if episodes:
                    return {
                        'title': title,
                        'episodes': episodes,
                        'thumbnail': episodes[0].get('thumbnail', '') if episodes else '',
                    }
            except Exception as exc:
                self._report_status(f"ReelShort manager extraction failed: {exc}")
        try:
            return self.portable_video.get_reelshort_info(url)
        except Exception as exc:
            self._report_status(f"Portable ReelShort extraction failed: {exc}")
        return self.portable_video.make_single_episode_info(url, 'ReelShort')

    def build_managed_platform_url(self, url):
        return self.portable_video.build_managed_url(url)

    def resolve_platform_url(self, url):
        if self.portable_video.available:
            return self.portable_video.resolve_episode_url(url)
        return str(url or '').strip()

    def _youtube_video_url(self, url):
        return self.resolve_platform_url(url)

    def _facebook_video_url(self, url):
        return self.resolve_platform_url(url)

    def _tiktok_video_url(self, url):
        return self.resolve_platform_url(url)

    def get_reelshort_video_url(self, url):
        if ReelShortBypassManager:
            try:
                mgr = ReelShortBypassManager(session=self.session, status_callback=self._report_status)
                v_url = mgr.get_video_url(url)
                if v_url:
                    return v_url
            except Exception:
                pass
        return self.resolve_platform_url(url)

    def _find_downloaded_output(self, dest_path):
        if os.path.exists(dest_path):
            return dest_path
        base_no_ext = os.path.splitext(dest_path)[0]
        for ext in ('.mp4', '.mkv', '.webm', '.mov', '.mp3', '.m4a'):
            variant = base_no_ext + ext
            if os.path.exists(variant):
                return variant
        dest_dir = os.path.dirname(dest_path) or '.'
        prefix = os.path.basename(base_no_ext)
        if os.path.isdir(dest_dir):
            for filename in os.listdir(dest_dir):
                if filename.startswith(prefix):
                    candidate = os.path.join(dest_dir, filename)
                    if os.path.isfile(candidate):
                        return candidate
        return ''

    def _looks_like_media_file(self, file_path, expect_ts=False):
        try:
            with open(file_path, 'rb') as media_file:
                head = media_file.read(8192)
        except OSError:
            return False
        if not head:
            return False
        low = head[:512].lower()
        bad_markers = (b'<html', b'<!doctype', b'<body',
                       b'{"code"', b'{"message"')
        if any(marker in low for marker in bad_markers):
            return False
        if expect_ts:
            if len(head) >= 188 and head[0] == 71:
                return True
            if len(head) >= 376 and head[188] == 71:
                return True
            return False
        return b'ftyp' in head[:128]

    def _find_ffmpeg(self):
        for name in ('ffmpeg.exe', 'ffmpeg'):
            bundled = os.path.join(PROJECT_ROOT, 'ffmpeg', name)
            if os.path.exists(bundled):
                return bundled
        return shutil.which('ffmpeg')

    def _remux_to_mp4(self, source_path, dest_path):
        ffmpeg_path = self._find_ffmpeg()
        if not ffmpeg_path:
            raise RuntimeError('ffmpeg not found')
        command = [
            ffmpeg_path,
            '-y',
            '-i',
            source_path,
            '-c',
            'copy',
            dest_path,
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            error_text = (
                result.stderr or result.stdout or '').strip().splitlines()
            raise RuntimeError(
                error_text[-1] if error_text else 'ffmpeg remux failed')

    def download_file(self, url, dest_path, label='episode', progress_callback=None, cancel_check=None, choice=None, info_json_path=None):
        if not url:
            raise RuntimeError('No media URL supplied')
        self.reset()
        dest_dir = os.path.dirname(dest_path) or '.'
        os.makedirs(dest_dir, exist_ok=True)

        if self.portable_video.can_handle(url):
            return self.portable_video.download(url, dest_path, label, choice=choice, info_json_path=info_json_path)

        if url.startswith('youtube-ytdlp://'):
            if not hasattr(self, '_youtube_download_episode'):
                raise RuntimeError('YouTube support is unavailable')
            ep_url = url.replace('youtube-ytdlp://', '', 1)
            ok = self._youtube_download_episode(ep_url, dest_path, label)
            if not ok:
                raise RuntimeError('YouTube yt-dlp download failed')
            saved_path = self._find_downloaded_output(dest_path)
            return saved_path or dest_path

        if url.startswith('facebook-ytdlp://'):
            if not hasattr(self, '_facebook_download_episode'):
                raise RuntimeError('Facebook support is unavailable')
            ep_url = url.replace('facebook-ytdlp://', '', 1)
            ok = self._facebook_download_episode(ep_url, dest_path, label)
            if not ok:
                raise RuntimeError('Facebook yt-dlp download failed')
            saved_path = self._find_downloaded_output(dest_path)
            return saved_path or dest_path

        url_lower = url.lower()
        stream_mode = (
            url.startswith('segments://')
            or 'm3u8' in url_lower
            or url.startswith('data:')
        )
        if stream_mode:
            temp_suffix = '.ts'
        else:
            temp_suffix = os.path.splitext(dest_path)[1] or '.bin'

        fd, temp_path = tempfile.mkstemp(temp_suffix, dir=dest_dir)
        os.close(fd)
        try:
            if url.startswith('segments://'):
                self._download_segments(url, temp_path, label, progress_callback=progress_callback, cancel_check=cancel_check)
            elif stream_mode:
                self._download_m3u8(url, temp_path, label, progress_callback=progress_callback, cancel_check=cancel_check)
            else:
                self._download_direct(url, temp_path, label, progress_callback=progress_callback, cancel_check=cancel_check)

            file_size = os.path.getsize(
                temp_path) if os.path.exists(temp_path) else 0
            if file_size < self.MIN_FILE_SIZE:
                raise RuntimeError(f"Download too small ({file_size} bytes)")

            if stream_mode:
                if file_size < self.MIN_EPISODE_SIZE:
                    raise RuntimeError(
                        f"Episode file too small ({file_size} bytes)")
                if not self._looks_like_media_file(temp_path, expect_ts=True):
                    raise RuntimeError(
                        'Downloaded stream is not a valid TS media file')
                try:
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    self._remux_to_mp4(temp_path, dest_path)
                    self._report_status(f"Saved MP4: {dest_path}")
                    return dest_path
                except Exception as exc:
                    fallback_path = os.path.splitext(dest_path)[0] + '.ts'
                    if os.path.exists(fallback_path):
                        os.remove(fallback_path)
                    shutil.move(temp_path, fallback_path)
                    temp_path = ''
                    self._report_status(
                        f"Saved TS fallback: {fallback_path} ({exc})")
                    return fallback_path
            else:
                if file_size < self.MIN_EPISODE_SIZE:
                    raise RuntimeError(
                        f"Episode file too small ({file_size} bytes)")
                if not self._looks_like_media_file(temp_path, expect_ts=False):
                    raise RuntimeError(
                        'Downloaded file is not valid MP4 media')
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                shutil.move(temp_path, dest_path)
                temp_path = ''
                self._report_status(f"Saved MP4: {dest_path}")
                return dest_path
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _download_direct(self, url, dest_path, label='episode', progress_callback=None, cancel_check=None):
        self._report_status(f"Downloading {label}...")
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                with self.session.get(url, stream=True, timeout=30) as response:
                    response.raise_for_status()
                    content_type = (response.headers.get(
                        'Content-Type') or '').lower()
                    if any(t in content_type for t in ('text/html', 'application/json', 'text/plain')):
                        raise RuntimeError(
                            f"Non-media response: {content_type}")
                    total_size = int(response.headers.get('Content-Length', 0))
                    downloaded = 0
                    with open(dest_path, 'wb') as out_file:
                        for chunk in response.iter_content(chunk_size=65536):
                            if self._cancelled or (cancel_check and cancel_check()):
                                raise RuntimeError('Download cancelled')
                            if not chunk:
                                continue
                            out_file.write(chunk)
                            downloaded += len(chunk)
                            if total_size:
                                self._report_progress(
                                    int((downloaded / total_size) * 100), progress_callback)
                self._report_progress(100, progress_callback)
                return
            except Exception as exc:
                last_error = exc
                if self._cancelled or (cancel_check and cancel_check()):
                    raise
                if attempt < self.MAX_RETRIES:
                    self._report_status(
                        f"Retry {attempt}/{self.MAX_RETRIES} for {label}...")
                    time.sleep(self.RETRY_DELAY * attempt)
        raise RuntimeError(f"Direct download failed: {last_error}")

    def _download_segments(self, seg_url, dest_path, label='episode', progress_callback=None, cancel_check=None):
        _, payload = seg_url.split('://', 1)
        parts = payload.split('|', 2)
        if len(parts) != 3:
            raise RuntimeError('Invalid segments URL format')
        base_path, chapter_id, auth_params = parts
        if not base_path.startswith('http'):
            base_path = f"https://{base_path}"
        origin = self._base_url_from(base_path)
        headers = {
            'Referer': 'https://www.dramaboxdb.com/',
            'Origin': origin,
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        self._report_status(f"Downloading locked episode {label}...")
        segment_count = 0
        for index in range(1, 220):
            segment_name = f"{chapter_id}.720p-{index:05d}.ts"
            segment_url = f"{base_path}/{segment_name}?{auth_params}"
            try:
                probe = self.session.head(
                    segment_url, headers=headers, timeout=10)
                if probe.status_code == 200:
                    segment_count = index
                else:
                    break
            except Exception:
                break
        max_segments = segment_count or 220
        if segment_count:
            self._report_status(
                f"Downloading {segment_count} segments for {label}...")
        else:
            self._report_status(
                "Segment count unknown, downloading until the server stops...")

        total_written = 0
        with open(dest_path, 'wb') as out_file:
            for index in range(1, max_segments + 1):
                if self._cancelled or (cancel_check and cancel_check()):
                    raise RuntimeError('Download cancelled')
                segment_name = f"{chapter_id}.720p-{index:05d}.ts"
                segment_url = f"{base_path}/{segment_name}?{auth_params}"
                response = self.session.get(
                    segment_url, headers=headers, timeout=25)
                if response.status_code == 200 and response.content:
                    out_file.write(response.content)
                    total_written += len(response.content)
                    if segment_count:
                        progress = int((index / max_segments) * 100)
                    else:
                        progress = min(99, index)
                    self._report_progress(progress, progress_callback)
                else:
                    if index == 1:
                        raise RuntimeError(
                            f"First segment failed with status {response.status_code}")
                    break
        if total_written == 0:
            raise RuntimeError('Segment download produced 0 bytes')
        self._report_progress(100, progress_callback)

    def _download_m3u8(self, m3u8_url, dest_path, label='episode', progress_callback=None, cancel_check=None):
        self._report_status(f"Parsing HLS playlist for {label}...")
        request_headers = {}
        if m3u8_url.startswith('data:'):
            try:
                _, payload = m3u8_url.split(',', 1)
                if ';base64' in m3u8_url:
                    playlist = base64.b64decode(payload).decode('utf-8')
                else:
                    playlist = payload
            except Exception as exc:
                raise RuntimeError(f"Cannot decode inline playlist: {exc}")
        else:
            origin = self._base_url_from(m3u8_url)
            headers = {
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': origin + '/',
                'Origin': origin,
            }
            request_headers = headers
            response = self.session.get(m3u8_url, headers=headers, timeout=20)
            response.raise_for_status()
            playlist = response.text

        if '#EXT-X-STREAM-INF' in playlist:
            streams = re.findall(
                r'#EXT-X-STREAM-INF:.*?BANDWIDTH=(\d+).*?\r?\n([^\r\n]+)',
                playlist,
                re.IGNORECASE | re.DOTALL,
            )
            if streams:
                streams.sort(key=lambda item: int(item[0]), reverse=True)
                best_stream = streams[0][1].strip()
                return self._download_m3u8(urljoin(m3u8_url, best_stream), dest_path, label, progress_callback=progress_callback, cancel_check=cancel_check)

        segments = []
        for line in playlist.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            segments.append(line)

        if not segments:
            raise RuntimeError('No media segments found in playlist')

        total_segments = len(segments)
        self._report_status(
            f"Downloading {total_segments} HLS segments for {label}...")
        with open(dest_path, 'wb') as out_file:
            for index, segment in enumerate(segments, 1):
                if self._cancelled or (cancel_check and cancel_check()):
                    raise RuntimeError('Download cancelled')
                segment_url = urljoin(m3u8_url, segment)
                segment_headers = request_headers
                if segment_url.startswith('http'):
                    segment_origin = self._base_url_from(segment_url)
                    segment_headers = {
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': segment_origin + '/',
                        'Origin': segment_origin,
                    }
                seg_resp = self.session.get(segment_url, headers=segment_headers, timeout=25)
                seg_resp.raise_for_status()
                chunk = seg_resp.content
                if chunk and chunk.startswith(b'shortmax'):
                    chunk = decrypt_shortmax_segment(chunk)
                out_file.write(chunk)
                self._report_progress(int((index / total_segments) * 100), progress_callback)
        self._report_progress(100, progress_callback)
