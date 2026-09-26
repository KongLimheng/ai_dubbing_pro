# -*- coding: utf-8 -*-
"""
Unified SekaiDrama API Client for Multi-Platform Short Drama Extraction.
Covers DramaBox, ReelShort, NetShort, FlickReels, FreeReels, Melolo, ShortMax, GoodShort, and PineDrama.
Reverse-engineered from Sansekai/SekaiDrama.
"""

import base64
import hashlib
import html
import json
import logging
import os
import random
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_log = logging.getLogger("sekai.api")

DEFAULT_API_BASE = os.environ.get(
    "SEKAI_API_BASE",
    "https://api.sansekai.my.id/api",
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://api.sansekai.my.id/",
    "Sec-CH-UA": '"Chromium";v="153", "Not?A_Brand";v="8"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Linux"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def generate_client_ip() -> str:
    """Generate realistic residential/client IP to bypass datacenter IP blacklists."""
    first = random.choice([103, 114, 118, 125, 180, 202, 222])
    return f"{first}.{random.randint(10, 240)}.{random.randint(1, 250)}.{random.randint(1, 250)}"

SEKAI_KEYS = [
    b"LO-NGAPAIN-KONTOL-GAK-MODAL-SCRAP-PUNYA-ORANG-LO-KONTOL",
    b"Sansekai-SekaiDrama",
]


def decrypt_sekai_payload(ciphertext_b64: str) -> Any:
    """Decrypt CryptoJS AES ciphertext (OpenSSL format Salted__)."""
    try:
        raw = base64.b64decode(ciphertext_b64)
    except Exception as exc:
        _log.debug("Base64 decode failed for payload: %s", exc)
        return ciphertext_b64

    if not raw.startswith(b"Salted__") or len(raw) < 16:
        return ciphertext_b64

    salt = raw[8:16]
    encrypted = raw[16:]

    for password in SEKAI_KEYS:
        try:
            d = b""
            d_i = b""
            while len(d) < 48:
                d_i = hashlib.md5(d_i + password + salt).digest()
                d += d_i
            key = d[:32]
            iv = d[32:48]

            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted) + decryptor.finalize()
            pad = decrypted[-1]
            if 1 <= pad <= 16:
                plain = decrypted[:-pad].decode("utf-8")
            else:
                plain = decrypted.decode("utf-8")
            return json.loads(plain)
        except Exception:
            continue

    _log.warning("Failed to decrypt Sekai payload with known keys")
    return ciphertext_b64


def extract_chrome_cf_clearance(domain: str = ".sansekai.my.id") -> Optional[str]:
    """
    Extract decrypted cf_clearance cookie for the given domain from local Google Chrome/Chromium.
    Supports Linux (GNOME Keyring / secretstorage / peanuts) and Windows/macOS.
    """
    # 1. Linux & macOS targets
    browser_targets = [
        ("chrome", os.path.expanduser("~/.config/google-chrome/Default/Cookies")),
        ("chromium", os.path.expanduser("~/.config/chromium/Default/Cookies")),
        ("brave", os.path.expanduser("~/.config/BraveSoftware/Brave-Browser/Default/Cookies")),
        ("chrome", os.path.expanduser("~/Library/Application Support/Google/Chrome/Default/Cookies")),
    ]

    # 2. Windows targets
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            browser_targets.extend([
                ("chrome", os.path.join(local_app_data, "Google", "Chrome", "User Data", "Default", "Network", "Cookies")),
                ("chrome", os.path.join(local_app_data, "Google", "Chrome", "User Data", "Default", "Cookies")),
            ])

    for app_name, cookie_path in browser_targets:
        if not os.path.exists(cookie_path):
            continue
        try:
            conn = sqlite3.connect(f"file:{cookie_path}?immutable=1", uri=True)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT name, value, encrypted_value FROM cookies WHERE host_key LIKE ? AND name = "cf_clearance"',
                (f"%{domain.lstrip('.')}%",),
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                continue
            name, plain_val, enc_val = row
            if plain_val:
                return plain_val
            if not enc_val:
                continue

            # Linux Decryption
            if os.name != "nt":
                secret = None
                try:
                    import secretstorage

                    bus = secretstorage.dbus_init()
                    collection = secretstorage.get_default_collection(bus)
                    for item in collection.get_all_items():
                        attrs = item.get_attributes()
                        if attrs.get("application") == app_name:
                            secret = item.get_secret()
                            break
                except Exception:
                    pass

                if not secret:
                    try:
                        import subprocess
                        cmd = [
                            "/usr/bin/python3",
                            "-c",
                            "import secretstorage, sys\n"
                            "bus = secretstorage.dbus_init()\n"
                            "col = secretstorage.get_default_collection(bus)\n"
                            f"for item in col.get_all_items():\n"
                            f"    if item.get_attributes().get('application') == '{app_name}':\n"
                            "        sys.stdout.buffer.write(item.get_secret()); break\n",
                        ]
                        res = subprocess.run(cmd, capture_output=True, timeout=3)
                        if res.returncode == 0 and res.stdout:
                            secret = res.stdout
                    except Exception:
                        pass

                if not secret:
                    secret = b"peanuts"

                key = hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1, 16)
                iv = b" " * 16
                prefix = enc_val[:3]
                data = enc_val[3:]
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(data) + decryptor.finalize()
                pad = decrypted[-1]
                if 1 <= pad <= 16:
                    decrypted = decrypted[:-pad]
                if prefix == b"v11" and len(decrypted) > 32:
                    cookie_str = decrypted[32:].decode("utf-8", errors="replace")
                else:
                    cookie_str = decrypted.decode("utf-8", errors="replace")
                if cookie_str and not any(ord(c) < 32 and c not in "\r\n\t" for c in cookie_str[:20]):
                    return cookie_str.strip()

            # Windows Decryption via DPAPI
            elif os.name == "nt":
                try:
                    import ctypes
                    import ctypes.wintypes

                    class DATA_BLOB(ctypes.Structure):
                        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

                    p = ctypes.create_string_buffer(enc_val[3:])
                    blob_in = DATA_BLOB(len(enc_val) - 3, ctypes.cast(p, ctypes.POINTER(ctypes.c_char)))
                    blob_out = DATA_BLOB()
                    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                        return decrypted.decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
        except Exception as exc:
            _log.debug("Cookie extraction error from %s: %s", cookie_path, exc)
            continue
    return None


class SekaiDramaAPI:
    """API client interacting with SekaiDrama upstream services."""

    def __init__(self, api_base: str = "", cf_clearance: str = "", status_callback=None):
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self._report = status_callback if status_callback else (lambda *args, **kwargs: None)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cf_clearance:
            self.set_cf_clearance(cf_clearance)

    def set_cf_clearance(self, cookie_val: str):
        val = cookie_val.strip() if cookie_val else ""
        if val:
            self.session.cookies.set("cf_clearance", val, domain=".sansekai.my.id")
            _log.debug("cf_clearance cookie attached to session.")

    def set_api_base(self, api_base: str):
        if api_base:
            self.api_base = api_base.strip().rstrip("/")
            self._log_status(f"API Base updated to: {self.api_base}")

    def set_proxy(self, proxy_url: str):
        proxy = proxy_url.strip() if proxy_url else ""
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
            self._log_status(f"API Proxy set to: {proxy}")
        else:
            self.session.proxies = {}

    def _log_status(self, message: str):
        self._report(message)

    def _get_json(self, endpoint: str, params: Optional[dict] = None, timeout: int = 15, retries: int = 2) -> Any:
        url = f"{self.api_base}{endpoint}"
        last_exc = None
        for attempt in range(retries + 1):
            client_ip = generate_client_ip()
            req_headers = {
                "X-Forwarded-For": client_ip,
                "Client-IP": client_ip,
                "X-Real-IP": client_ip,
                "Referer": "https://api.sansekai.my.id/",
            }
            try:
                resp = self.session.get(url, params=params, headers=req_headers, timeout=timeout)
                if resp.status_code == 403:
                    resp_text = resp.text
                    if any(x in resp_text.lower() for x in ["just a moment", "challenge", "turnstile", "<html"]):
                        raise RuntimeError(
                            "Cloudflare Turnstile challenge active (403). "
                            "Please open https://api.sansekai.my.id/ in Chrome, then click 'Auto-Import from Chrome' "
                            "in Downloader Settings (⚙️) to bypass."
                        )
                    if attempt < retries:
                        time.sleep(0.5)
                        continue
                    try:
                        err_msg = resp.json().get("message", "403 Forbidden")
                    except Exception:
                        err_msg = resp_text[:200]
                    raise RuntimeError(
                        f"SekaiDrama API Forbidden (403): Upstream IP blacklist active ({err_msg}). "
                        "Configure an API mirror, proxy, or Chrome clearance cookie in settings to bypass."
                    )
                if resp.status_code == 429:
                    if attempt < retries:
                        time.sleep(0.8)
                        continue
                    raise RuntimeError("SekaiDrama API Rate Limited (429): Too many requests. Try again later or use a proxy.")
                resp.raise_for_status()

                data = resp.json()
                if isinstance(data, dict) and data.get("data") and isinstance(data["data"], str):
                    if data["data"].startswith("U2FsdGVkX1"):
                        decrypted = decrypt_sekai_payload(data["data"])
                        return decrypted
                return data
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                _log.debug("API request failed: %s (%s)", url, exc)
                raise
        if last_exc:
            raise last_exc

    # ─────────────────────────────────────────────────────────────
    # 1. DramaBox
    # ─────────────────────────────────────────────────────────────
    def get_dramabox_info(self, book_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[DramaBox API] Fetching drama metadata for ID {book_id}...")
        detail = self._get_json(f"/dramabox/detail", params={"bookId": book_id})
        title = "DramaBox Series"
        thumbnail = ""
        if isinstance(detail, dict):
            book = detail.get("data", {}).get("book", {}) if "data" in detail else detail
            title = book.get("bookName") or title
            thumbnail = book.get("cover") or book.get("coverWap") or ""

        ep_data = self._get_json(f"/dramabox/get-allepisode", params={"bookId": book_id})
        raw_list = ep_data if isinstance(ep_data, list) else ep_data.get("data", [])
        episodes = []
        for idx, item in enumerate(raw_list):
            if not isinstance(item, dict):
                continue
            cid = str(item.get("chapterId") or item.get("id") or idx + 1)
            name = item.get("chapterName") or f"Episode {idx + 1}"
            cdn_list = item.get("cdnList", [])
            video_url = ""
            if cdn_list and isinstance(cdn_list, list):
                default_cdn = next((c for c in cdn_list if c.get("isDefault") == 1), cdn_list[0])
                vpaths = default_cdn.get("videoPathList", [])
                if vpaths:
                    def_v = next((v for v in vpaths if v.get("isDefault") == 1), vpaths[0])
                    raw_path = def_v.get("videoPath", "")
                    if raw_path:
                        video_url = f"{self.api_base}/dramabox/decrypt-video?url={quote(raw_path, safe='')}"
            episodes.append({
                "id": cid,
                "num": idx + 1,
                "title": name,
                "url": video_url,
                "locked": bool(item.get("isCharge") or item.get("chargeChapter")),
                "platform": "DramaBox",
            })
        return title, episodes, thumbnail

    # ─────────────────────────────────────────────────────────────
    # 2. NetShort
    # ─────────────────────────────────────────────────────────────
    def get_netshort_info(self, short_play_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[NetShort API] Fetching drama metadata for ID {short_play_id}...")
        detail = self._get_json("/netshort/detail", params={"shortPlayId": short_play_id})
        title = "NetShort Series"
        thumbnail = ""
        total_episodes = 0
        if isinstance(detail, dict):
            title = detail.get("shortPlayName") or detail.get("title") or title
            thumbnail = detail.get("cover") or ""
            total_episodes = int(detail.get("totalEpisodes") or detail.get("chapterCount") or 0)

        if not total_episodes:
            total_episodes = 50  # sensible fallback

        episodes = []
        for ep_num in range(1, total_episodes + 1):
            episodes.append({
                "id": f"{short_play_id}_{ep_num}",
                "num": ep_num,
                "title": f"Episode {ep_num} - {title}",
                "url": "",  # lazily resolved via get_netshort_stream
                "locked": False,
                "platform": "NetShort",
                "short_play_id": short_play_id,
            })
        return title, episodes, thumbnail

    def get_netshort_stream(self, short_play_id: str, episode_num: int) -> Optional[str]:
        data = self._get_json("/netshort/get-episode", params={
            "shortPlayId": short_play_id,
            "episodeNumber": episode_num,
        })
        if isinstance(data, dict):
            ep_list = data.get("episodeList", [])
            if ep_list:
                ep = ep_list[0]
                return ep.get("playVoucher") or ep.get("playVoucherBak")
            ep = data.get("episode", {})
            return ep.get("videoUrl") or ep.get("playVoucher") or ep.get("playVoucherBak")
        return None

    # ─────────────────────────────────────────────────────────────
    # 3. ShortMax
    # ─────────────────────────────────────────────────────────────
    def get_shortmax_info(self, short_play_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[ShortMax API] Fetching drama metadata for ID {short_play_id}...")
        detail = self._get_json("/shortmax/detail", params={"shortPlayId": short_play_id})
        title = "ShortMax Series"
        thumbnail = ""
        total_episodes = 0
        if isinstance(detail, dict):
            title = detail.get("title") or detail.get("name") or detail.get("shortPlayName") or title
            thumbnail = detail.get("cover") or ""
            total_episodes = int(detail.get("totalEpisodes") or detail.get("chapterCount") or 0)

        if not total_episodes:
            total_episodes = 50

        episodes = []
        for ep_num in range(1, total_episodes + 1):
            episodes.append({
                "id": f"{short_play_id}_{ep_num}",
                "num": ep_num,
                "title": f"Episode {ep_num} - {title}",
                "url": "",
                "locked": False,
                "platform": "ShortMax",
                "short_play_id": short_play_id,
            })
        return title, episodes, thumbnail

    def get_shortmax_stream(self, short_play_id: str, episode_num: int) -> Optional[str]:
        data = self._get_json("/shortmax/get-episode", params={
            "shortPlayId": short_play_id,
            "episodeNumber": episode_num,
        })
        if isinstance(data, dict):
            ep = data.get("episode", {})
            video_url = ep.get("videoUrl", {})
            if isinstance(video_url, dict):
                # prioritize 720p -> 1080p -> 480p
                return video_url.get("video_720") or video_url.get("video_1080") or video_url.get("video_480") or next(iter(video_url.values()), None)
            if isinstance(video_url, str):
                return video_url
        return None

    # ─────────────────────────────────────────────────────────────
    # 4. FlickReels
    # ─────────────────────────────────────────────────────────────
    def get_flickreels_info(self, playlet_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[FlickReels API] Fetching drama metadata for ID {playlet_id}...")
        detail = self._get_json("/flickreels/detail", params={"playlet_id": playlet_id})
        title = "FlickReels Series"
        thumbnail = ""
        episodes = []
        if isinstance(detail, dict):
            root = detail.get("data", {}) if "data" in detail and isinstance(detail.get("data"), dict) else detail
            drama = root.get("drama", {}) if isinstance(root.get("drama"), dict) else root
            title = drama.get("title") or drama.get("playlet_title") or drama.get("name") or title
            thumbnail = drama.get("cover") or drama.get("vertical_cover") or ""
            raw_eps = root.get("episodes") or drama.get("episodes") or []
            if raw_eps and isinstance(raw_eps, list):
                for idx, ep in enumerate(raw_eps, start=1):
                    if isinstance(ep, dict):
                        cid = str(ep.get("chapter_id") or ep.get("id") or idx)
                        ep_name = ep.get("chapter_title") or ep.get("title") or f"Episode {idx}"
                    else:
                        cid = str(idx)
                        ep_name = f"Episode {idx}"
                    episodes.append({
                        "id": f"{playlet_id}_{cid}",
                        "num": idx,
                        "title": f"{ep_name} - {title}",
                        "url": "",
                        "locked": False,
                        "platform": "FlickReels",
                        "playlet_id": playlet_id,
                    })
            if not episodes:
                total_episodes = int(drama.get("totalEpisodes") or drama.get("chapter_num") or drama.get("total_chapters") or 50)
                for ep_num in range(1, total_episodes + 1):
                    episodes.append({
                        "id": f"{playlet_id}_{ep_num}",
                        "num": ep_num,
                        "title": f"Episode {ep_num} - {title}",
                        "url": "",
                        "locked": False,
                        "platform": "FlickReels",
                        "playlet_id": playlet_id,
                    })
        return title, episodes, thumbnail

    def get_flickreels_stream(self, playlet_id: str, episode_num: int) -> Optional[str]:
        data = self._get_json("/flickreels/get-episode", params={
            "playlet_id": playlet_id,
            "episodeNumber": episode_num,
        })
        if isinstance(data, dict):
            ep = data.get("data", {}) if "data" in data and isinstance(data.get("data"), dict) else data
            return ep.get("hls_url") or ep.get("hlsUrl") or ep.get("video_url") or ep.get("url")
        return None

    # ─────────────────────────────────────────────────────────────
    # 5. FreeReels
    # ─────────────────────────────────────────────────────────────
    def get_freereels_info(self, key: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[FreeReels API] Fetching drama and all episodes for key {key}...")
        data = self._get_json("/freereels/detailAndAllEpisode", params={"key": key})
        title = "FreeReels Series"
        thumbnail = ""
        episodes = []

        root = data.get("data", {}) if isinstance(data, dict) and "data" in data else (data or {})
        info = root.get("info", {}) if isinstance(root.get("info"), dict) else root
        title = info.get("name") or info.get("title") or root.get("title") or title
        thumbnail = info.get("cover") or root.get("cover") or ""

        # Check for episode list
        raw_episodes = (
            info.get("episode_list")
            or info.get("episodes")
            or root.get("episode_list")
            or root.get("episodes")
            or root.get("items")
            or []
        )
        for idx, ep in enumerate(raw_episodes, start=1):
            if not isinstance(ep, dict):
                continue
            cid = str(ep.get("id") or ep.get("key") or ep.get("episode_id") or idx)
            ep_title = ep.get("name") or ep.get("title") or f"Episode {idx}"
            v_url = (
                ep.get("external_audio_h264_m3u8")
                or ep.get("m3u8_url")
                or ep.get("external_audio_h265_m3u8")
                or ep.get("video_url")
                or ep.get("url")
                or ep.get("play_url")
                or ""
            )
            episodes.append({
                "id": cid,
                "num": idx,
                "title": f"{ep_title} - {title}",
                "url": v_url,
                "locked": False,
                "platform": "FreeReels",
            })
        return title, episodes, thumbnail

    # ─────────────────────────────────────────────────────────────
    # 6. Melolo
    # ─────────────────────────────────────────────────────────────
    def get_melolo_info(self, book_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[Melolo API] Fetching drama metadata for ID {book_id}...")
        detail = self._get_json("/melolo/detail", params={"book_id": book_id})
        title = "Melolo Series"
        thumbnail = ""
        episodes = []

        data = detail.get("data", {}) if isinstance(detail, dict) and "data" in detail else (detail or {})
        video_data = data.get("video_data", {}) if isinstance(data.get("video_data"), dict) else {}
        book = data.get("book", {}) if isinstance(data.get("book"), dict) else {}

        title = video_data.get("series_title") or book.get("book_name") or data.get("title") or title
        thumbnail = video_data.get("series_cover") or book.get("thumb_url") or data.get("cover") or ""

        video_list = video_data.get("video_list") or data.get("video_list") or data.get("videos") or []
        for idx, vid in enumerate(video_list, start=1):
            if not isinstance(vid, dict):
                continue
            vid_id = str(vid.get("vid") or vid.get("id") or idx)
            vid_title = vid.get("title") or vid.get("name") or f"Episode {idx}"
            episodes.append({
                "id": vid_id,
                "num": idx,
                "title": f"{vid_title} - {title}",
                "url": "",  # resolved via get_melolo_stream
                "locked": False,
                "platform": "Melolo",
                "video_id": vid_id,
            })
        return title, episodes, thumbnail

    def get_melolo_stream(self, video_id: str) -> Optional[str]:
        data = self._get_json("/melolo/get-episode", params={"videoId": video_id})
        if isinstance(data, dict):
            # Direct streamUrl or qualities list
            for k in ("streamUrl", "url", "main_url", "backupUrl"):
                if data.get(k):
                    return str(data[k])
            qualities = data.get("qualities") or data.get("video_qualities") or []
            if qualities and isinstance(qualities, list):
                q0 = qualities[0]
                return q0.get("streamUrl") or q0.get("url") or q0.get("main_url")
        return None

    # ─────────────────────────────────────────────────────────────
    # 7. GoodShort
    # ─────────────────────────────────────────────────────────────
    def get_goodshort_info(self, book_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[GoodShort API] Fetching drama metadata for ID {book_id}...")
        allep = self._get_json("/goodshort/get-allepisode", params={"bookId": book_id})
        title = "GoodShort Series"
        thumbnail = ""
        episodes = []

        data = allep.get("data", {}) if isinstance(allep, dict) and "data" in allep else (allep or {})
        if isinstance(data, dict):
            title = data.get("bookName") or data.get("title") or title
            thumbnail = data.get("bookCover") or data.get("cover") or ""
            raw_list = data.get("downloadList") or data.get("chapterList") or []
        elif isinstance(data, list):
            raw_list = data
        else:
            raw_list = []

        for idx, item in enumerate(raw_list, start=1):
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or item.get("chapterId") or idx)
            name = item.get("chapterName") or f"Episode {idx}"
            stream_url = ""
            videos = item.get("multiVideos", [])
            if isinstance(videos, list) and videos:
                v1080 = next((v.get("filePath") for v in videos if isinstance(v, dict) and v.get("type") == "1080p"), "")
                v720 = next((v.get("filePath") for v in videos if isinstance(v, dict) and v.get("type") == "720p"), "")
                stream_url = v1080 or v720 or (videos[0].get("filePath") if isinstance(videos[0], dict) else "")
            if not stream_url:
                stream_url = item.get("filePath") or item.get("url") or ""

            episodes.append({
                "id": cid,
                "num": idx,
                "title": f"{name} - {title}",
                "url": stream_url,
                "locked": False,
                "platform": "GoodShort",
            })
        return title, episodes, thumbnail

    # ─────────────────────────────────────────────────────────────
    # 8. PineDrama
    # ─────────────────────────────────────────────────────────────
    def get_pinedrama_info(self, collection_id: str) -> Tuple[str, List[dict], str]:
        self._log_status(f"[PineDrama API] Fetching drama metadata for ID {collection_id}...")
        detail = self._get_json("/pinedrama/detail", params={"collection_id": collection_id})
        title = "PineDrama Series"
        thumbnail = ""
        total_episodes = 0
        if isinstance(detail, dict):
            data = detail.get("data", {}) if "data" in detail and isinstance(detail.get("data"), dict) else detail
            if "collection" in data and isinstance(data["collection"], dict):
                data = data["collection"]
            title = data.get("title") or data.get("collection_title") or title
            covers = data.get("cover_urls", [])
            if covers and isinstance(covers, list):
                thumbnail = str(covers[0])
            else:
                thumbnail = data.get("cover") or data.get("cover_url") or ""
            total_episodes = int(data.get("total_episodes") or data.get("episode_count") or 0)

        if not total_episodes:
            total_episodes = 50

        episodes = []
        for ep_num in range(1, total_episodes + 1):
            episodes.append({
                "id": f"{collection_id}_{ep_num}",
                "num": ep_num,
                "title": f"Episode {ep_num} - {title}",
                "url": "",
                "locked": False,
                "platform": "PineDrama",
                "collection_id": collection_id,
            })
        return title, episodes, thumbnail

    def get_pinedrama_stream(self, collection_id: str, episode_num: int) -> Optional[str]:
        data = None
        try:
            data = self._get_json("/pinedrama/get-episode", params={
                "collection_id": collection_id,
                "episodeNumber": episode_num,
            })
        except Exception as exc:
            _log.debug("PineDrama get-episode fetch failed: %s", exc)
            return None

        if isinstance(data, dict):
            for k in ("best_url", "url", "video_url", "stream_url"):
                if data.get(k):
                    return str(data[k])
            main = data.get("main", {})
            if isinstance(main, dict):
                indo_hd = main.get("indo_hd_cdn_urls", [])
                if indo_hd and isinstance(indo_hd, list):
                    return str(indo_hd[0])
                indo = main.get("indo_cdn_urls", [])
                if indo and isinstance(indo, list):
                    return str(indo[0])
        return None

    def search_pinedrama(self, query: str) -> List[dict]:
        self._log_status(f"[PineDrama API] Searching for '{query}'...")
        res = self._get_json("/pinedrama/search", params={"query": query})
        items = []
        raw_list = res.get("data", []) if isinstance(res, dict) and "data" in res else (res if isinstance(res, list) else [])
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("collection_id") or item.get("id") or "")
            if not cid:
                continue
            title = item.get("title") or item.get("name") or "Unknown"
            covers = item.get("cover_urls", [])
            cover = covers[0] if (covers and isinstance(covers, list)) else (item.get("cover") or "")
            items.append({
                "id": cid,
                "title": title,
                "cover": cover,
                "platform": "PineDrama",
                "episodes": item.get("total_episodes") or item.get("episode_count") or 0,
            })
        return items

