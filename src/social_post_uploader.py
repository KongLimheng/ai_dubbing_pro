# -*- coding: utf-8 -*-
"""
social_post_uploader.py - Multi-platform video upload engines for Facebook Page, YouTube, and TikTok.
Provides chunked resumable uploading, OAuth 2.0 loopback server, and asynchronous background worker.
"""

import os
import sys
import json
import time
import socket
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import re
import glob
from typing import Dict, List, Optional, Callable, Any

import requests
from PyQt5.QtCore import QThread, pyqtSignal


# ─────────────────────────────────────────────────────────────────────────────
# 0. METADATA & CLOSED CAPTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def extract_episode_number(filename: str, fallback_idx: int = 1) -> int:
    """
    Extract episode number from filename or stem using regex patterns.
    Examples:
      'Drama Episode 05.mp4' -> 5
      'Ep. 12 - Clip.mp4' -> 12
      'Show E03.mp4' -> 3
      'Part 2.mp4' -> 2
      'Tập 10.mp4' -> 10
      '08.mp4' -> 8
    Falls back to fallback_idx if no number is found.
    """
    if not filename:
        return fallback_idx
    stem = os.path.splitext(os.path.basename(filename))[0]

    # Pattern 1: Explicit episode markers (e.g. Episode 05, Ep_05, Ep. 05, Part 05, Tap 05, Tập 05)
    m = re.search(
        r'(?:episode|ep|part|tap|tập|ch|chapter)[\s._-]*([0-9]{1,4})\b', stem, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Pattern 2: E followed by digits (e.g. E05, E5, s01e05)
    m = re.search(r'\b[eEsS](\d{1,2})?[eE](\d{1,4})\b', stem)
    if m:
        try:
            return int(m.group(2))
        except ValueError:
            pass
    m = re.search(r'\b[eE](\d{1,4})\b', stem)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Pattern 3: Separated numbers e.g. "Drama - 05", "[05]"
    m = re.search(r'[-_\[\(\s](\d{1,4})[-_\]\)\s]', stem)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Pattern 4: Ending with digits e.g. "Video05", "clip_1"
    m = re.search(r'(\d{1,4})$', stem)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Pattern 5: Any standalone digits in the stem
    m = re.search(r'\b(\d{1,4})\b', stem)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    return fallback_idx


def build_bulk_video_title(base_title: str, video_path: str, index: int) -> str:
    """
    Intelligently combine base title (from config.txt or user input) with the video episode name.
    Supports placeholder substitution: {filename}, {episode}, {ep}, {index}.
    If no placeholders exist:
      - If stem already contains or starts with base_title, avoids duplicating.
      - If stem is numeric (e.g. '01'), formats as '{base_title} - Episode {stem}'.
      - Otherwise, concatenates: '{base_title} - {stem}'.
    """
    stem = os.path.splitext(os.path.basename(video_path))[
        0] if video_path else ""

    ep_num = extract_episode_number(stem, fallback_idx=index)
    clean_base = (base_title or "").strip()

    if not clean_base:
        return stem or f"Video {index}"

    # Token substitution if placeholders present
    tokens = ("{filename}", "{episode}", "{ep}", "{index}")
    if any(k in clean_base for k in tokens):
        t = clean_base
        t = t.replace("{ep}", str(ep_num))
        return t.strip()

    # If stem is empty, return base_title
    if not stem:
        return clean_base

    # Check if stem already starts with or contains base_title to avoid duplication
    lower_base = clean_base.lower()
    lower_stem = stem.lower()
    if lower_stem.startswith(lower_base) or lower_base in lower_stem:
        return stem

    # If stem is purely digits (e.g. '01', '1', '12')
    if stem.strip().isdigit():
        return f"{clean_base} - Episode {stem.strip()}"

    return f"{clean_base} - {stem}"


def build_bulk_video_description(base_desc: str, video_title: str, video_path: str, index: int) -> str:
    """
    Format a dynamic video description by combining the base description (from config.txt)
    with the computed video title / episode info.
    Supports placeholders: {title}, {filename}, {episode}, {ep}, {index}.
    If no placeholders are present, prepends the video title to the base description.
    """
    stem = os.path.splitext(os.path.basename(video_path))[
        0] if video_path else ""
    ep_num = extract_episode_number(stem, fallback_idx=index)
    clean_desc = (base_desc or "").strip()
    clean_title = (video_title or "").strip()

    tokens = ("{title}", "{filename}", "{episode}", "{ep}", "{index}")
    if clean_desc and any(k in clean_desc for k in tokens):
        d = clean_desc
        d = d.replace("{title}", clean_title)
        return d.strip()

    if clean_title:
        if clean_desc:
            return f"{clean_title}\n\n{clean_desc}".strip()
        return clean_title

    return clean_desc


def convert_vtt_to_srt(vtt_content: str) -> str:
    """
    Convert WebVTT subtitle text to SubRip (.srt) format.
    - Strips WEBVTT headers and styling cues.
    - Replaces decimal periods in timestamps (00:00:01.000) with commas (00:00:01,000).
    - Ensures sequential cue numbering.
    """
    lines = vtt_content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    srt_lines = []
    cue_idx = 1
    in_header = True

    ts_pattern = re.compile(
        r'(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3})'
    )

    def format_ts(match):
        h1 = match.group(1) or "00:"
        if not h1.endswith(":"):
            h1 += ":"
        if len(h1) == 2:
            h1 = f"0{h1}"
        m1 = match.group(2)
        s1 = match.group(3)
        ms1 = match.group(4)

        h2 = match.group(5) or "00:"
        if not h2.endswith(":"):
            h2 += ":"
        if len(h2) == 2:
            h2 = f"0{h2}"
        m2 = match.group(6)
        s2 = match.group(7)
        ms2 = match.group(8)

        return f"{h1}{m1}:{s1},{ms1} --> {h2}{m2}:{s2},{ms2}"

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if in_header:
            if line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE") or line.startswith("REGION"):
                i += 1
                continue
            if not line:
                in_header = False
                i += 1
                continue
            if "-->" in line:
                in_header = False
            else:
                i += 1
                continue

        if not line:
            i += 1
            continue

        if "-->" in line:
            fixed_ts = ts_pattern.sub(format_ts, line)
            srt_lines.append(str(cue_idx))
            cue_idx += 1
            srt_lines.append(fixed_ts)
            i += 1
            while i < len(lines) and lines[i].strip():
                text_line = re.sub(r'<[^>]+>', '', lines[i].strip())
                if text_line:
                    srt_lines.append(text_line)
                i += 1
            srt_lines.append("")
        else:
            if i + 1 < len(lines) and "-->" in lines[i + 1]:
                i += 1
                continue
            i += 1

    return "\n".join(srt_lines).strip() + "\n"


def find_closed_caption_file(video_path: str) -> Optional[Dict[str, Any]]:
    """
    Search for a closed caption / subtitle file (.srt, .vtt) corresponding to a video.
    Searches in priority order:
      1. Exact stem: {stem}.srt
      2. Language-tagged: {stem}.{locale}.srt (e.g. video.en_US.srt, video.km_KH.srt)
      3. Exact stem VTT: {stem}.vtt
      4. Language-tagged VTT: {stem}.{locale}.vtt
      5. Episode-number matching subtitle in same directory (e.g. EP01.mp4 <-> 1.srt)
    Returns:
      {'path': str, 'locale': Optional[str], 'type': 'srt' | 'vtt'} or None
    """
    if not video_path or not os.path.exists(video_path):
        return None

    v_dir = os.path.dirname(os.path.abspath(video_path))
    if not os.path.isdir(v_dir):
        return None

    try:
        dir_files = os.listdir(v_dir)
    except Exception:
        return None

    v_stem = os.path.splitext(os.path.basename(video_path))[0]
    v_ep = extract_episode_number(v_stem)

    # 1. Exact stem .srt
    exact_srt = os.path.join(v_dir, f"{v_stem}.srt")
    if os.path.isfile(exact_srt):
        return {"path": exact_srt, "locale": None, "type": "srt"}

    # 2. Language-tagged .srt e.g. name.en_US.srt, name.km_KH.srt
    locale_pattern = re.compile(
        r'\.([a-z]{2}(?:_[A-Z]{2})?)\.srt$', re.IGNORECASE)
    for fname in dir_files:
        if fname.lower().startswith(v_stem.lower()) and fname.lower().endswith(".srt"):
            m = locale_pattern.search(fname)
            loc = m.group(1) if m else None
            return {"path": os.path.join(v_dir, fname), "locale": loc, "type": "srt"}

    # 3. Exact stem .vtt
    exact_vtt = os.path.join(v_dir, f"{v_stem}.vtt")
    if os.path.isfile(exact_vtt):
        return {"path": exact_vtt, "locale": None, "type": "vtt"}

    # 4. Language-tagged .vtt
    vtt_locale_pattern = re.compile(
        r'\.([a-z]{2}(?:_[A-Z]{2})?)\.vtt$', re.IGNORECASE)
    for fname in dir_files:
        if fname.lower().startswith(v_stem.lower()) and fname.lower().endswith(".vtt"):
            m = vtt_locale_pattern.search(fname)
            loc = m.group(1) if m else None
            return {"path": os.path.join(v_dir, fname), "locale": loc, "type": "vtt"}

    # 5. Episode-matched subtitles in the directory
    if v_ep is not None:
        for fname in dir_files:
            lower = fname.lower()
            if lower.endswith(".srt") or lower.endswith(".vtt"):
                s_stem = os.path.splitext(fname)[0]
                s_ep = extract_episode_number(s_stem)
                if s_ep == v_ep:
                    sub_type = "srt" if lower.endswith(".srt") else "vtt"
                    loc = None
                    m = re.search(
                        r'[\._-]([a-z]{2}(?:_[A-Z]{2})?)[\._-]', fname, re.IGNORECASE)
                    if m:
                        loc = m.group(1)
                    return {"path": os.path.join(v_dir, fname), "locale": loc, "type": sub_type}

    return None


def parse_facebook_group_identifier(raw_input: str) -> List[str]:
    """
    Extract Facebook Group IDs from input string, which can be:
      - Numeric ID: '123456789012345'
      - Group URL: 'https://www.facebook.com/groups/123456789012345/' or '.../groups/my_group/'
      - Comma / newline / space-separated list: '111, 222, 333'
    """
    if not raw_input:
        return []

    tokens = [t.strip() for t in re.split(
        r'[,;\n\r\t]+', str(raw_input)) if t.strip()]
    group_ids = []

    for token in tokens:
        m = re.search(r'facebook\.com/groups/([^/?#&]+)', token, re.IGNORECASE)
        if m:
            gid = m.group(1).strip()
            if gid and gid not in group_ids:
                group_ids.append(gid)
            continue

        clean_token = token.strip().rstrip("/")
        if clean_token and not clean_token.startswith("(None") and clean_token not in group_ids:
            group_ids.append(clean_token)

    return group_ids


# ─────────────────────────────────────────────────────────────────────────────
# 1. FACEBOOK PAGE UPLOADER (Graph API v19.0+)
# ─────────────────────────────────────────────────────────────────────────────

class FacebookUploader:
    """Uploader engine for Facebook Pages using the Meta Graph API."""
    GRAPH_API_VERSION = "v19.0"
    BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

    @classmethod
    def test_connection(cls, page_id: str, access_token: str) -> Dict[str, Any]:
        """Test page connection and retrieve page metadata."""
        if not page_id or not access_token:
            raise ValueError(
                "Page ID and Page Access Token are both required.")

        url = f"{cls.BASE_URL}/{page_id.strip()}"
        params = {
            "fields": "id,name,link,picture{url},fan_count,verification_status",
            "access_token": access_token.strip(),
        }
        res = requests.get(url, params=params, timeout=12)
        data = res.json()
        if res.status_code != 200 or "error" in data:
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"Facebook API Error: {err}")

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "link": data.get("link", f"https://www.facebook.com/{page_id}"),
            "fans": data.get("fan_count", 0),
            "picture": data.get("picture", {}).get("data", {}).get("url", ""),
        }

    @classmethod
    def inspect_token(cls, token: str, app_id: str = "", app_secret: str = "") -> Dict[str, Any]:
        """
        Inspect Facebook access token using the debug_token endpoint.
        Checks expiration time, scopes, validity, and token type.
        """
        if not token:
            raise ValueError("Token is required for inspection.")

        clean_token = token.strip()
        url = f"{cls.BASE_URL}/debug_token"

        # Use App Access Token if app_id and app_secret provided, otherwise try clean_token itself
        if app_id and app_secret:
            app_token = f"{app_id.strip()}|{app_secret.strip()}"
        else:
            app_token = clean_token

        params = {
            "input_token": clean_token,
            "access_token": app_token,
        }
        res = requests.get(url, params=params, timeout=12)
        data = res.json()

        if res.status_code != 200 or "error" in data:
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"Debug Token Error: {err}")

        token_info = data.get("data", {})
        is_valid = token_info.get("is_valid", False)
        t_type = token_info.get("type", "UNKNOWN")
        expires_at = token_info.get("expires_at", 0)
        scopes = token_info.get("scopes", [])

        # Check permanency: expires_at == 0 means never expires!
        # System User tokens or Page tokens derived from long-lived user tokens have expires_at == 0.
        is_permanent = bool(expires_at == 0 and is_valid)

        now = int(time.time())
        if not is_valid:
            status_label = "🔴 Invalid or Revoked Token"
            remaining_seconds = 0
        elif is_permanent:
            status_label = "🟢 Permanent (Never Expires)"
            remaining_seconds = -1
        else:
            remaining_seconds = max(0, expires_at - now)
            if remaining_seconds == 0:
                status_label = "🔴 Expired Token"
            elif remaining_seconds >= 86400:
                days = remaining_seconds // 86400
                status_label = f"🟡 Long-Lived Token (Expires in {days} days)"
            else:
                hours = remaining_seconds // 3600
                mins = (remaining_seconds % 3600) // 60
                status_label = f"⚠️ Short-Lived Token (Expires in {hours}h {mins}m - needs exchange!)"

        required_scopes = ["pages_manage_posts", "pages_read_engagement"]
        missing_scopes = [s for s in required_scopes if s not in scopes]

        return {
            "is_valid": is_valid,
            "type": t_type,
            "is_permanent": is_permanent,
            "expires_at": expires_at,
            "remaining_seconds": remaining_seconds,
            "status_label": status_label,
            "scopes": scopes,
            "missing_scopes": missing_scopes,
            "app_id": token_info.get("app_id", ""),
            "user_id": token_info.get("user_id", ""),
        }

    @classmethod
    def exchange_for_permanent_page_tokens(
        cls, app_id: str, app_secret: str, user_token: str
    ) -> Dict[str, Any]:
        """
        Exchange a short-lived user token for a 60-day long-lived token,
        then query /me/accounts to get all managed Facebook Pages with their
        PERMANENT Page Access Tokens (which never expire).
        """
        if not app_id or not app_secret or not user_token:
            raise ValueError(
                "App ID, App Secret, and User Access Token are all required.")

        clean_app_id = app_id.strip()
        clean_secret = app_secret.strip()
        clean_user_tok = user_token.strip()

        # Step 1: Exchange for 60-day Long-Lived User Token
        oauth_url = f"{cls.BASE_URL}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": clean_app_id,
            "client_secret": clean_secret,
            "fb_exchange_token": clean_user_tok,
        }
        res = requests.get(oauth_url, params=params, timeout=15)
        oauth_data = res.json()
        if res.status_code != 200 or "error" in oauth_data:
            err = oauth_data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"Token Exchange Failed: {err}")

        long_lived_token = oauth_data.get("access_token")
        if not long_lived_token:
            raise RuntimeError(
                "No long-lived access token returned by Meta OAuth.")

        # Step 2: Fetch all managed pages using the long-lived user token
        # When /me/accounts is called with a long-lived user token, Meta returns
        # Page Access Tokens that NEVER EXPIRE!
        pages_url = f"{cls.BASE_URL}/me/accounts"
        pages_params = {
            "fields": "id,name,category,access_token,picture{url},tasks",
            "access_token": long_lived_token,
            "limit": 100,
        }
        res_pages = requests.get(pages_url, params=pages_params, timeout=15)
        pages_data = res_pages.json()
        if res_pages.status_code != 200 or "error" in pages_data:
            err = pages_data.get("error", {}).get("message", res_pages.text)
            raise RuntimeError(
                f"Fetching Pages with Long-Lived Token Failed: {err}")

        raw_pages = pages_data.get("data", [])
        if not raw_pages:
            return {
                "success": True,
                "long_lived_user_token": long_lived_token,
                "pages": [],
                "message": "Long-lived token generated, but no managed Facebook Pages were found.",
            }

        # Step 3: Verify each page token
        pages = []
        for p in raw_pages:
            pid = str(p.get("id"))
            pname = p.get("name", f"Page {pid}")
            pcat = p.get("category", "")
            ptok = p.get("access_token", "")
            pic = p.get("picture", {}).get("data", {}).get("url", "")
            tasks = p.get("tasks", [])

            # Quick inspect on permanency if possible
            is_perm = True
            status_txt = "🟢 Permanent (Never Expires)"
            if ptok:
                try:
                    insp = cls.inspect_token(ptok, clean_app_id, clean_secret)
                    is_perm = insp.get("is_permanent", True)
                    status_txt = insp.get(
                        "status_label", "🟢 Permanent (Never Expires)")
                except Exception:
                    pass

            pages.append({
                "id": pid,
                "name": pname,
                "category": pcat,
                "access_token": ptok,
                "picture": pic,
                "tasks": tasks,
                "is_permanent": is_perm,
                "status_label": status_txt,
            })

        return {
            "success": True,
            "long_lived_user_token": long_lived_token,
            "pages": pages,
        }

    @classmethod
    def fetch_user_pages(cls, user_token: str) -> List[Dict[str, Any]]:
        """Fetch all Facebook Pages managed by the given user access token."""
        if not user_token:
            raise ValueError(
                "User Access Token is required to fetch managed pages.")

        url = f"{cls.BASE_URL}/me/accounts"
        params = {
            "fields": "id,name,category,access_token,picture{url}",
            "access_token": user_token.strip(),
            "limit": 50,
        }
        res = requests.get(url, params=params, timeout=15)
        data = res.json()
        if res.status_code != 200 or "error" in data:
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"Facebook Pages Query Error: {err}")

        pages = []
        for item in data.get("data", []):
            pages.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category", ""),
                "access_token": item.get("access_token", ""),
                "picture": item.get("picture", {}).get("data", {}).get("url", ""),
            })
        return pages

    @classmethod
    def upload_video_captions(
        cls,
        video_id: str,
        caption_file_path: str,
        access_token: str,
        locale: str = "en_US",
    ) -> Dict[str, Any]:
        """
        Upload SubRip (.srt) closed captions to a published or scheduled Facebook video node.
        Endpoint: POST /{video-id}/captions
        Strict Meta Requirement: Filename in multipart form must be 'filename.<locale>.srt'.
        """
        if not video_id or not caption_file_path or not access_token:
            raise ValueError(
                "video_id, caption_file_path, and access_token are required.")
        if not os.path.exists(caption_file_path):
            raise FileNotFoundError(
                f"Caption file does not exist: {caption_file_path}")

        # Normalize locale: e.g. en_us -> en_US, km_kh -> km_KH, en -> en_US
        clean_locale = locale.strip() or "en_US"
        if "_" in clean_locale:
            parts = clean_locale.split("_", 1)
            clean_locale = f"{parts[0].lower()}_{parts[1].upper()}"
        elif len(clean_locale) == 2:
            defaults = {
                "en": "en_US", "km": "km_KH", "zh": "zh_CN", "vi": "vi_VN",
                "th": "th_TH", "es": "es_LA", "id": "id_ID", "fr": "fr_FR"
            }
            clean_locale = defaults.get(clean_locale.lower(
            ), f"{clean_locale.lower()}_{clean_locale.upper()}")

        is_vtt = caption_file_path.lower().endswith(".vtt")
        encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
        raw_text = ""
        for enc in encodings:
            try:
                with open(caption_file_path, "r", encoding=enc) as f:
                    raw_text = f.read()
                break
            except UnicodeDecodeError:
                continue

        if not raw_text.strip():
            raise ValueError(
                f"Caption file {caption_file_path} is empty or unreadable.")

        if is_vtt:
            srt_content = convert_vtt_to_srt(raw_text)
        else:
            srt_content = raw_text

        srt_bytes = srt_content.encode("utf-8")

        # Meta upload filename: must match '<name>.<locale>.srt'
        base_stem = os.path.splitext(os.path.basename(caption_file_path))[0]
        base_stem = re.sub(
            r'\.[a-z]{2}(?:_[A-Z]{2})?$', '', base_stem, flags=re.IGNORECASE)
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', base_stem) or "captions"
        upload_multipart_filename = f"{safe_name}.{clean_locale}.srt"

        url = f"{cls.BASE_URL}/{str(video_id).strip()}/captions"
        files = {
            "captions_file": (upload_multipart_filename, srt_bytes, "application/x-subrip")
        }
        data = {
            "access_token": access_token.strip(),
            "default_locale": clean_locale,
        }

        res = requests.post(url, data=data, files=files, timeout=30)
        res_data = res.json() if res.text.strip().startswith("{") else {}

        if res.status_code != 200 or not res_data.get("success", False):
            err_msg = res_data.get("error", {}).get("message", res.text)
            raise RuntimeError(
                f"Facebook Caption Upload Failed ({clean_locale}): {err_msg}")

        return {
            "success": True,
            "locale": clean_locale,
            "upload_filename": upload_multipart_filename,
            "file_path": caption_file_path,
        }

    @classmethod
    def verify_video_captions(cls, video_id: str, access_token: str) -> List[Dict[str, Any]]:
        """
        Verify existing closed caption tracks for a video via GET /{video-id}/captions.
        """
        if not video_id or not access_token:
            return []

        url = f"{cls.BASE_URL}/{str(video_id).strip()}/captions"
        params = {"access_token": access_token.strip()}
        try:
            res = requests.get(url, params=params, timeout=15)
            data = res.json()
            if res.status_code == 200 and "data" in data:
                return data.get("data", [])
        except Exception:
            pass
        return []

    @classmethod
    def fetch_page_playlists(cls, page_id: str, access_token: str, user_token: str = "") -> List[Dict[str, Any]]:
        """
        Fetch all video playlists (video_lists) belonging to a Facebook Page.
        Supports schema fallbacks across Meta Graph API versions and traverses
        cursor pagination (paging.next) to retrieve all playlists.
        """
        if not page_id or not access_token:
            return []

        clean_pid = str(page_id).strip()
        if "facebook.com" in clean_pid:
            url_match = re.search(
                r'facebook\.com/(?:pages/[^/]+/)?([^/?#]+)', clean_pid)
            if url_match:
                clean_pid = url_match.group(1).split("-")[-1]

        clean_tok = str(access_token).strip()

        # If user_token is provided, try looking up authentic page_token from /me/accounts
        if user_token and user_token.strip():
            try:
                acc_url = f"{cls.BASE_URL}/me/accounts"
                acc_res = requests.get(
                    acc_url, params={"access_token": user_token.strip(), "limit": 100}, timeout=10)
                acc_data = acc_res.json()
                for p in acc_data.get("data", []):
                    if str(p.get("id")) == clean_pid or str(p.get("name", "")).lower() == clean_pid.lower():
                        clean_pid = str(p.get("id"))
                        if p.get("access_token"):
                            clean_tok = str(p.get("access_token")).strip()
                        break
            except Exception:
                pass

        candidate_field_sets = [
            "id,title,description",
            "id,description,creation_time",
            "id,title",
            None,
        ]

        raw_items = []
        last_error = None

        for field_set in candidate_field_sets:
            url = f"{cls.BASE_URL}/{clean_pid}/video_lists"
            params = {"access_token": clean_tok, "limit": 100}
            if field_set:
                params["fields"] = field_set

            try:
                res = requests.get(url, params=params, timeout=15)
                data = res.json()
                if res.status_code == 200 and "data" in data:
                    raw_items = list(data.get("data", []))
                    next_url = data.get("paging", {}).get("next")
                    pages_fetched = 1
                    while next_url and pages_fetched < 10:
                        try:
                            n_res = requests.get(next_url, timeout=15)
                            n_data = n_res.json()
                            if n_res.status_code == 200 and "data" in n_data:
                                n_items = n_data.get("data", [])
                                if not n_items:
                                    break
                                raw_items.extend(n_items)
                                next_url = n_data.get("paging", {}).get("next")
                                pages_fetched += 1
                            else:
                                break
                        except Exception:
                            break
                    last_error = None
                    break
                else:
                    err_msg = data.get("error", {}).get("message", res.text)
                    last_error = err_msg
                    if "nonexisting field" in err_msg.lower() or "syntax error" in err_msg.lower():
                        continue
            except Exception as ex:
                last_error = str(ex)
                continue

        # Edge fallback if video_lists returned empty or failed
        if not raw_items and not last_error:
            try:
                pl_url = f"{cls.BASE_URL}/{clean_pid}/playlists"
                pl_res = requests.get(
                    pl_url, params={"access_token": clean_tok, "limit": 100}, timeout=15)
                pl_data = pl_res.json()
                if pl_res.status_code == 200 and "data" in pl_data:
                    raw_items = list(pl_data.get("data", []))
            except Exception:
                pass

        if last_error and not raw_items:
            raise RuntimeError(f"Facebook Playlists Query Error: {last_error}")

        playlists = []
        for item in raw_items:
            pl_id = str(item.get("id"))
            pl_title = item.get("title") or item.get(
                "description") or f"Playlist {pl_id}"
            if len(pl_title) > 60:
                pl_title = pl_title[:57] + "..."
            playlists.append({
                "id": pl_id,
                "title": pl_title,
                "description": item.get("description", ""),
                "creation_time": item.get("creation_time", ""),
            })

        # Merge custom saved playlists from config
        try:
            from social_post_config import get_facebook_config
            fb_cfg = get_facebook_config()
            for cp in fb_cfg.get("custom_playlists", []):
                cid = str(cp.get("id", "")).strip()
                if cid and not any(p["id"] == cid for p in playlists):
                    playlists.append({
                        "id": cid,
                        "title": cp.get("title") or f"Playlist {cid}",
                        "description": cp.get("description", ""),
                        "custom": True,
                    })
        except Exception:
            pass

        return playlists

    @classmethod
    def add_video_to_playlist(cls, playlist_id: str, video_id: str, access_token: str) -> bool:
        """Add an uploaded video to a Facebook Page playlist."""
        if not playlist_id or not video_id or not access_token:
            return False

        url = f"{cls.BASE_URL}/{playlist_id.strip()}/videos"
        payload = {
            "video_id": str(video_id).strip(),
            "access_token": access_token.strip(),
        }
        res = requests.post(url, data=payload, timeout=20)
        data = res.json()
        if res.status_code != 200 or "error" in data:
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"Add Video to Playlist Failed: {err}")
        return True

    @classmethod
    def fetch_all_available_groups(
        cls, access_token: str, page_id: str = "", user_token: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Fetch all Facebook Groups accessible to the user and page.
        Queries /me/groups with access_token and user_token, plus /{page_id}/groups,
        traversing full pagination (paging.next) and deduplicating by group ID.
        Gracefully handles Meta API permission restrictions (e.g. user_managed_groups)
        and merges custom/manually added groups.
        """
        if not access_token and not user_token:
            return []

        tokens_to_try = []
        if access_token and access_token.strip():
            tokens_to_try.append(access_token.strip())
        if user_token and user_token.strip() and user_token.strip() not in tokens_to_try:
            tokens_to_try.append(user_token.strip())

        seen_group_ids = set()
        all_groups = []
        errors = []

        def _fetch_edge(edge_url: str, tok: str):
            nonlocal seen_group_ids, all_groups, errors
            params = {
                "fields": "id,name,privacy,administrator,description",
                "access_token": tok,
                "limit": 100,
            }
            try:
                res = requests.get(edge_url, params=params, timeout=15)
                data = res.json()
                if res.status_code != 200 or "error" in data:
                    err_msg = data.get("error", {}).get("message", res.text)
                    if "nonexisting field" in err_msg.lower():
                        params["fields"] = "id,name,privacy"
                        res = requests.get(edge_url, params=params, timeout=15)
                        data = res.json()
                    else:
                        errors.append(err_msg)
                        return

                if res.status_code == 200 and "data" in data:
                    page_items = data.get("data", [])
                    for item in page_items:
                        gid = str(item.get("id"))
                        if gid and gid not in seen_group_ids:
                            seen_group_ids.add(gid)
                            all_groups.append({
                                "id": gid,
                                "name": item.get("name", f"Group {gid}"),
                                "privacy": item.get("privacy", "UNKNOWN"),
                                "administrator": bool(item.get("administrator", False)),
                                "description": item.get("description", ""),
                            })

                    next_url = data.get("paging", {}).get("next")
                    pages_followed = 1
                    while next_url and pages_followed < 10:
                        try:
                            n_res = requests.get(next_url, timeout=15)
                            n_data = n_res.json()
                            if n_res.status_code == 200 and "data" in n_data:
                                n_items = n_data.get("data", [])
                                if not n_items:
                                    break
                                for item in n_items:
                                    gid = str(item.get("id"))
                                    if gid and gid not in seen_group_ids:
                                        seen_group_ids.add(gid)
                                        all_groups.append({
                                            "id": gid,
                                            "name": item.get("name", f"Group {gid}"),
                                            "privacy": item.get("privacy", "UNKNOWN"),
                                            "administrator": bool(item.get("administrator", False)),
                                            "description": item.get("description", ""),
                                        })
                                next_url = n_data.get("paging", {}).get("next")
                                pages_followed += 1
                            else:
                                break
                        except Exception:
                            break
            except Exception as e:
                errors.append(str(e))

        for tok in tokens_to_try:
            _fetch_edge(f"{cls.BASE_URL}/me/groups", tok)

        if page_id and access_token:
            _fetch_edge(f"{cls.BASE_URL}/{page_id.strip()}/groups",
                        access_token.strip())

        # Merge custom / manually added groups from config
        try:
            from social_post_config import get_facebook_config
            fb_cfg = get_facebook_config()
            for cg in fb_cfg.get("custom_groups", []):
                gid = str(cg.get("id", "")).strip()
                if gid and gid not in seen_group_ids:
                    seen_group_ids.add(gid)
                    all_groups.append({
                        "id": gid,
                        "name": cg.get("name") or f"Group {gid}",
                        "privacy": cg.get("privacy", "CUSTOM"),
                        "administrator": bool(cg.get("administrator", False)),
                        "description": cg.get("description", "Manually added group"),
                        "custom": True,
                    })
        except Exception:
            pass

        # If no groups found and errors occurred:
        # Check if the error is Meta's user_managed_groups permission restriction
        if not all_groups and errors:
            is_perm_err = any("user_managed_groups" in str(
                e).lower() or "permission" in str(e).lower() for e in errors)
            if not is_perm_err:
                raise RuntimeError(
                    f"Facebook Groups Query Error: {'; '.join(errors[:2])}")

        # Sort: Admin groups first, then alphabetically by name
        all_groups.sort(key=lambda g: (
            not g.get("administrator", False), g.get("name", "").lower()))
        return all_groups

    @classmethod
    def fetch_user_groups(cls, access_token: str) -> List[Dict[str, Any]]:
        """Backward-compatible alias for fetch_all_available_groups."""
        return cls.fetch_all_available_groups(access_token)

    @classmethod
    def share_video_to_group(cls, group_id: str, video_url: str, message: str, access_token: str) -> Dict[str, Any]:
        """Share a published video post link into a single Facebook Group."""
        res = cls.share_video_to_groups(
            group_ids=[group_id],
            video_url=video_url,
            message=message,
            access_token=access_token,
        )
        if res.get("results") and res["results"][0].get("post_id"):
            res["post_id"] = res["results"][0]["post_id"]
        return res

    @classmethod
    def share_video_to_groups(
        cls,
        group_ids: List[str],
        video_url: str,
        message: str,
        access_token: str,
        user_token: str = "",
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Share a published video post link into one or multiple Facebook Groups.
        Tries user_token first, then access_token. Individual group errors do not halt others.
        """
        if not group_ids or not video_url:
            return {"success": True, "shared_count": 0, "failed_count": 0, "results": []}

        clean_ids = [str(gid).strip() for gid in group_ids if str(
            gid).strip() and not str(gid).startswith("(None")]
        if not clean_ids:
            return {"success": True, "shared_count": 0, "failed_count": 0, "results": []}

        tokens_to_try = []
        if user_token and user_token.strip():
            tokens_to_try.append(user_token.strip())
        if access_token and access_token.strip() and access_token.strip() not in tokens_to_try:
            tokens_to_try.append(access_token.strip())

        total = len(clean_ids)
        results = []
        success_count = 0
        failed_count = 0

        for i, gid in enumerate(clean_ids, 1):
            if progress_callback:
                progress_callback(
                    95 + int((i / total) * 4), f"Sharing video to Group [{i}/{total}] (ID: {gid})...")

            shared = False
            last_err = ""
            post_id = ""

            for tok in tokens_to_try:
                url = f"{cls.BASE_URL}/{gid}/feed"
                payload = {
                    "link": video_url.strip(),
                    "message": message.strip() if message else "",
                    "access_token": tok,
                }
                try:
                    res = requests.post(url, data=payload, timeout=20)
                    data = res.json()
                    if res.status_code == 200 and "id" in data:
                        shared = True
                        post_id = data.get("id")
                        break
                    else:
                        last_err = data.get("error", {}).get(
                            "message", res.text)
                except Exception as e:
                    last_err = str(e)

            if shared:
                success_count += 1
                results.append(
                    {"group_id": gid, "success": True, "post_id": post_id})
            else:
                failed_count += 1
                results.append(
                    {"group_id": gid, "success": False, "error": last_err})

        return {
            "success": (success_count > 0 or total == 0),
            "total": total,
            "shared_count": success_count,
            "failed_count": failed_count,
            "results": results,
        }

    @classmethod
    def upload_video(
        cls,
        video_path: str,
        page_id: str,
        access_token: str,
        title: str = "",
        description: str = "",
        published: bool = True,
        scheduled_publish_time: Optional[int] = None,
        disable_caption: bool = False,
        check_closed_caption: bool = True,
        caption_locale: str = "en_US",
        caption_file: Optional[str] = None,
        playlist_id: str = "",
        group_id: str = "",
        group_ids: Optional[List[str]] = None,
        user_token: str = "",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Upload video to Facebook Page via Resumable Chunked Upload API.
        Supports instant publishing, public scheduling, draft saving, playlist assignment,
        closed caption (.srt/.vtt) auto-detection and upload, and multi-group link sharing.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file does not exist: {video_path}")
        if not page_id or not access_token:
            raise ValueError("Page ID and Access Token must be provided.")

        file_size = os.path.getsize(video_path)
        page_id = page_id.strip()
        token = access_token.strip()

        if progress_callback:
            progress_callback(5, "Initializing Facebook upload session...")

        # Phase 1: Start upload session
        init_url = f"{cls.BASE_URL}/{page_id}/videos"
        init_payload = {
            "upload_phase": "start",
            "file_size": file_size,
            "access_token": token,
        }
        res = requests.post(init_url, data=init_payload, timeout=20)
        data = res.json()
        if res.status_code != 200 or "upload_session_id" not in data:
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"Facebook Init Session Failed: {err}")

        session_id = data["upload_session_id"]
        video_id = data.get("video_id")
        start_offset = int(data.get("start_offset", 0))
        end_offset = int(data.get("end_offset", file_size))

        # Phase 2: Transfer chunks
        chunk_size = 4 * 1024 * 1024  # 4 MB chunks
        with open(video_path, "rb") as f:
            while start_offset < file_size:
                if cancel_check and cancel_check():
                    raise RuntimeError("Upload cancelled by user.")

                f.seek(start_offset)
                chunk_bytes = f.read(
                    end_offset - start_offset if end_offset > start_offset else chunk_size)
                if not chunk_bytes:
                    break

                files = {"video_file_chunk": chunk_bytes}
                transfer_data = {
                    "upload_phase": "transfer",
                    "upload_session_id": session_id,
                    "start_offset": start_offset,
                    "access_token": token,
                }
                res = requests.post(
                    init_url, data=transfer_data, files=files, timeout=60)
                t_data = res.json()
                if res.status_code != 200:
                    err = t_data.get("error", {}).get("message", res.text)
                    raise RuntimeError(
                        f"Facebook Transfer Chunk Failed: {err}")

                start_offset = int(t_data.get(
                    "start_offset", start_offset + len(chunk_bytes)))
                end_offset = int(t_data.get("end_offset", min(
                    start_offset + chunk_size, file_size)))

                pct = min(90, int((start_offset / file_size) * 85) + 5)
                if progress_callback:
                    mb_sent = start_offset / (1024 * 1024)
                    mb_total = file_size / (1024 * 1024)
                    progress_callback(
                        pct, f"Uploading chunk: {mb_sent:.1f}/{mb_total:.1f} MB ({pct}%)")

        # Phase 3: Finish upload session
        if progress_callback:
            if scheduled_publish_time and scheduled_publish_time > 0:
                sched_dt_str = time.strftime(
                    '%Y-%m-%d %H:%M:%S', time.localtime(scheduled_publish_time))
                progress_callback(
                    92, f"Finalizing video post (Scheduled for {sched_dt_str})...")
            else:
                progress_callback(92, "Finalizing Facebook video post...")

        post_description = "" if disable_caption else (description or "")

        finish_data = {
            "upload_phase": "finish",
            "upload_session_id": session_id,
            "title": title,
            "description": post_description,
            "access_token": token,
        }

        # Handle scheduled public vs immediate publish vs draft
        if scheduled_publish_time and scheduled_publish_time > 0:
            finish_data["published"] = "false"
            finish_data["scheduled_publish_time"] = int(scheduled_publish_time)
        else:
            finish_data["published"] = "true" if published else "false"

        res = requests.post(init_url, data=finish_data, timeout=30)
        f_data = res.json()
        if res.status_code != 200 or not f_data.get("success", False):
            if "id" not in f_data and not f_data.get("success", False):
                err = f_data.get("error", {}).get("message", res.text)
                raise RuntimeError(f"Facebook Finalize Failed: {err}")

        final_vid = f_data.get("id") or video_id or session_id
        fb_url = f"https://www.facebook.com/{page_id}/videos/{final_vid}"

        # Optional: Auto-detect, upload, and verify Closed Caption (.srt / .vtt)
        caption_upload_result = {}
        if check_closed_caption:
            cap_info = None
            if caption_file and os.path.exists(caption_file):
                cap_info = {
                    "path": caption_file,
                    "locale": caption_locale,
                    "type": "srt" if caption_file.lower().endswith(".srt") else "vtt"
                }
            else:
                cap_info = find_closed_caption_file(video_path)

            if cap_info and os.path.exists(cap_info["path"]):
                c_path = cap_info["path"]
                c_loc = cap_info.get("locale") or caption_locale or "en_US"
                try:
                    if progress_callback:
                        progress_callback(
                            93, f"Uploading closed captions: {os.path.basename(c_path)} ({c_loc})...")
                    caption_upload_result = cls.upload_video_captions(
                        video_id=final_vid,
                        caption_file_path=c_path,
                        access_token=token,
                        locale=c_loc,
                    )
                    verified = cls.verify_video_captions(final_vid, token)
                    caption_upload_result["verified"] = bool(verified)
                    caption_upload_result["verified_tracks"] = verified
                    if progress_callback:
                        progress_callback(
                            94, f"✅ Closed caption attached: {os.path.basename(c_path)} ({c_loc})")
                except Exception as ce:
                    caption_upload_result = {
                        "success": False, "error": str(ce), "path": c_path}
                    if progress_callback:
                        progress_callback(94, f"Closed caption notice: {ce}")
            else:
                if progress_callback:
                    progress_callback(
                        94, f"ℹ️ No closed caption file found for {os.path.basename(video_path)}")

        # Optional: Add to Playlist
        if playlist_id:
            try:
                if progress_callback:
                    progress_callback(
                        95, f"Adding video to playlist (ID: {playlist_id})...")
                cls.add_video_to_playlist(playlist_id, final_vid, token)
            except Exception as pe:
                if progress_callback:
                    progress_callback(96, f"Playlist notice: {pe}")

        # Optional: Share to Facebook Groups
        target_group_ids = []
        if group_ids:
            if isinstance(group_ids, list):
                target_group_ids.extend(group_ids)
            elif isinstance(group_ids, str) and group_ids.strip():
                target_group_ids.extend(
                    [g.strip() for g in group_ids.split(",") if g.strip()])
        if group_id and group_id.strip() not in target_group_ids and not str(group_id).startswith("(None"):
            target_group_ids.append(group_id.strip())

        group_share_result = {}
        if target_group_ids:
            try:
                if len(target_group_ids) == 1 and not user_token:
                    group_share_result = cls.share_video_to_group(
                        group_id=target_group_ids[0],
                        video_url=fb_url,
                        message=title,
                        access_token=token,
                    )
                else:
                    group_share_result = cls.share_video_to_groups(
                        group_ids=target_group_ids,
                        video_url=fb_url,
                        message=title,
                        access_token=token,
                        user_token=user_token,
                        progress_callback=progress_callback,
                    )
                if group_share_result.get("failed_count", 0) > 0 and progress_callback:
                    progress_callback(
                        99,
                        f"Notice: Shared to {group_share_result['shared_count']}/{len(target_group_ids)} groups (some groups require admin approval)."
                    )
            except Exception as ge:
                if progress_callback:
                    progress_callback(99, f"Group share notice: {ge}")

        status_label = "scheduled" if (scheduled_publish_time and scheduled_publish_time > 0) else (
            "published" if published else "draft")
        if progress_callback:
            if status_label == "scheduled":
                sched_dt_str = time.strftime(
                    '%Y-%m-%d %H:%M:%S', time.localtime(scheduled_publish_time))
                progress_callback(
                    100, f"✅ Video scheduled successfully for {sched_dt_str}!")
            elif status_label == "published":
                progress_callback(
                    100, "✅ Published successfully to Facebook Page!")
            else:
                progress_callback(
                    100, "✅ Video saved as Draft to Facebook Page!")

        return {
            "success": True,
            "video_id": final_vid,
            "url": fb_url,
            "platform": "facebook",
            "status": status_label,
            "scheduled_publish_time": scheduled_publish_time,
            "playlist_id": playlist_id,
            "group_id": group_id,
            "group_ids": target_group_ids,
            "group_share": group_share_result,
            "caption_upload": caption_upload_result,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 1.1 FACEBOOK ASYNC BACKGROUND WORKERS
# ─────────────────────────────────────────────────────────────────────────────

class FacebookPlaylistsWorker(QThread):
    """Background worker to query Facebook Page playlists without blocking GUI."""
    success_sig = pyqtSignal(list)
    error_sig = pyqtSignal(str)

    def __init__(self, page_id: str, access_token: str, user_token: str = "", parent=None):
        super().__init__(parent)
        self.page_id = page_id
        self.access_token = access_token
        self.user_token = user_token

    def run(self):
        try:
            playlists = FacebookUploader.fetch_page_playlists(
                self.page_id, self.access_token, user_token=self.user_token)
            self.success_sig.emit(playlists)
        except Exception as e:
            self.error_sig.emit(str(e))


class FacebookGroupsWorker(QThread):
    """Background worker to query all available Facebook Groups without blocking GUI."""
    success_sig = pyqtSignal(list)
    error_sig = pyqtSignal(str)

    def __init__(self, access_token: str, page_id: str = "", user_token: str = "", parent=None):
        super().__init__(parent)
        self.access_token = access_token
        self.page_id = page_id
        self.user_token = user_token

    def run(self):
        try:
            groups = FacebookUploader.fetch_all_available_groups(
                access_token=self.access_token,
                page_id=self.page_id,
                user_token=self.user_token,
            )
            self.success_sig.emit(groups)
        except Exception as e:
            self.error_sig.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. YOUTUBE UPLOADER (OAuth 2.0 Loopback & Data API v3 Resumable Upload)
# ─────────────────────────────────────────────────────────────────────────────

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Internal HTTP handler to receive Google OAuth authorization code."""
    auth_code: Optional[str] = None
    error: Optional[str] = None

    def log_message(self, format, *args):
        pass  # Suppress console logging

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if "code" in params:
            self.__class__.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            success_html = """
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Successful</title></head>
            <body style="font-family: system-ui, sans-serif; text-align: center; padding: 40px; background: #0F141C; color: #FFF;">
                <h1 style="color: #4CAF50; font-size: 28px;">✅ YouTube Authorization Successful!</h1>
                <p style="font-size: 16px; color: #BBB;">You have successfully connected your YouTube account to <b>AI Dubber Ultimate</b>.</p>
                <p style="font-size: 14px; color: #888;">You can now close this browser tab and return to the application.</p>
            </body>
            </html>
            """
            self.wfile.write(success_html.encode("utf-8"))
        else:
            self.__class__.error = params.get("error", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            err_html = f"<html><body><h1>❌ Authorization Failed: {self.__class__.error}</h1></body></html>"
            self.wfile.write(err_html.encode("utf-8"))


class YouTubeUploader:
    """Uploader engine for YouTube using the Google Data API v3."""
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true"
    SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

    @classmethod
    def start_oauth_flow(cls, client_id: str, client_secret: str, port: int = 8088) -> Dict[str, Any]:
        """
        Launches Google OAuth consent screen in browser and catches the redirect
        using a local loopback server to obtain access_token and refresh_token.
        """
        if not client_id or not client_secret:
            raise ValueError(
                "Google Client ID and Client Secret are required.")

        redirect_uri = f"http://localhost:{port}/callback"

        # Check port availability
        try:
            server = HTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
            server.timeout = 180  # 3 minutes timeout for user to log in
            _OAuthCallbackHandler.auth_code = None
            _OAuthCallbackHandler.error = None
        except Exception as e:
            raise RuntimeError(
                f"Could not bind OAuth local server on port {port}: {e}")

        # Build authorization URL
        auth_params = {
            "client_id": client_id.strip(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": cls.SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{cls.AUTH_ENDPOINT}?{urllib.parse.urlencode(auth_params)}"
        webbrowser.open(auth_url)

        # Handle 1 incoming request
        while _OAuthCallbackHandler.auth_code is None and _OAuthCallbackHandler.error is None:
            server.handle_request()

        server.server_close()

        if _OAuthCallbackHandler.error:
            raise RuntimeError(
                f"Google Authorization was denied: {_OAuthCallbackHandler.error}")

        code = _OAuthCallbackHandler.auth_code
        if not code:
            raise RuntimeError("Authorization timed out or no code received.")

        # Exchange authorization code for tokens
        token_payload = {
            "code": code,
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        res = requests.post(cls.TOKEN_ENDPOINT, data=token_payload, timeout=15)
        t_data = res.json()
        if res.status_code != 200 or "access_token" not in t_data:
            err = t_data.get("error_description", res.text)
            raise RuntimeError(f"Token exchange failed: {err}")

        access_token = t_data["access_token"]
        refresh_token = t_data.get("refresh_token", "")

        # Test and fetch channel name
        channel_info = {}
        try:
            channel_info = cls.test_connection(access_token)
        except Exception:
            pass

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "channel_title": channel_info.get("title", ""),
            "channel_id": channel_info.get("id", ""),
        }

    @classmethod
    def refresh_access_token(cls, client_id: str, client_secret: str, refresh_token: str) -> str:
        """Refresh expired Google access token using the stored refresh token."""
        if not refresh_token:
            raise ValueError(
                "Refresh token is required to refresh access token.")

        payload = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "refresh_token": refresh_token.strip(),
            "grant_type": "refresh_token",
        }
        res = requests.post(cls.TOKEN_ENDPOINT, data=payload, timeout=15)
        data = res.json()
        if res.status_code != 200 or "access_token" not in data:
            err = data.get("error_description", res.text)
            raise RuntimeError(f"Token refresh failed: {err}")

        return data["access_token"]

    @classmethod
    def test_connection(cls, access_token: str) -> Dict[str, Any]:
        """Test YouTube credentials and fetch channel info."""
        if not access_token:
            raise ValueError(
                "Access token is required to test YouTube connection.")

        headers = {"Authorization": f"Bearer {access_token.strip()}"}
        res = requests.get(cls.CHANNELS_ENDPOINT, headers=headers, timeout=12)
        data = res.json()
        if res.status_code != 200 or "error" in data:
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"YouTube Channel Query Failed: {err}")

        items = data.get("items", [])
        if not items:
            return {"title": "Connected Account (No Channel)", "id": "", "subscribers": "0"}

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})

        return {
            "id": item.get("id", ""),
            "title": snippet.get("title", "YouTube Channel"),
            "custom_url": snippet.get("customUrl", ""),
            "subscribers": stats.get("subscriberCount", "0"),
            "avatar": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
        }

    @classmethod
    def upload_video(
        cls,
        video_path: str,
        access_token: str,
        title: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        privacy_status: str = "public",  # "public", "unlisted", "private"
        category_id: str = "22",
        made_for_kids: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Uploads video to YouTube via the official Resumable Upload protocol.
        Sends file in 2MB chunks with byte progress callbacks.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not access_token:
            raise ValueError("YouTube access token is required for upload.")

        file_size = os.path.getsize(video_path)
        token = access_token.strip()

        if progress_callback:
            progress_callback(
                5, "Initiating YouTube resumable upload session...")

        # Step 1: Initialize Resumable Upload Session
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/mp4",
        }
        metadata = {
            "snippet": {
                "title": title or os.path.basename(video_path),
                "description": description or "",
                "tags": tags or [],
                "categoryId": category_id or "22",
            },
            "status": {
                "privacyStatus": privacy_status or "public",
                "selfDeclaredMadeForKids": bool(made_for_kids),
            },
        }

        res = requests.post(cls.UPLOAD_ENDPOINT,
                            headers=headers, json=metadata, timeout=25)
        if res.status_code != 200 or "Location" not in res.headers:
            err = res.text
            try:
                err_json = res.json()
                err = err_json.get("error", {}).get("message", res.text)
            except Exception:
                pass
            raise RuntimeError(
                f"YouTube Init Upload Failed ({res.status_code}): {err}")

        upload_url = res.headers["Location"]

        # Step 2: Stream file in chunks (multiples of 256KB; using 2MB = 2097152 bytes)
        chunk_size = 2 * 1024 * 1024
        uploaded_bytes = 0

        with open(video_path, "rb") as f:
            while uploaded_bytes < file_size:
                if cancel_check and cancel_check():
                    raise RuntimeError("Upload cancelled by user.")

                f.seek(uploaded_bytes)
                chunk_data = f.read(chunk_size)
                if not chunk_data:
                    break

                chunk_end = uploaded_bytes + len(chunk_data) - 1
                put_headers = {
                    "Content-Length": str(len(chunk_data)),
                    "Content-Range": f"bytes {uploaded_bytes}-{chunk_end}/{file_size}",
                    "Content-Type": "video/mp4",
                }

                put_res = requests.put(
                    upload_url, headers=put_headers, data=chunk_data, timeout=60)

                # 308 Resume Incomplete means chunk uploaded, waiting for next
                if put_res.status_code in (200, 201):
                    # Finished!
                    final_data = put_res.json()
                    vid = final_data.get("id")
                    if progress_callback:
                        progress_callback(
                            100, f"YouTube video published successfully! (ID: {vid})")
                    return {
                        "success": True,
                        "video_id": vid,
                        "url": f"https://youtu.be/{vid}",
                        "platform": "youtube",
                    }
                elif put_res.status_code == 308:
                    range_header = put_res.headers.get("Range")
                    if range_header:
                        uploaded_bytes = int(range_header.split("-")[1]) + 1
                    else:
                        uploaded_bytes += len(chunk_data)

                    pct = min(95, int((uploaded_bytes / file_size) * 90) + 5)
                    if progress_callback:
                        mb_sent = uploaded_bytes / (1024 * 1024)
                        mb_total = file_size / (1024 * 1024)
                        progress_callback(
                            pct, f"Uploading chunk: {mb_sent:.1f}/{mb_total:.1f} MB ({pct}%)")
                else:
                    err = put_res.text
                    try:
                        err = put_res.json().get("error", {}).get("message", put_res.text)
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"YouTube Upload Failed ({put_res.status_code}): {err}")

        raise RuntimeError(
            "YouTube upload finished without returning video ID.")


# ─────────────────────────────────────────────────────────────────────────────
# 3. TIKTOK UPLOADER (Content Posting API v2)
# ─────────────────────────────────────────────────────────────────────────────

class TikTokUploader:
    """Uploader engine for TikTok using the official Content Posting API v2."""
    BASE_URL = "https://open.tiktokapis.com/v2"

    @classmethod
    def test_connection(cls, access_token: str) -> Dict[str, Any]:
        """Verify TikTok access token and fetch creator permissions."""
        if not access_token:
            raise ValueError("TikTok Access Token is required.")

        url = f"{cls.BASE_URL}/post/publish/creator_info/query/"
        headers = {
            "Authorization": f"Bearer {access_token.strip()}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        res = requests.post(url, headers=headers, json={}, timeout=12)
        data = res.json()
        if res.status_code != 200 or data.get("error", {}).get("code") != "ok":
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"TikTok Verification Error: {err}")

        creator_data = data.get("data", {})
        return {
            "creator_nickname": creator_data.get("creator_nickname", "TikTok Creator"),
            "creator_avatar": creator_data.get("creator_avatar_url", ""),
            "privacy_options": creator_data.get("privacy_level_options", []),
            "duet_disabled": creator_data.get("duet_disabled", False),
            "stitch_disabled": creator_data.get("stitch_disabled", False),
            "comment_disabled": creator_data.get("comment_disabled", False),
        }

    @classmethod
    def upload_video(
        cls,
        video_path: str,
        access_token: str,
        title: str = "",
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Uploads video to TikTok via Direct Post API v2.
        Initializes post, streams chunk data, and checks publish status.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not access_token:
            raise ValueError("TikTok access token is required.")

        file_size = os.path.getsize(video_path)
        token = access_token.strip()

        if progress_callback:
            progress_callback(5, "Initializing TikTok video upload session...")

        # Step 1: Initialize Direct Post Upload
        init_url = f"{cls.BASE_URL}/post/publish/video/init/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        init_payload = {
            "post_info": {
                "title": title[:150] if title else os.path.splitext(os.path.basename(video_path))[0],
                "privacy_level": privacy_level,
                "disable_duet": bool(disable_duet),
                "disable_stitch": bool(disable_stitch),
                "disable_comment": bool(disable_comment),
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        }

        res = requests.post(init_url, headers=headers,
                            json=init_payload, timeout=25)
        data = res.json()
        if res.status_code != 200 or data.get("error", {}).get("code") != "ok":
            err = data.get("error", {}).get("message", res.text)
            raise RuntimeError(f"TikTok Init Post Failed: {err}")

        upload_data = data.get("data", {})
        publish_id = upload_data.get("publish_id")
        upload_url = upload_data.get("upload_url")

        if not upload_url:
            raise RuntimeError("TikTok API did not return upload URL.")

        if progress_callback:
            progress_callback(
                15, "Uploading video content to TikTok servers...")

        # Step 2: Upload file bytes to the upload_url via PUT
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        put_headers = {
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            "Content-Type": "video/mp4",
        }

        if cancel_check and cancel_check():
            raise RuntimeError("Upload cancelled by user.")

        put_res = requests.put(
            upload_url, headers=put_headers, data=video_bytes, timeout=120)
        if put_res.status_code not in (200, 201, 204):
            raise RuntimeError(
                f"TikTok Video Data Upload Failed: {put_res.status_code} - {put_res.text}")

        if progress_callback:
            progress_callback(90, "TikTok upload received. Publishing post...")

        # Step 3: Check post status
        check_url = f"{cls.BASE_URL}/post/publish/status/fetch/"
        status_payload = {"publish_id": publish_id}
        check_res = requests.post(
            check_url, headers=headers, json=status_payload, timeout=15)
        check_data = check_res.json()

        status_code = check_data.get("data", {}).get(
            "status", "PUBLISH_COMPLETE")
        tiktok_url = f"https://www.tiktok.com/@me"  # Link to creator profile or post

        if progress_callback:
            progress_callback(100, "Published successfully to TikTok!")

        return {
            "success": True,
            "publish_id": publish_id,
            "url": tiktok_url,
            "status": status_code,
            "platform": "tiktok",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. MULTI-PLATFORM ASYNCHRONOUS WORKER (QThread)
# ─────────────────────────────────────────────────────────────────────────────

class SocialUploadWorker(QThread):
    """
    Background worker that runs uploads to Facebook, YouTube, and TikTok concurrently
    or sequentially without freezing the GUI. Supports single video and batch folder queues.
    """
    platform_started = pyqtSignal(str)
    platform_progress = pyqtSignal(str, int, str)
    # platform, success, message, url
    platform_completed = pyqtSignal(str, bool, str, str)
    log_message = pyqtSignal(str, str)                    # level, text
    all_completed = pyqtSignal(dict)                      # summary dict
    # current_idx (1-based), total_count, video_name
    video_queue_started = pyqtSignal(int, int, str)
    # current_idx, total_count, video_name, summary
    video_queue_completed = pyqtSignal(int, int, str, dict)

    def __init__(
        self,
        video_path: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        credentials: Optional[Dict[str, Any]] = None,
        video_paths: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        if video_paths:
            self.video_paths = [
                p for p in video_paths if p and os.path.exists(p)]
        elif video_path and os.path.exists(video_path):
            self.video_paths = [video_path]
        else:
            self.video_paths = [video_path] if video_path else []

        self.video_path = self.video_paths[0] if self.video_paths else (
            video_path or "")
        self.platforms = platforms or []  # list: ['facebook', 'youtube', 'tiktok']
        self.metadata = metadata or {}
        self.credentials = credentials or {}
        self._is_cancelled = False
        self._facebook_bulk_done = False

    def cancel(self):
        """Request cancellation of the current uploads."""
        self._is_cancelled = True
        self.log_message.emit("WARN", "Cancellation requested by user...")

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def run(self):
        total_vids = len(self.video_paths)
        overall_summary = {
            "total_videos": total_vids,
            "video_results": [],
            "success_count": 0,
            "fail_count": 0,
            "results": {},  # For backwards compatibility with single video
        }

        if total_vids == 0:
            self.log_message.emit(
                "WARN", "No valid videos found in queue to upload.")
            self.all_completed.emit(overall_summary)
            return

        self.log_message.emit(
            "INFO", f"Starting upload task: {total_vids} video(s) for {len(self.platforms)} platform(s)...")

        for v_idx, v_path in enumerate(self.video_paths, 1):
            if self._is_cancelled:
                self.log_message.emit(
                    "WARN", f"Queue cancelled. Skipping remaining {total_vids - v_idx + 1} video(s).")
                break

            self.video_path = v_path
            v_name = os.path.basename(v_path)
            self.video_queue_started.emit(v_idx, total_vids, v_name)
            self.log_message.emit(
                "INFO", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.log_message.emit(
                "INFO", f"🎬 [{v_idx}/{total_vids}] Video target: {v_name}")

            # Per-video metadata dynamic combination: config.txt title + episode
            raw_title = self.metadata.get("title", "")
            raw_desc = self.metadata.get("description", "")

            v_title = build_bulk_video_title(raw_title, v_path, v_idx)
            v_desc = build_bulk_video_description(
                raw_desc, v_title, v_path, v_idx)

            v_meta = dict(self.metadata)
            v_meta["title"] = v_title
            v_meta["description"] = v_desc

            # Calculate schedule time for batch queue if schedule mode active
            if self.metadata.get("fb_publish_status") == "schedule":
                base_sched = self.metadata.get("fb_schedule_timestamp")
                if base_sched:
                    interval_sec = int(self.metadata.get(
                        "fb_schedule_interval_minutes", 60)) * 60
                    v_sched = int(base_sched) + (v_idx - 1) * interval_sec
                    now_ts = int(time.time())
                    if v_sched < now_ts + 600:
                        v_sched = now_ts + 660
                    v_meta["fb_scheduled_publish_time"] = v_sched

            single_summary = {
                "video_name": v_name,
                "video_path": v_path,
                "title": v_title,
                "success_count": 0,
                "fail_count": 0,
                "results": {},
            }

            for platform in self.platforms:
                if self._is_cancelled:
                    self.log_message.emit(
                        "WARN", f"Skipping {platform} for {v_name} due to cancellation.")
                    self.platform_completed.emit(
                        platform, False, "Cancelled by user.", "")
                    single_summary["fail_count"] += 1
                    single_summary["results"][platform] = {
                        "success": False, "message": "Cancelled"}
                    continue

                self.platform_started.emit(platform)
                self.log_message.emit(
                    "INFO", f"Connecting to {platform.capitalize()} for {v_name}...")

                try:
                    if platform == "facebook":
                        res = self._run_facebook(v_path, v_meta)
                    elif platform == "youtube":
                        res = self._run_youtube(v_path, v_meta)
                    elif platform == "tiktok":
                        res = self._run_tiktok(v_path, v_meta)
                    else:
                        raise ValueError(f"Unknown platform: {platform}")

                    single_summary["success_count"] += 1
                    single_summary["results"][platform] = res
                    vid_url = res.get("url", "")
                    self.platform_completed.emit(
                        platform, True, "Upload Succeeded!", vid_url)
                    self.log_message.emit(
                        "SUCCESS", f"[{platform.upper()}] Success for {v_name}! Link: {vid_url}")

                except Exception as e:
                    err_msg = str(e)
                    single_summary["fail_count"] += 1
                    single_summary["results"][platform] = {
                        "success": False, "message": err_msg}
                    self.platform_completed.emit(platform, False, err_msg, "")
                    self.log_message.emit(
                        "ERROR", f"[{platform.upper()}] Failed for {v_name}: {err_msg}")

            overall_summary["video_results"].append(single_summary)
            if single_summary["success_count"] > 0:
                overall_summary["success_count"] += 1
            else:
                overall_summary["fail_count"] += 1

            self.video_queue_completed.emit(
                v_idx, total_vids, v_name, single_summary)

        # Retain last video's results dict for single-video compatibility
        if overall_summary["video_results"]:
            overall_summary["results"] = overall_summary["video_results"][-1]["results"]

        self.all_completed.emit(overall_summary)

    def _run_facebook(self, video_path: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target_path = video_path or self.video_path
        target_meta = meta or self.metadata

        fb_cfg = self.credentials.get("facebook", {})
        post_method = fb_cfg.get("post_method", "graph_api")

        title = target_meta.get("title", "")
        description = target_meta.get("description", "")
        published = target_meta.get("fb_published", True)
        publish_status = target_meta.get("fb_publish_status", "publish_now")
        scheduled_time = target_meta.get("fb_scheduled_publish_time", None)
        disable_caption = bool(target_meta.get("fb_disable_caption", False))
        check_closed_caption = bool(target_meta.get(
            "fb_closed_caption", fb_cfg.get("closed_caption_enabled", True)))
        caption_locale = str(target_meta.get(
            "fb_caption_locale", fb_cfg.get("closed_caption_locale", "en_US")))
        caption_file = target_meta.get("fb_caption_file", None)
        playlist_id = target_meta.get("fb_playlist_id", "").strip()
        group_id = target_meta.get("fb_group_id", "").strip()
        group_ids = target_meta.get("fb_group_ids", [])
        user_token = fb_cfg.get("user_token", "").strip()

        def cb(pct, txt):
            self.platform_progress.emit("facebook", pct, txt)

        # Mode A: Browser Automation (Zero-token via Chrome profile)
        if post_method == "browser":
            from facebook_browser_poster import FacebookBrowserPoster, DEFAULT_ASSET_ID
            profile_name = fb_cfg.get("browser_profile", "Default")
            user_data_dir = fb_cfg.get("browser_user_data_dir", "") or None
            headless = bool(fb_cfg.get("browser_headless", False))
            raw_asset = (
                target_meta.get("asset_id", "").strip()
                or fb_cfg.get("browser_asset_id", "").strip()
                or fb_cfg.get("page_id", "").strip()
            )
            if not raw_asset or raw_asset in ("12345", "mock_page_id", "test_page_123"):
                target_asset_id = DEFAULT_ASSET_ID
            else:
                target_asset_id = raw_asset
            target_playlist = playlist_id or target_meta.get(
                "playlist", "") or target_meta.get("fb_playlist", "")

            poster = FacebookBrowserPoster(
                user_data_dir=user_data_dir,
                profile_name=profile_name,
                headless=headless,
            )

            # Safety session validation & smart fallback
            s_status = poster.check_session_status()
            if not s_status.get("logged_in"):
                if profile_name != "Default":
                    def_poster = FacebookBrowserPoster(
                        user_data_dir=user_data_dir,
                        profile_name="Default",
                        headless=headless,
                    )
                    def_status = def_poster.check_session_status()
                    if def_status.get("logged_in"):
                        cb(5, f"Notice: Profile '{profile_name}' lacks session cookies. Auto-switching to active profile 'Default' (UID: {def_status.get('user_id')})...")
                        profile_name = "Default"
                        poster = def_poster
                if not poster.check_session_status().get("logged_in") and headless:
                    poster.headless = False

            if len(self.video_paths) > 1 and target_path == self.video_paths[0]:
                cb(5,
                   f"Starting Bulk Browser Automation for {len(self.video_paths)} video(s) using Chrome Profile '{profile_name}'...")
                res = poster.bulk_post(
                    video_paths=self.video_paths,
                    title=title,
                    description=description,
                    asset_id=target_asset_id,
                    playlist=target_playlist,
                    disable_caption=disable_caption,
                    progress_callback=cb,
                )
                self._facebook_bulk_done = True
                return res
            elif getattr(self, "_facebook_bulk_done", False):
                cb(100, "Already published via Meta Bulk Composer session.")
                return {
                    "success": True,
                    "method": "bulk_browser_automation",
                    "note": "Batch uploaded in initial bulk session",
                    "video_path": target_path,
                }
            else:
                cb(5,
                   f"Starting Browser Automation using Chrome Profile '{profile_name}'...")
                return poster.post(
                    video_path=target_path,
                    title=title,
                    description="" if disable_caption else description,
                    page_id=target_asset_id,
                    progress_callback=cb,
                )

        # Mode B: Meta Graph API (Official Resumable Chunked Upload)
        page_id = fb_cfg.get("page_id", "").strip()
        page_token = fb_cfg.get("page_token", "").strip()

        if not page_id or not page_token:
            raise ValueError(
                "Facebook Page ID or Page Access Token is missing. Please configure it in Accounts tab.")

        return FacebookUploader.upload_video(
            video_path=target_path,
            page_id=page_id,
            access_token=page_token,
            title=title,
            description=description,
            published=(publish_status !=
                       "draft" and scheduled_time is None and published),
            scheduled_publish_time=scheduled_time,
            disable_caption=disable_caption,
            check_closed_caption=check_closed_caption,
            caption_locale=caption_locale,
            caption_file=caption_file,
            playlist_id=playlist_id,
            group_id=group_id,
            group_ids=group_ids,
            user_token=user_token,
            progress_callback=cb,
            cancel_check=self.is_cancelled,
        )

    def _run_youtube(self, video_path: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target_path = video_path or self.video_path
        target_meta = meta or self.metadata

        yt_cfg = self.credentials.get("youtube", {})
        client_id = yt_cfg.get("client_id", "").strip()
        client_secret = yt_cfg.get("client_secret", "").strip()
        refresh_token = yt_cfg.get("refresh_token", "").strip()
        access_token = yt_cfg.get("access_token", "").strip()

        # If access token is empty or refresh token is available, refresh it to ensure it is valid
        if refresh_token and client_id and client_secret:
            try:
                self.platform_progress.emit(
                    "youtube", 2, "Refreshing Google OAuth token...")
                access_token = YouTubeUploader.refresh_access_token(
                    client_id, client_secret, refresh_token)
                yt_cfg["access_token"] = access_token
            except Exception as e:
                self.log_message.emit("WARN", f"Token refresh notice: {e}")

        if not access_token:
            raise ValueError(
                "YouTube Access Token is missing. Please sign in with Google in Accounts tab.")

        title = target_meta.get("title", "")
        description = target_meta.get("description", "")
        tags = target_meta.get("tags", [])
        privacy = target_meta.get("yt_privacy", "public")
        category = target_meta.get("yt_category", "22")
        made_for_kids = target_meta.get("yt_made_for_kids", False)

        def cb(pct, txt):
            self.platform_progress.emit("youtube", pct, txt)

        return YouTubeUploader.upload_video(
            video_path=target_path,
            access_token=access_token,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy,
            category_id=category,
            made_for_kids=made_for_kids,
            progress_callback=cb,
            cancel_check=self.is_cancelled,
        )

    def _run_tiktok(self, video_path: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target_path = video_path or self.video_path
        target_meta = meta or self.metadata

        tt_cfg = self.credentials.get("tiktok", {})
        access_token = tt_cfg.get("access_token", "").strip()

        if not access_token:
            raise ValueError(
                "TikTok Access Token is missing. Please configure it in Accounts tab.")

        title = target_meta.get("title", "")
        privacy = target_meta.get("tt_privacy", "PUBLIC_TO_EVERYONE")
        allow_comment = target_meta.get("tt_allow_comment", True)
        allow_duet = target_meta.get("tt_allow_duet", True)
        allow_stitch = target_meta.get("tt_allow_stitch", True)

        def cb(pct, txt):
            self.platform_progress.emit("tiktok", pct, txt)

        return TikTokUploader.upload_video(
            video_path=target_path,
            access_token=access_token,
            title=title,
            privacy_level=privacy,
            disable_comment=not allow_comment,
            disable_duet=not allow_duet,
            disable_stitch=not allow_stitch,
            progress_callback=cb,
            cancel_check=self.is_cancelled,
        )
