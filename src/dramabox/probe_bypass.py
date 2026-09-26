"""
Bypass Strategy — CDN Probe (direct segment probing)
=====================================================
Probes the CDN directly to verify that bypass-constructed URLs
actually work before attempting a full download.

When other strategies provide auth_params + book_path, this strategy
validates them by making a HEAD request to the first segment.
If the segment returns 200, the bypass URL is confirmed valid.

This can also be used independently:
  - Try alternate CDN hosts (hwzthls, thwzthls, etc.)
  - Try different auth parameter combinations
  - Try both /m3u8/ and non-m3u8 segment paths
  - Discover working CDN patterns by probing known structures

Priority: LOW (validation + fallback probing)
"""

import re
import logging
import requests
from typing import Optional, Tuple

try:
    from .base import (
        BaseBypass,
        BypassResult,
        decode_url,
        extract_auth,
        extract_book_path,
    )
except ImportError:
    from base import (
        BaseBypass,
        BypassResult,
        decode_url,
        extract_auth,
        extract_book_path,
    )

_log = logging.getLogger("dramabox.bypass")

CDN_HOSTS = [
    "hwzthls.dramaboxdb.com",
    "thwzthls.dramaboxdb.com",
    "hwzthls2.dramaboxdb.com",
]

SEGMENT_PATTERNS = [
    "{host}/{hash}/{bp}/{eid}_{sfx}/m3u8/{eid}.720p-00001.ts",
    "{host}/{hash}/{bp}/{eid}_{sfx}/{eid}.720p-00001.ts",
    "{host}/{hash}/{bp}/{eid}_{sfx}/m3u8/{eid}.480p-00001.ts",
]


class ProbeBypass(BaseBypass):
    """Probe CDN to validate and discover working segment URLs."""

    name = "Probe"

    def __init__(self, status_callback=None):
        super().__init__(status_callback)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.dramaboxdb.com/",
        })
        self._verified_host = ""
        self._verified_pattern = ""

    def attempt(self, ep_id: str, html: str) -> Optional[BypassResult]:
        return None

    def validate_bypass(
        self,
        ep_id: str,
        auth_params: str,
        book_path: str,
        hls_host: str = "",
        chapter_suffix: str = "2",
    ) -> bool:
        if not ep_id or not auth_params or not book_path:
            return False

        cdn_hash = ep_id[-2:][::-1]
        if hls_host:
            host = hls_host.replace("https://", "").replace("http://", "")
        else:
            host = CDN_HOSTS[0]

        for pattern in SEGMENT_PATTERNS:
            url = "https://" + pattern.format(
                host=host,
                hash=cdn_hash,
                bp=book_path,
                eid=ep_id,
                sfx=chapter_suffix,
            )
            url += f"?{auth_params}"
            try:
                r = self._session.head(url, timeout=8)
                if r.status_code == 200:
                    self._verified_host = host
                    self._verified_pattern = pattern
                    self._log_debug(f"Validated: {url[:100]}")
                    return True
            except Exception:
                pass
        return False

    def probe_cdn(
        self,
        ep_id: str,
        auth_params: str,
        book_path: str,
        chapter_suffix: str = "2",
    ) -> Optional[str]:
        if not ep_id or not auth_params or not book_path:
            return None

        cdn_hash = ep_id[-2:][::-1]

        for host in CDN_HOSTS:
            for pattern in SEGMENT_PATTERNS:
                url = "https://" + pattern.format(
                    host=host,
                    hash=cdn_hash,
                    bp=book_path,
                    eid=ep_id,
                    sfx=chapter_suffix,
                )
                url += f"?{auth_params}"
                try:
                    r = self._session.head(url, timeout=6)
                    if r.status_code == 200:
                        self._verified_host = host
                        self._verified_pattern = pattern
                        self._log_status(f"✅ [Probe] CDN found: {host}")
                        base = pattern.rsplit("/", 1)[0]
                        base_url = "https://" + base.format(
                            host=host,
                            hash=cdn_hash,
                            bp=book_path,
                            eid=ep_id,
                        )
                        return base_url
                except Exception:
                    pass

        self._log_debug("No working CDN pattern found")
        return None

    def discover_book_path(
        self,
        ep_id: str,
        auth_params: str,
        known_book_prefix: str = "",
    ) -> Optional[str]:
        return None

    def get_segment_count(
        self,
        base_url: str,
        ep_id: str,
        auth_params: str,
    ) -> int:
        first_url = f"{base_url}/{ep_id}.720p-00001.ts?{auth_params}"
        try:
            r = self._session.head(first_url, timeout=8)
            if r.status_code != 200:
                return 0
        except Exception:
            return 0

        lo, hi = 1, 200
        while lo < hi:
            mid = (lo + hi + 1) // 2
            seg_url = f"{base_url}/{ep_id}.720p-{mid:05d}.ts?{auth_params}"
            try:
                r = self._session.head(seg_url, timeout=6)
                if r.status_code == 200:
                    lo = mid
                else:
                    hi = mid - 1
            except Exception:
                hi = mid - 1

        return lo
