"""
Self-contained DramaBox bypass manager for the standalone ZIP project.
"""

import logging
import re
from typing import Optional

try:
    from .base import decode_url, extract_chapter_suffix
    from .api_bypass import ApiBypass
    from .cache_bypass import CacheBypass
    from .jsonld_bypass import JsonLdBypass
    from .mp4_bypass import Mp4Bypass
    from .nextdata_bypass import NextDataBypass
    from .probe_bypass import ProbeBypass
    from .script_bypass import ScriptBypass
except ImportError:
    from base import decode_url, extract_chapter_suffix
    from api_bypass import ApiBypass
    from cache_bypass import CacheBypass
    from jsonld_bypass import JsonLdBypass
    from mp4_bypass import Mp4Bypass
    from nextdata_bypass import NextDataBypass
    from probe_bypass import ProbeBypass
    from script_bypass import ScriptBypass

_log = logging.getLogger("dramabox.bypass")

HLS_HOST = "https://hwzthls.dramaboxdb.com"


class DramaBoxBypassManager:
    def __init__(self, status_callback=None, hls_host: str = ""):
        self._report = status_callback if status_callback else (lambda *args, **kwargs: None)
        self._hls_host = hls_host if hls_host else HLS_HOST

        self.api = ApiBypass(status_callback=self._report)
        self.jsonld = JsonLdBypass(status_callback=self._report)
        self.mp4 = Mp4Bypass(status_callback=self._report)
        self.nextdata = NextDataBypass(status_callback=self._report)
        self.script = ScriptBypass(status_callback=self._report)
        self.cache = CacheBypass(status_callback=self._report)
        self.probe = ProbeBypass(status_callback=self._report)

        self._strategies = [
            self.api,
            self.jsonld,
            self.mp4,
            self.nextdata,
            self.script,
            self.cache,
        ]

    def build_bypass_url(self, ep_id: str, html: str) -> Optional[str]:
        if not ep_id:
            return None

        auth_params = ""
        book_path = ""
        chapter_suffix = "2"
        sources = []

        for strategy in self._strategies:
            try:
                result = strategy.attempt(ep_id, html)
                if result is None:
                    continue

                if not auth_params and result.auth_params:
                    auth_params = result.auth_params
                    sources.append(f"{strategy.name}(auth)")

                if not book_path and result.book_path:
                    book_path = result.book_path
                    chapter_suffix = result.chapter_suffix
                    sources.append(f"{strategy.name}(path)")

                if auth_params and book_path:
                    break
            except Exception as exc:
                _log.debug("[Manager] Strategy %s error: %s", strategy.name, exc)

        if auth_params and book_path:
            for raw in re.findall(r'https://hwz\w+\.dramaboxdb\.com/[^\s"\'\\>]+', html):
                decoded = decode_url(re.sub(r'[;,\)\]\}"\\]+$', "", raw))
                if ep_id in decoded:
                    ep_suffix = extract_chapter_suffix(decoded)
                    if ep_suffix and ep_suffix != chapter_suffix:
                        _log.debug(
                            "[Manager] Correcting suffix: %r -> %r (from ep_id=%s own URL)",
                            chapter_suffix,
                            ep_suffix,
                            ep_id,
                        )
                        chapter_suffix = ep_suffix
                        break

            self.cache.update(auth_params=auth_params, book_path=book_path)

            cdn_hash = ep_id[-2:][::-1]
            seg_base = f"{self._hls_host}/{cdn_hash}/{book_path}/{ep_id}_{chapter_suffix}/m3u8"
            seg_url = f"segments://{seg_base}|{ep_id}|{auth_params}"
            source_str = " + ".join(sources)

            try:
                verified = self.probe.validate_bypass(
                    ep_id,
                    auth_params,
                    book_path,
                    self._hls_host,
                    chapter_suffix,
                )
                if verified:
                    self._report(f"Bypass URL built + verified (ep={ep_id}) via [{source_str}]")
                else:
                    self._report(f"Bypass URL built (ep={ep_id}) via [{source_str}] - unverified")
            except Exception:
                self._report(f"Bypass URL built (ep={ep_id}) via [{source_str}]")

            return seg_url

        self._report(f"Bypass failed: auth={'YES' if auth_params else 'NO'}, bookPath={'YES' if book_path else 'NO'}")
        return None

    def is_locked(self, html: str) -> bool:
        return self.jsonld.detect_locked(html)

    def get_free_url(self, html: str, ep_id: str) -> Optional[str]:
        try:
            url = self.jsonld.get_free_url(html, ep_id)
            if url:
                self._report("Video URL found via JSON-LD")
                return url
        except Exception as exc:
            _log.debug("[Manager] JSON-LD free_url error: %s", exc)

        try:
            url = self.mp4.get_direct_mp4(html, ep_id)
            if url:
                self._report("Video URL found via MP4 (direct download)")
                return url
        except Exception as exc:
            _log.debug("[Manager] MP4 free_url error: %s", exc)

        try:
            url = self.api.get_fresh_video_url(ep_id, html)
            if url:
                self._report("Video URL found via API (fresh token)")
                return url
        except Exception as exc:
            _log.debug("[Manager] API free_url error: %s", exc)

        try:
            url = self.script.find_ep_specific_url(html, ep_id)
            if url:
                self._report("Video URL found via Script scan")
                return url
        except Exception as exc:
            _log.debug("[Manager] Script free_url error: %s", exc)

        return None

    def find_matching_url(self, html: str, ep_id: str) -> Optional[str]:
        url = self.nextdata.find_matching_url(html, ep_id)
        if url:
            self._report("Video URL found via __NEXT_DATA__ (chapterId match)")
        return url

    def harvest_m3u8_cache(self, html: str) -> dict:
        return self.nextdata.harvest_m3u8_cache(html)

    def update_cache(self, auth_params: str = "", book_path: str = ""):
        self.cache.update(auth_params=auth_params, book_path=book_path)
