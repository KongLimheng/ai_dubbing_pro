import html
import json
import os
import re
import sys
from urllib.parse import unquote, urljoin, urlparse
import requests

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VENDOR_ROOT = os.path.join(PROJECT_ROOT, "vendor")
MANAGED_SCHEME = "ytdlp://"

if os.path.isdir(os.path.join(VENDOR_ROOT, "yt_dlp")) and VENDOR_ROOT not in sys.path:
    sys.path.insert(0, VENDOR_ROOT)

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None
except Exception:
    YoutubeDL = None


class _SilentLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def _extract_json_ld_content_url(page_html: str) -> str:
    if not page_html:
        return ""
    match = re.search(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        page_html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return ""

    try:
        payload = json.loads(match.group(1))
    except Exception:
        return ""

    if not isinstance(payload, dict):
        return ""

    content_url = html.unescape(str(payload.get("contentUrl", ""))).strip()
    if content_url.startswith("//"):
        return "https:" + content_url
    return content_url


class PortableVideoSupport:
    def __init__(self, session=None, status_callback=None, progress_callback=None, ffmpeg_finder=None):
        self.session = session if session else requests.Session()
        self._report = status_callback if status_callback else (lambda msg: None)
        self._progress = progress_callback if progress_callback else (lambda value: None)
        self._ffmpeg_finder = ffmpeg_finder if ffmpeg_finder else (lambda: "")

    @property
    def available(self) -> bool:
        return YoutubeDL is not None

    def build_managed_url(self, url: str) -> str:
        clean = str(url or "").strip()
        if not clean:
            return ""
        if clean.startswith(MANAGED_SCHEME):
            return clean
        return f"{MANAGED_SCHEME}{clean}"

    def unwrap_managed_url(self, url: str) -> str:
        clean = str(url or "").strip()
        if clean.startswith(MANAGED_SCHEME):
            return clean[len(MANAGED_SCHEME):]
        return clean

    def can_handle(self, url: str) -> bool:
        clean = self.unwrap_managed_url(url)
        if not clean:
            return False
        host = urlparse(clean).netloc.lower()
        return any(
            domain in host
            for domain in (
                "youtube.com",
                "youtu.be",
                "facebook.com",
                "fb.watch",
                "reelshort.com",
                "tiktok.com",
                "vm.tiktok.com",
                "vt.tiktok.com",
            )
        )

    def get_youtube_info(self, url: str) -> dict:
        return self._extract_platform_info(url, "YouTube")

    def get_facebook_info(self, url: str) -> dict:
        return self._extract_platform_info(url, "Facebook")

    def get_tiktok_info(self, url: str) -> dict:
        return self._extract_platform_info(url, "TikTok")

    def get_reelshort_info(self, url: str) -> dict:
        source_url = self.unwrap_managed_url(url)
        try:
            info = self._extract_reelshort_from_html(source_url)
            if info.get("episodes"):
                return info
        except Exception:
            pass

        try:
            info = self._extract_platform_info(source_url, "ReelShort")
            if info.get("episodes"):
                return info
        except Exception:
            pass

        return self.make_single_episode_info(source_url, "ReelShort")

    def resolve_episode_url(self, url: str) -> str:
        clean = str(url or "").strip()
        if not clean:
            return ""
        direct_url = self._extract_direct_media_url(clean)
        return direct_url if direct_url else self.build_managed_url(clean)

    def download(self, url: str, dest_path: str, label: str = "") -> str:
        if not self.available:
            raise RuntimeError("yt-dlp support is unavailable")
        source_url = self.unwrap_managed_url(url)
        if not source_url:
            raise RuntimeError("No platform URL supplied")

        target_label = label if label else "media"
        self._report(f"Downloading {target_label} with portable yt-dlp...")
        self._progress(0)

        outtmpl = os.path.splitext(dest_path)[0] + ".%(ext)s"
        opts = self._make_options(source_url, download=True)
        opts["outtmpl"] = outtmpl
        opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"
        opts["progress_hooks"] = [self._progress_hook]

        with YoutubeDL(opts) as ydl:
            result = ydl.download([source_url])
            if result != 0:
                raise RuntimeError("yt-dlp download failed")

        self._progress(100)
        return self._finalize_output(dest_path)

    def make_single_episode_info(self, url: str, platform: str, title: str = "", thumbnail: str = "") -> dict:
        source_url = self.unwrap_managed_url(url)
        final_title = str(title or platform).strip() or platform
        return {
            "title": final_title,
            "episodes": [
                {
                    "id": source_url or platform,
                    "num": 1,
                    "title": final_title,
                    "url": source_url,
                    "locked": False,
                    "resolved_url": self.build_managed_url(source_url),
                }
            ],
            "thumbnail": thumbnail or "",
        }

    def _extract_platform_info(self, url: str, platform: str) -> dict:
        if not self.available:
            raise RuntimeError("yt-dlp support is unavailable")
        source_url = self.unwrap_managed_url(url)
        self._report(f"Loading {platform} data...")

        opts = self._make_options(source_url, download=False)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source_url, download=False)

        return self._normalize_info(info, source_url, platform)

    def _normalize_info(self, info: dict, source_url: str, platform: str) -> dict:
        if not isinstance(info, dict):
            return {
                "title": platform,
                "episodes": [],
                "thumbnail": "",
            }

        title = str(
            info.get("title")
            or info.get("playlist_title")
            or info.get("uploader")
            or platform
        ).strip()
        thumbnail = self._extract_thumbnail(info)
        episodes = []
        entries = info.get("entries")

        if entries:
            for pos, entry in enumerate(entries, start=1):
                if not isinstance(entry, dict):
                    continue
                entry_url = self._entry_source_url(entry, source_url, platform)
                resolved_url = self._extract_direct_from_info(entry)
                if not resolved_url:
                    resolved_url = self.build_managed_url(entry_url or source_url)
                episodes.append({
                    "id": str(entry.get("id") or entry_url or f"{platform}_{pos}"),
                    "num": pos,
                    "title": str(entry.get("title") or f"{platform} {pos}").strip(),
                    "url": entry_url or source_url,
                    "locked": False,
                    "resolved_url": resolved_url,
                })
                if not thumbnail:
                    thumbnail = self._extract_thumbnail(entry)

            if episodes:
                return {
                    "title": title or platform,
                    "episodes": episodes,
                    "thumbnail": thumbnail or "",
                }

        resolved_url = self._extract_direct_from_info(info)
        if not resolved_url:
            resolved_url = self.build_managed_url(source_url)

        return {
            "title": title or platform,
            "episodes": [
                {
                    "id": str(info.get("id") or source_url or platform),
                    "num": 1,
                    "title": title or platform,
                    "url": self._entry_source_url(info, source_url, platform) or source_url,
                    "locked": False,
                    "resolved_url": resolved_url,
                }
            ],
            "thumbnail": thumbnail or "",
        }

    def _extract_reelshort_from_html(self, url: str) -> dict:
        source_url = self.unwrap_managed_url(url)
        page_html = self._fetch_page(source_url)
        title = self._extract_meta(page_html, "og:title") or self._extract_title(page_html) or "ReelShort"
        thumbnail = self._extract_meta(page_html, "og:image")
        all_episodes_url = self._reelshort_full_episodes_url(source_url, page_html)

        if all_episodes_url:
            all_episodes = self._extract_reelshort_all_episode_pages(
                all_episodes_url,
                page_html if self._same_page_url(source_url, all_episodes_url) else "",
            )
            if all_episodes.get("episodes"):
                if not all_episodes.get("title"):
                    all_episodes["title"] = title
                if not all_episodes.get("thumbnail"):
                    all_episodes["thumbnail"] = thumbnail
                return all_episodes

        episode_links = self._extract_episode_links(page_html, source_url)
        episodes = []
        for pos, episode_url in enumerate(episode_links, start=1):
            episode_number = self._episode_number_from_url(episode_url, pos)
            episodes.append({
                "id": episode_url,
                "num": episode_number,
                "title": f"Episode {episode_number}",
                "url": episode_url,
                "locked": False,
                "resolved_url": self.build_managed_url(episode_url),
            })

        if not episodes:
            direct_url = _extract_json_ld_content_url(page_html)
            if not direct_url:
                direct_url = self._extract_direct_media_url(source_url, page_html=page_html)
            episodes = [
                {
                    "id": source_url,
                    "num": 1,
                    "title": title,
                    "url": source_url,
                    "locked": False,
                    "resolved_url": direct_url or self.build_managed_url(source_url),
                }
            ]

        return {
            "title": title,
            "episodes": episodes,
            "thumbnail": thumbnail or "",
        }

    def _extract_reelshort_all_episode_pages(self, url: str, first_page_html: str = "") -> dict:
        base_url = self._reelshort_full_episodes_base_url(url)
        page_html = first_page_html if first_page_html else self._fetch_page(base_url)
        first_page = self._parse_reelshort_all_episodes_page(page_html, base_url)

        title = first_page.get("title") or self._extract_title(page_html) or "ReelShort"
        thumbnail = first_page.get("thumbnail") or self._extract_meta(page_html, "og:image")
        total_pages = max(1, self._safe_int(first_page.get("total_pages"), 1))
        series_slug = first_page.get("series_slug") or self._reelshort_series_slug_from_url(base_url, page_html)

        episodes = []
        seen = set()

        def add_page(page_data):
            nonlocal thumbnail
            for chapter in page_data.get("chapters", []):
                episode = self._reelshort_chapter_to_episode(chapter, base_url, series_slug, title)
                if not episode:
                    continue
                key = episode.get("id") or episode.get("url")
                if key in seen:
                    continue
                seen.add(key)
                episodes.append(episode)
                if not thumbnail:
                    thumbnail = str(chapter.get("video_pic") or "").strip()

        add_page(first_page)

        for page_number in range(2, min(total_pages, 100) + 1):
            page_url = self._reelshort_full_episodes_page_url(base_url, page_number)
            try:
                page_data = self._parse_reelshort_all_episodes_page(self._fetch_page(page_url), page_url)
            except Exception as exc:
                self._report(f"ReelShort page {page_number} fetch failed: {exc}")
                continue

            chapters = page_data.get("chapters", [])
            if not chapters:
                break
            prev_count = len(episodes)
            if not series_slug:
                series_slug = page_data.get("series_slug") or self._reelshort_series_slug_from_url(page_url)
            add_page(page_data)
            if len(episodes) == prev_count:
                break

        episodes.sort(key=lambda item: self._safe_int(item.get("num"), 1000000000))

        return {
            "title": title,
            "episodes": episodes,
            "thumbnail": thumbnail or "",
        }

    def _parse_reelshort_all_episodes_page(self, page_html: str, page_url: str) -> dict:
        next_data = self._extract_next_data(page_html)
        page_props = next_data.get("props", {}).get("pageProps", {})
        data = page_props.get("data", {}) if isinstance(page_props, dict) else {}
        if not isinstance(data, dict):
            data = {}

        chapters = data.get("chapter_list", [])
        if not isinstance(chapters, list):
            chapters = []

        title = str(data.get("book_title") or "").strip()
        thumbnail = ""

        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            serial_number = self._safe_int(chapter.get("serial_number"), -1)
            if serial_number > 0:
                thumbnail = str(chapter.get("video_pic") or "").strip()
                if thumbnail:
                    break

        total_pages = self._safe_int(data.get("totalPage") or page_props.get("totalPage"), 1)
        if total_pages <= 1:
            total = self._safe_int(data.get("total") or data.get("chapter_count"), 0)
            page_size = self._safe_int(data.get("page_size"), 0)
            if total and page_size:
                total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "title": title,
            "thumbnail": thumbnail,
            "chapters": chapters,
            "total_pages": total_pages,
            "series_slug": self._reelshort_series_slug_from_url(page_url, page_html),
        }

    def _reelshort_chapter_to_episode(self, chapter: dict, page_url: str, series_slug: str, series_title: str) -> dict:
        if not isinstance(chapter, dict):
            return {}
        serial_number = self._safe_int(chapter.get("serial_number"), -1)
        if serial_number <= 0:
            return {}

        chapter_id = str(chapter.get("chapter_id") or "").strip()
        if not chapter_id:
            return {}

        episode_url = self._reelshort_episode_url(page_url, series_slug, serial_number, chapter_id)
        title = f"Episode {serial_number}"
        clean_series_title = str(series_title or "").strip()
        if clean_series_title and clean_series_title != "ReelShort":
            title = f"{title} - {clean_series_title}"

        return {
            "id": chapter_id,
            "num": serial_number,
            "title": title,
            "url": episode_url,
            "locked": False,
            "resolved_url": "",
        }

    def _extract_next_data(self, page_html: str) -> dict:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            page_html or "",
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return {}

        raw_json = match.group(1).strip()
        for candidate in (raw_json, html.unescape(raw_json)):
            try:
                payload = json.loads(candidate)
                return payload if isinstance(payload, dict) else {}
            except Exception:
                pass
        return {}

    def _reelshort_full_episodes_url(self, url: str, page_html: str = "") -> str:
        slug = self._reelshort_series_slug_from_url(url, page_html)
        if not slug:
            return ""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return f"{origin}/full-episodes/{slug}"

    def _reelshort_full_episodes_base_url(self, url: str) -> str:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        return f"{origin}{path}"

    def _reelshort_full_episodes_page_url(self, base_url: str, page_number: int) -> str:
        clean = base_url.rstrip("/")
        if page_number <= 1:
            return clean
        return f"{clean}/{page_number}"

    def _reelshort_episode_url(self, page_url: str, series_slug: str, serial_number: int, chapter_id: str) -> str:
        parsed = urlparse(page_url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.reelshort.com"
        return f"{origin}/episodes/episode-{serial_number}-{series_slug}-{chapter_id}"

    def _reelshort_series_slug_from_url(self, url: str, page_html: str = "") -> str:
        parsed = urlparse(url or "")
        path_parts = [p for p in parsed.path.split("/") if p]

        for i, part in enumerate(path_parts):
            if part.lower() in ("full-episodes", "movie") and i + 1 < len(path_parts):
                candidate = path_parts[i + 1]
                slug_match = re.search(r"(?:episode-\d+-|trailer-)?(.+?-[0-9a-f]{24})(?:-[a-z0-9]+)?$", candidate, re.IGNORECASE)
                if slug_match:
                    return slug_match.group(1).strip("/")
                return candidate.strip("/")

        for segment in reversed(path_parts):
            slug_match = re.search(r"(?:episode-\d+-|trailer-)?(.+?-[0-9a-f]{24})(?:-[a-z0-9]+)?$", segment, re.IGNORECASE)
            if slug_match:
                return slug_match.group(1).strip("/")

        if page_html:
            for pattern in (
                r'href=["\'](/full-episodes/[^"\']+)["\']',
                r'href=["\'](/movie/[^"\']+)["\']',
            ):
                link_match = re.search(pattern, page_html, re.IGNORECASE)
                if link_match:
                    return self._reelshort_series_slug_from_url(urljoin(url, link_match.group(1)))

        return ""

    def _same_page_url(self, left: str, right: str) -> bool:
        left_parsed = urlparse(left)
        right_parsed = urlparse(right)
        return (
            left_parsed.scheme.lower() == right_parsed.scheme.lower()
            and left_parsed.netloc.lower() == right_parsed.netloc.lower()
            and left_parsed.path.rstrip("/") == right_parsed.path.rstrip("/")
        )

    def _safe_int(self, value, default: int = 0) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default

    def _fetch_page(self, url: str, timeout: int = 20) -> str:
        headers = self._default_headers(url)
        response = self.session.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text

    def _extract_direct_media_url(self, page_url: str, page_html: str = "") -> str:
        if not page_html:
            try:
                page_html = self._fetch_page(page_url)
            except Exception:
                page_html = ""
        if not page_html:
            return ""

        next_data = self._extract_next_data(page_html)
        if next_data:
            props = next_data.get("props", {}).get("pageProps", {})
            data = props.get("data", {}) if isinstance(props, dict) else {}
            if isinstance(data, dict):
                video_url = data.get("video_url")
                if video_url and str(video_url).startswith("http"):
                    return str(video_url).strip()
            chapter_list = props.get("chapterList", [])
            if isinstance(chapter_list, list):
                for ch in chapter_list:
                    if isinstance(ch, dict):
                        mp4 = ch.get("mp4")
                        if mp4 and "15s" not in str(mp4).lower():
                            return str(mp4).strip()

        url = _extract_json_ld_content_url(page_html)
        if url:
            return url

        for pattern in (
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
        ):
            m = re.search(pattern, page_html, re.IGNORECASE)
            if m:
                return m.group(1)
        return ""

    def _extract_episode_links(self, html_text: str, base_url: str) -> list:
        links = []
        seen = set()
        for raw in re.findall(
            r'href=["\']((?:/movie/|/full-episodes/|/ep/|/episode/)[^"\']+)["\']',
            html_text or "",
            re.IGNORECASE,
        ):
            full = urljoin(base_url, raw)
            if full not in seen:
                seen.add(full)
                links.append(full)
        return links

    def _episode_number_from_url(self, url: str, fallback: int = 1) -> int:
        m = re.search(r"/ep(?:isode)?[-_/](\d+)", url or "", re.IGNORECASE)
        if m:
            return self._safe_int(m.group(1), fallback)
        m2 = re.search(r"-(\d+)(?:/|$)", url or "", re.IGNORECASE)
        if m2:
            return self._safe_int(m2.group(1), fallback)
        return fallback

    def _extract_meta(self, html_text: str, property_name: str) -> str:
        match = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(property_name)}["\'][^>]+content=["\'](.*?)["\']',
            html_text or "",
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                rf'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\']{re.escape(property_name)}["\']',
                html_text or "",
                re.IGNORECASE,
            )
        if match:
            return html.unescape(match.group(1)).strip()
        return ""

    def _extract_title(self, html_text: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html_text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        title = html.unescape(match.group(1)).strip()
        title = re.sub(r"\s*[\-|]\s*ReelShort.*$", "", title, flags=re.IGNORECASE).strip()
        return title

    def _entry_source_url(self, entry: dict, source_url: str = "", platform: str = "") -> str:
        for key in ("webpage_url", "original_url", "url"):
            candidate = str(entry.get(key) or "").strip()
            if not candidate:
                continue
            if candidate.startswith("//"):
                return "https:" + candidate
            if candidate.startswith("http"):
                return candidate
            if source_url and candidate.startswith("/"):
                return urljoin(source_url, candidate)
        return ""

    def _extract_direct_from_info(self, info: dict) -> str:
        for key in ("url", "manifest_url"):
            candidate = str(info.get(key) or "").strip()
            if candidate.startswith("http") and (".m3u8" in candidate.lower() or ".mp4" in candidate.lower()):
                return candidate
        return ""

    def _extract_thumbnail(self, info: dict) -> str:
        thumbnail = str(info.get("thumbnail") or "").strip()
        if thumbnail:
            return thumbnail
        thumbs = info.get("thumbnails") or []
        if thumbs and isinstance(thumbs[-1], dict):
            return str(thumbs[-1].get("url") or "").strip()
        return ""

    def _make_options(self, url: str, download: bool = False) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "noprogress": True,
            "logger": _SilentLogger(),
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,
            "skip_download": not download,
            "windowsfilenames": False,
            "http_headers": self._default_headers(url),
        }
        ffmpeg_loc = self._ffmpeg_finder()
        if ffmpeg_loc:
            opts["ffmpeg_location"] = ffmpeg_loc
        return opts

    def _default_headers(self, url: str = "") -> dict:
        parsed = urlparse(url or "")
        referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else "https://www.dramaboxdb.com/"
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        }

    def _progress_hook(self, progress_data: dict):
        status = progress_data.get("status")
        if status == "downloading":
            total = progress_data.get("total_bytes") or progress_data.get("total_bytes_estimate") or 0
            downloaded = progress_data.get("downloaded_bytes") or 0
            if total:
                pct = min(99, int((downloaded / total) * 100))
                self._progress(pct)
        elif status == "finished":
            self._progress(100)

    def _finalize_output(self, dest_path: str) -> str:
        if os.path.exists(dest_path):
            return dest_path

        base_no_ext = os.path.splitext(dest_path)[0]
        for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3"):
            candidate = base_no_ext + ext
            if os.path.exists(candidate):
                if ext == ".mp4" and candidate != dest_path:
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    os.replace(candidate, dest_path)
                    return dest_path
                return candidate

        return dest_path
