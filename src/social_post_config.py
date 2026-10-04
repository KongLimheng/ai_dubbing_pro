# -*- coding: utf-8 -*-
"""
social_post_config.py - Persistent configuration management for Social Post features.
Handles credential storage, default metadata, and publishing history in .app_config.json.
"""

import time
from typing import Dict, List, Any
import settings_manager


def get_social_config() -> Dict[str, Any]:
    """Retrieve all social posting configuration from the global config."""
    cfg = settings_manager.read_config()
    social_cfg = cfg.get("social_post", {})
    if not isinstance(social_cfg, dict):
        social_cfg = {}
    return social_cfg


def save_social_config(social_data: Dict[str, Any]) -> bool:
    """Save updated social posting configuration back to .app_config.json."""
    if not isinstance(social_data, dict):
        return False
    current = get_social_config()
    current.update(social_data)
    return settings_manager.write_config({"social_post": current})


# ── Facebook Configuration ───────────────────────────────────────────────────

def get_facebook_config() -> Dict[str, Any]:
    """Get Facebook Page posting configuration."""
    cfg = get_social_config()
    fb = cfg.get("facebook", {})
    if not isinstance(fb, dict):
        fb = {}
    return {
        "page_id": fb.get("page_id", ""),
        "page_name": fb.get("page_name", ""),
        "page_token": fb.get("page_token", ""),
        "user_token": fb.get("user_token", ""),
        "app_id": fb.get("app_id", ""),
        "app_secret": fb.get("app_secret", ""),
        "token_status": fb.get("token_status", ""),
        "is_permanent": fb.get("is_permanent", False),
        "post_method": fb.get("post_method", "graph_api"),
        "browser_profile": fb.get("browser_profile", "Default"),
        "browser_user_data_dir": fb.get("browser_user_data_dir", ""),
        "browser_headless": fb.get("browser_headless", False),
        "browser_asset_id": fb.get("browser_asset_id", ""),
        "published": fb.get("published", True),
        "publish_status": fb.get("publish_status", "publish_now"),  # "publish_now" | "schedule" | "draft"
        "schedule_time": fb.get("schedule_time", ""),
        "schedule_interval_minutes": fb.get("schedule_interval_minutes", 60),
        "disable_caption": fb.get("disable_caption", False),
        "playlist_id": fb.get("playlist_id", ""),
        "playlist_title": fb.get("playlist_title", ""),
        "group_id": fb.get("group_id", ""),
        "group_name": fb.get("group_name", ""),
        "selected_group_ids": fb.get("selected_group_ids", []),
        "selected_group_names": fb.get("selected_group_names", []),
        "cached_playlists": fb.get("cached_playlists", []),
        "cached_groups": fb.get("cached_groups", []),
        "custom_groups": fb.get("custom_groups", []),
        "custom_playlists": fb.get("custom_playlists", []),
        "closed_caption_enabled": fb.get("closed_caption_enabled", True),
        "closed_caption_locale": fb.get("closed_caption_locale", "en_US"),
    }


def save_facebook_config(data: Dict[str, Any]) -> bool:
    """Save Facebook Page posting configuration."""
    cfg = get_social_config()
    fb = cfg.get("facebook", {})
    if not isinstance(fb, dict):
        fb = {}
    fb.update(data)
    return save_social_config({"facebook": fb})


def get_last_selected_folder() -> str:
    """Get the last folder chosen for batch video posting."""
    cfg = get_social_config()
    return cfg.get("last_selected_folder", "")


def save_last_selected_folder(folder_path: str) -> bool:
    """Save the last folder chosen for batch video posting."""
    return save_social_config({"last_selected_folder": folder_path})


# ── YouTube Configuration ────────────────────────────────────────────────────

def get_youtube_config() -> Dict[str, Any]:
    """Get YouTube channel posting configuration."""
    cfg = get_social_config()
    yt = cfg.get("youtube", {})
    if not isinstance(yt, dict):
        yt = {}
    return {
        "client_id": yt.get("client_id", ""),
        "client_secret": yt.get("client_secret", ""),
        "refresh_token": yt.get("refresh_token", ""),
        "access_token": yt.get("access_token", ""),
        "channel_title": yt.get("channel_title", ""),
        "channel_id": yt.get("channel_id", ""),
        "default_privacy": yt.get("default_privacy", "public"),  # public, unlisted, private
        "default_category": yt.get("default_category", "22"),     # 22 = People & Blogs, 24 = Entertainment
        "made_for_kids": yt.get("made_for_kids", False),
    }


def save_youtube_config(data: Dict[str, Any]) -> bool:
    """Save YouTube channel posting configuration."""
    cfg = get_social_config()
    yt = cfg.get("youtube", {})
    if not isinstance(yt, dict):
        yt = {}
    yt.update(data)
    return save_social_config({"youtube": yt})


# ── TikTok Configuration ─────────────────────────────────────────────────────

def get_tiktok_config() -> Dict[str, Any]:
    """Get TikTok posting configuration."""
    cfg = get_social_config()
    tt = cfg.get("tiktok", {})
    if not isinstance(tt, dict):
        tt = {}
    return {
        "client_key": tt.get("client_key", ""),
        "client_secret": tt.get("client_secret", ""),
        "access_token": tt.get("access_token", ""),
        "refresh_token": tt.get("refresh_token", ""),
        "creator_name": tt.get("creator_name", ""),
        "default_privacy": tt.get("default_privacy", "PUBLIC_TO_EVERYONE"),
        "allow_comment": tt.get("allow_comment", True),
        "allow_duet": tt.get("allow_duet", True),
        "allow_stitch": tt.get("allow_stitch", True),
    }


def save_tiktok_config(data: Dict[str, Any]) -> bool:
    """Save TikTok posting configuration."""
    cfg = get_social_config()
    tt = cfg.get("tiktok", {})
    if not isinstance(tt, dict):
        tt = {}
    tt.update(data)
    return save_social_config({"tiktok": tt})


# ── Publishing Defaults & Templates ──────────────────────────────────────────

def get_social_defaults() -> Dict[str, Any]:
    """Get default title/description templates and hashtags."""
    cfg = get_social_config()
    defaults = cfg.get("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}
    return {
        "title_template": defaults.get("title_template", ""),
        "description_template": defaults.get("description_template", ""),
        "default_tags": defaults.get("default_tags", "#dubbing #shorts #reels #viral"),
        "post_facebook": defaults.get("post_facebook", True),
        "post_youtube": defaults.get("post_youtube", True),
        "post_tiktok": defaults.get("post_tiktok", True),
    }


def save_social_defaults(data: Dict[str, Any]) -> bool:
    """Save default metadata and platform selection."""
    cfg = get_social_config()
    defaults = cfg.get("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}
    defaults.update(data)
    return save_social_config({"defaults": defaults})


# ── Publishing History ───────────────────────────────────────────────────────

def get_upload_history() -> List[Dict[str, Any]]:
    """Get list of past upload entries, newest first."""
    cfg = get_social_config()
    history = cfg.get("history", [])
    if not isinstance(history, list):
        history = []
    return history


def add_upload_history_entry(entry: Dict[str, Any]) -> bool:
    """
    Append an upload record to history (retains last 100 entries).
    entry format:
    {
        "id": "...",
        "timestamp": 1234567890,
        "datetime": "2026-09-30 14:00:00",
        "video_name": "sample.mp4",
        "video_path": "/path/to/sample.mp4",
        "title": "Title here",
        "platforms": {
            "facebook": {"success": True, "url": "...", "id": "..."},
            "youtube": {"success": True, "url": "...", "id": "..."},
            "tiktok": {"success": True, "url": "...", "id": "..."}
        }
    }
    """
    history = get_upload_history()
    if not entry.get("timestamp"):
        entry["timestamp"] = time.time()
    if not entry.get("datetime"):
        entry["datetime"] = time.strftime("%Y-%m-%d %H:%M:%S")

    history.insert(0, entry)
    history = history[:100]  # Cap at 100 records
    return save_social_config({"history": history})


def clear_upload_history() -> bool:
    """Clear past upload history records."""
    return save_social_config({"history": []})
