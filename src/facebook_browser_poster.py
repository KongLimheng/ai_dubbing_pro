# -*- coding: utf-8 -*-
"""
facebook_browser_poster.py - Standalone Browser Automation Video Poster for Facebook.

Allows posting videos directly to Facebook Pages / Meta Business Suite without
requiring any Meta Developer App, App Review, or Access Tokens.
Uses your existing logged-in Chrome Profile or saved session cookies.

Features:
- Direct video uploading via Meta Business Suite Composer
- Automatic title, caption, hashtags, and playlist filling
- Interactive login / profile setup mode
- Command-line interface and programmatic Python API
"""

import re
import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from typing import Optional, Dict, Any, List, Callable

DEFAULT_ASSET_ID = "364039971101203"
MBS_COMPOSER_URL = "https://business.facebook.com/latest/composer"
MBS_BULK_COMPOSER_URL = "https://business.facebook.com/latest/bulk_upload_composer"
FB_WATCH_URL = "https://www.facebook.com/watch"


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
    stem = os.path.splitext(os.path.basename(filename))[0]

    # Pattern 1: Explicit episode markers (e.g. Episode 05, Ep_05, Ep. 05, Part 05, Tap 05)
    m = re.search(
        r'(?:episode|ep|part|tap|tập)[\s._-]*([0-9]{1,4})\b', stem, re.IGNORECASE)
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


def format_video_description(
    template: str,
    title: str,
    episode_num: int,
    filename: str = "",
    extra_desc: str = "",
) -> str:
    """
    Format a dynamic video description using title, episode number, and optional template.
    Supported placeholders:
      {title}, {episode}, {ep}, {index}, {filename}
    If template is empty:
      Produces: "{title} Episode {episode_num}\n\n{extra_desc}" (or just title & ep if no extra_desc)
    """
    stem = os.path.splitext(os.path.basename(filename))[
        0] if filename else title
    clean_title = title.strip() or stem

    if template and any(k in template for k in ("{title}", "{episode}", "{ep}", "{index}", "{filename}")):
        desc = template.replace("{title}", clean_title)
        desc = desc.replace("{episode}", str(episode_num))
        desc = desc.replace("{ep}", str(episode_num))
        desc = desc.replace("{index}", str(episode_num))
        desc = desc.replace("{filename}", stem)
        return desc.strip()

    if extra_desc and any(k in extra_desc for k in ("{title}", "{episode}", "{ep}", "{index}", "{filename}")):
        desc = extra_desc.replace("{title}", clean_title)
        desc = desc.replace("{episode}", str(episode_num))
        desc = desc.replace("{ep}", str(episode_num))
        desc = desc.replace("{index}", str(episode_num))
        desc = desc.replace("{filename}", stem)
        return desc.strip()

    base = f"{clean_title} Episode {episode_num}"
    if extra_desc:
        return f"{base}\n\n{extra_desc.strip()}".strip()
    return base


def get_default_chrome_path() -> str:
    """Find the Google Chrome executable on the current system."""
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return "chrome.exe"
    elif sys.platform == "darwin":
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return path if os.path.exists(path) else "google-chrome"
    else:
        for bin_name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(bin_name)
            if found:
                return found
        return "/usr/bin/google-chrome"


def get_default_user_data_dir() -> str:
    """Find default Chrome User Data directory across platforms."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:
        return os.path.expanduser("~/.config/google-chrome")


def list_chrome_profiles(user_data_dir: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Discover all Chrome profiles in the given or default User Data directory.
    Reads Preferences to obtain custom profile names and Google accounts.
    Returns:
      [
        {"key": "Default", "name": "Default — user@gmail.com", "path": "..."},
        {"key": "Profile 2", "name": "Profile 2 (Creator) — page@gmail.com", "path": "..."}
      ]
    """
    base_dir = user_data_dir or get_default_user_data_dir()
    profiles = []
    if not os.path.exists(base_dir):
        return [{"key": "Default", "name": "Default", "path": ""}]

    candidate_keys = []
    try:
        for item in os.listdir(base_dir):
            if item == "Default" or (item.startswith("Profile ") and os.path.isdir(os.path.join(base_dir, item))):
                candidate_keys.append(item)
    except Exception:
        return [{"key": "Default", "name": "Default", "path": ""}]

    def sort_key(k: str):
        if k == "Default":
            return (0, 0)
        parts = k.split()
        if len(parts) > 1 and parts[1].isdigit():
            return (1, int(parts[1]))
        return (1, 999)

    candidate_keys.sort(key=sort_key)

    for key in candidate_keys:
        p_path = os.path.join(base_dir, key)
        pref_file = os.path.join(p_path, "Preferences")
        disp_name = key
        gmail = ""

        if os.path.exists(pref_file):
            try:
                with open(pref_file, "r", encoding="utf-8", errors="ignore") as f:
                    pref_data = json.load(f)
                custom_name = pref_data.get("profile", {}).get("name", "")
                if custom_name and custom_name != key:
                    disp_name = f"{key} ({custom_name})"

                accs = pref_data.get("account_info", [])
                if accs and isinstance(accs, list) and len(accs) > 0:
                    gmail = accs[0].get("email", "")
                if not gmail:
                    gmail = pref_data.get("signin", {}).get(
                        "allowed_username", "")
            except Exception:
                pass

        label = f"{disp_name} — {gmail}" if gmail else disp_name
        profiles.append({"key": key, "name": label, "path": p_path})

    return profiles or [{"key": "Default", "name": "Default", "path": ""}]


def is_playwright_ready() -> bool:
    """Check if Playwright is installed in the current environment."""
    try:
        import playwright
        return True
    except ImportError:
        return False


def install_playwright(callback: Optional[Callable] = None) -> bool:
    """
    Attempt to install playwright into the environment via uv pip or python -m pip.
    """
    def log(msg: str):
        if callback:
            callback(msg)
        print(f"[PLAYWRIGHT INSTALL] {msg}")

    log("Installing playwright package...")
    uv_bin = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if os.path.exists(uv_bin):
        cmd = [uv_bin, "pip", "install", "--python",
               sys.executable, "playwright"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "playwright"]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=120)
        if proc.returncode != 0:
            log(f"Failed to install playwright package: {proc.stderr}")
            return False

        log("Installing chromium browser binaries...")
        cmd_browsers = [sys.executable, "-m",
                        "playwright", "install", "chromium"]
        proc2 = subprocess.run(cmd_browsers, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, timeout=180)
        if proc2.returncode != 0:
            log(f"Notice on browser binaries: {proc2.stderr}")
        log("Playwright installation completed successfully!")
        return True
    except Exception as e:
        log(f"Installation error: {e}")
        return False


class FacebookBrowserPoster:
    """
    Automated browser posting engine for Meta Business Suite & Facebook.
    Leverages persistent browser sessions to publish videos without API tokens.
    """

    MBS_COMPOSER_URL = "https://business.facebook.com/latest/composer"
    MBS_BULK_COMPOSER_URL = "https://business.facebook.com/latest/bulk_upload_composer"
    DEFAULT_ASSET_ID = "364039971101203"
    FB_WATCH_URL = "https://www.facebook.com/watch"

    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        profile_name: str = "Default",
        chrome_path: Optional[str] = None,
        headless: bool = False,
    ):
        self.user_data_dir = user_data_dir or get_default_user_data_dir()
        self.profile_name = profile_name
        self.chrome_path = chrome_path or get_default_chrome_path()
        self.headless = headless

    def get_profile_storage_dir(self) -> str:
        """
        Returns the unified persistent browser storage directory for this profile.
        Both interactive login ('Open Chrome to Login') and automated upload share this
        EXACT same directory, eliminating guest profiles and ProcessSingleton lock conflicts.
        """
        base_dir = os.path.join(self.user_data_dir, "ai_dubber_profiles")
        prof_dir = os.path.join(base_dir, self.profile_name)
        os.makedirs(prof_dir, exist_ok=True)
        return prof_dir

    def get_storage_state_path(self) -> str:
        """Path to exported Playwright storage state JSON (cookies & localStorage)."""
        return os.path.join(self.get_profile_storage_dir(), "facebook_storage_state.json")

    def check_session_status(self) -> Dict[str, Any]:
        """
        Check if the profile has active Facebook session cookies without opening a browser.
        Returns:
            {"logged_in": bool, "user_id": str, "cookies_count": int, "status_text": str}
        """
        state_file = self.get_storage_state_path()
        if not os.path.exists(state_file):
            return {
                "logged_in": False,
                "user_id": "",
                "cookies_count": 0,
                "status_text": "No saved session (Please click 'Open Chrome to Login')",
            }
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies", [])
            fb_cookies = [
                c for c in cookies if "facebook.com" in c.get("domain", "")]
            c_user = next((c["value"]
                          for c in fb_cookies if c.get("name") == "c_user"), "")
            xs = next((c["value"]
                      for c in fb_cookies if c.get("name") == "xs"), "")
            is_valid = bool(c_user and xs)
            status_text = f"Logged in (UID: {c_user})" if is_valid else (
                f"Has {len(fb_cookies)} cookie(s)" if fb_cookies else "Not logged in")
            return {
                "logged_in": is_valid,
                "user_id": c_user,
                "cookies_count": len(fb_cookies),
                "status_text": status_text,
            }
        except Exception as e:
            return {
                "logged_in": False,
                "user_id": "",
                "cookies_count": 0,
                "status_text": f"Error reading session: {e}",
            }

    def launch_profile_for_login(
        self,
        target_url: str = MBS_COMPOSER_URL,
        on_status_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Launch an interactive headful browser session pointing to the dedicated
        profile storage directory so the user can log into Facebook / Meta Business Suite.
        Once the user logs in or closes the window, session cookies are exported to
        facebook_storage_state.json and persisted in the unified profile directory.
        """
        def log(msg: str):
            if on_status_callback:
                on_status_callback(msg)
            print(f"[*] {msg}")

        profile_dir = self.get_profile_storage_dir()
        state_file = self.get_storage_state_path()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("Playwright not installed, falling back to subprocess Chrome...")
            cmd = [
                self.chrome_path,
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                target_url,
            ]
            proc = subprocess.Popen(cmd)
            return {"process": proc, "pid": proc.pid, "profile_dir": profile_dir}

        log(
            f"Launching interactive browser for profile '{self.profile_name}'...")
        with sync_playwright() as p:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                executable_path=self.chrome_path if os.path.exists(
                    self.chrome_path) else None,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--start-maximized",
                ],
                viewport=None,
            )

            # If previous storage state exists, inject cookies
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        saved_state = json.load(f)
                    if saved_state.get("cookies"):
                        browser_context.add_cookies(saved_state["cookies"])
                except Exception:
                    pass

            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page(
            )

            log(f"Navigating to {target_url}...")
            try:
                page.goto(target_url, wait_until="domcontentloaded",
                          timeout=60000)
            except Exception as e:
                log(f"Page navigation notice: {e}")

            log("Browser is open. Please log into Facebook / Meta Business Suite in the opened window.")
            log("Once logged in, your session is saved automatically. Close the browser when done.")

            # Monitor loop until user closes page or browser
            try:
                while True:
                    if page.is_closed() or not browser_context.pages:
                        break
                    # Periodically save storage state if logged in
                    try:
                        cookies = browser_context.cookies()
                        has_user = any(c.get(
                            "name") == "c_user" for c in cookies if "facebook.com" in c.get("domain", ""))
                        if has_user:
                            browser_context.storage_state(path=state_file)
                    except Exception:
                        pass
                    time.sleep(1)
            except Exception:
                pass

            # Final save before closing context
            try:
                browser_context.storage_state(path=state_file)
                log(f"✅ Session state successfully saved to {state_file}")
            except Exception:
                pass

            browser_context.close()

        session_info = self.check_session_status()
        log(f"Session status: {session_info.get('status_text', 'Ready')}")
        return session_info

    def _handle_checkpoint_or_login(
        self,
        page,
        browser_context,
        target_url: str,
        report: Callable[[int, str], None],
        p_instance: Any,
    ):
        """
        Detects if redirected to Facebook login or security checkpoint.
        If running headless, automatically switches to a visible headful Chrome window
        so the user can complete verification. Waits up to 120s, then immediately saves
        the updated storage state cookies to facebook_storage_state.json and returns
        the active (browser_context, page).
        """
        cur_url = getattr(page, "url", "")
        if "login" not in cur_url and "checkpoint" not in cur_url:
            return browser_context, page

        report(20, "⚠️ Action Required: Facebook login or 2FA checkpoint detected!")
        profile_dir = self.get_profile_storage_dir()
        state_file = self.get_storage_state_path()

        if self.headless and p_instance is not None:
            report(
                22,
                "🌐 Security checkpoint detected in background mode. Opening visible Chrome window for verification..."
            )
            try:
                browser_context.close()
            except Exception:
                pass

            browser_context = p_instance.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                executable_path=self.chrome_path if os.path.exists(
                    self.chrome_path) else None,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--start-maximized",
                ],
                viewport=None,
            )

            # Restore cookies if present
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        saved_state = json.load(f)
                    if saved_state.get("cookies"):
                        browser_context.add_cookies(saved_state["cookies"])
                except Exception:
                    pass

            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page(
            )
            try:
                page.goto(target_url, wait_until="domcontentloaded",
                          timeout=60000)
            except Exception:
                pass

        report(25, "🔑 Please complete Facebook login / checkpoint in the opened Chrome window (waiting up to 120s)...")
        print(
            "[!] Facebook checkpoint/login detected. Waiting up to 120s for completion...")

        try:
            page.wait_for_url(
                lambda u: "login" not in u and "checkpoint" not in u,
                timeout=120000,
            )
            time.sleep(3)
        except Exception as e:
            raise RuntimeError(
                "Facebook login / checkpoint was not completed within the time limit. "
                "Please click 'Open Chrome to Log In / Check Session' in the Social Post window to verify your account."
            ) from e

        # Immediately lock in newly authenticated cookies!
        try:
            browser_context.storage_state(path=state_file)
            report(28, "✅ Facebook checkpoint cleared & session cookies saved!")
        except Exception as e:
            print(f"[!] Notice: Could not save storage state immediately: {e}")

        return browser_context, page

    def upload_video_via_playwright(
        self,
        video_path: str,
        title: str = "",
        description: str = "",
        page_id: str = "",
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Automates video upload using Playwright with persistent context.
        Requires: pip install playwright && playwright install chromium
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium\n"
                "Or use the Meta Graph API uploader with 1-Click Permanent Token."
            )

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        abs_video_path = os.path.abspath(video_path)

        def report(pct: int, msg: str):
            if progress_callback:
                progress_callback(pct, msg)
            print(f"[{pct}%] {msg}")

        report(5, "Starting browser session with Chrome profile...")

        raw_page_id = str(page_id).strip() if page_id else ""
        if raw_page_id in ("12345", "mock_page_id", "test_page_123"):
            raw_page_id = DEFAULT_ASSET_ID
        composer_url = f"{self.MBS_COMPOSER_URL}?asset_id={raw_page_id}" if raw_page_id else self.MBS_COMPOSER_URL

        with sync_playwright() as p:
            # Launch persistent browser context pointing to the unified user profile
            profile_dir = self.get_profile_storage_dir()
            state_file = self.get_storage_state_path()

            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                executable_path=self.chrome_path if os.path.exists(
                    self.chrome_path) else None,
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--start-maximized",
                ],
                viewport=None,
            )

            # Restore cookies from storage state if present
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        saved_state = json.load(f)
                    if saved_state.get("cookies"):
                        browser_context.add_cookies(saved_state["cookies"])
                except Exception:
                    pass

            try:
                page = browser_context.pages[0] if browser_context.pages else browser_context.new_page(
                )

                report(15, f"Navigating to Meta Business Suite Composer...")
                page.goto(composer_url,
                          wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)

                # Check if logged in or redirected to login / checkpoint (auto headful fallback)
                browser_context, page = self._handle_checkpoint_or_login(
                    page, browser_context, composer_url, report, p
                )

                report(30, "Locating video upload button...")

                # Look for file input or video upload button
                file_input = page.query_selector('input[type="file"]')
                if not file_input:
                    # Look for 'Add Video' button that activates file chooser
                    add_btn = page.query_selector(
                        'div[role="button"]:has-text("Add video"), div[role="button"]:has-text("Upload video")')
                    if add_btn:
                        with page.expect_file_chooser(timeout=30000) as fc_info:
                            add_btn.click()
                        file_chooser = fc_info.value
                        file_chooser.set_files(abs_video_path)
                    else:
                        raise RuntimeError(
                            "Could not find video upload input on Meta Business Suite Composer.")
                else:
                    file_input.set_input_files(abs_video_path)

                report(50, "Video selected. Waiting for upload processing...")
                time.sleep(5)

                # Set Title if input exists
                if title:
                    report(60, f"Filling title: {title[:40]}...")
                    title_input = page.query_selector(
                        'input[placeholder*="title" i], textarea[placeholder*="title" i]')
                    if title_input:
                        title_input.fill(title)

                # Set Description / Caption
                if description:
                    report(70, f"Filling caption/description...")
                    desc_input = page.query_selector(
                        'div[role="textbox"][contenteditable="true"], textarea[placeholder*="text" i]')
                    if desc_input:
                        desc_input.click()
                        desc_input.fill(description)

                report(85, "Waiting for upload progress completion...")
                # Wait until upload reaches 100% or publish button is enabled
                publish_btn = page.wait_for_selector(
                    'div[role="button"]:has-text("Publish"), button:has-text("Publish")',
                    timeout=90000
                )

                if publish_btn:
                    report(95, "Clicking Publish button...")
                    publish_btn.click()
                    time.sleep(5)
                    report(
                        100, "✅ Successfully published video to Facebook via Browser Automation!")
                    return {
                        "success": True,
                        "method": "browser_automation",
                        "video_path": abs_video_path,
                        "title": title,
                    }
                else:
                    raise RuntimeError(
                        "Publish button could not be located or was disabled.")

            finally:
                try:
                    browser_context.storage_state(path=state_file)
                except Exception:
                    pass
                browser_context.close()

    def upload_bulk_videos_via_playwright(
        self,
        video_paths: List[str],
        title: str = "",
        description: str = "",
        asset_id: str = DEFAULT_ASSET_ID,
        playlist: str = "",
        disable_caption: bool = True,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Automates bulk video upload via Meta Business Suite's Bulk Upload Composer:
        https://business.facebook.com/latest/bulk_upload_composer?asset_id={asset_id}

        Workflow:
        1. Navigate to bulk_upload_composer with asset_id.
        2. Upload all video paths in parallel/batch.
        3. Fill dynamic descriptions based on video title & extracted episode number.
        4. Click 'Optimize' tab -> uncheck 'Caption' / auto-generated captions.
        5. Click 'Publish' / 'Share' tab -> switch ON 'Add to playlist' -> select target playlist.
        6. Click 'Save' / 'Publish' button.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium\n"
                "Or use the Meta Graph API uploader with 1-Click Permanent Token."
            )

        if not video_paths:
            raise ValueError("No video paths provided for bulk upload.")

        valid_paths = [os.path.abspath(p)
                       for p in video_paths if os.path.exists(p)]
        if not valid_paths:
            raise FileNotFoundError(
                f"None of the provided video files exist: {video_paths}")

        def report(pct: int, msg: str):
            if progress_callback:
                progress_callback(pct, msg)
            print(f"[{pct}%] {msg}")

        raw_asset = str(asset_id).strip() if asset_id is not None else ""
        if not raw_asset or raw_asset in ("12345", "mock_page_id", "test_page_123"):
            target_asset_id = DEFAULT_ASSET_ID
        else:
            target_asset_id = raw_asset
        bulk_url = f"{self.MBS_BULK_COMPOSER_URL}?asset_id={target_asset_id}"

        report(
            5, f"Starting browser session with Chrome Profile '{self.profile_name}'...")

        with sync_playwright() as p:
            profile_dir = self.get_profile_storage_dir()
            state_file = self.get_storage_state_path()

            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                executable_path=self.chrome_path if os.path.exists(
                    self.chrome_path) else None,
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--start-maximized",
                ],
                viewport=None,
            )

            # Restore cookies from storage state if present
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        saved_state = json.load(f)
                    if saved_state.get("cookies"):
                        browser_context.add_cookies(saved_state["cookies"])
                except Exception:
                    pass

            try:
                page = browser_context.pages[0] if browser_context.pages else browser_context.new_page(
                )

                report(
                    15, f"Opening Meta Bulk Composer (Asset ID: {target_asset_id})...")
                page.goto(bulk_url, wait_until="domcontentloaded",
                          timeout=60000)
                time.sleep(3)

                # Check if logged in or redirected to login / checkpoint (auto headful fallback)
                browser_context, page = self._handle_checkpoint_or_login(
                    page, browser_context, bulk_url, report, p
                )

                report(
                    30, f"Uploading {len(valid_paths)} video(s) to Bulk Composer...")

                file_input = page.query_selector('input[type="file"]')
                if not file_input:
                    add_btn = page.query_selector(
                        'div[role="button"]:has-text("Upload videos"), div[role="button"]:has-text("Upload video"), '
                        'div[role="button"]:has-text("Add videos"), div[role="button"]:has-text("Add video"), '
                        'button:has-text("Upload videos"), button:has-text("Add videos"), button:has-text("Add video")'
                    )
                    if add_btn:
                        with page.expect_file_chooser(timeout=30000) as fc_info:
                            add_btn.click()
                        fc = fc_info.value
                        fc.set_files(valid_paths)
                    else:
                        raise RuntimeError(
                            "Could not find video upload input on Meta Business Suite Bulk Composer.")
                else:
                    file_input.set_input_files(valid_paths)

                report(
                    45, f"Videos uploaded. Waiting for processing cards to render...")
                time.sleep(6)

                # Fill dynamic descriptions
                report(55, "Injecting dynamic descriptions (Title + Episode #)...")
                desc_boxes = page.query_selector_all(
                    'div[role="textbox"][contenteditable="true"], textarea[placeholder*="text" i], textarea[placeholder*="description" i]'
                )
                for idx, v_path in enumerate(valid_paths, 1):
                    ep_num = extract_episode_number(v_path, fallback_idx=idx)
                    stem = os.path.splitext(os.path.basename(v_path))[0]
                    v_title = title or stem
                    dyn_desc = format_video_description(
                        template="",
                        title=v_title,
                        episode_num=ep_num,
                        filename=v_path,
                        extra_desc=description,
                    )
                    if idx <= len(desc_boxes):
                        try:
                            box = desc_boxes[idx - 1]
                            box.click()
                            box.fill(dyn_desc)
                        except Exception:
                            pass
                    elif len(desc_boxes) == 1:
                        try:
                            desc_boxes[0].click()
                            desc_boxes[0].fill(dyn_desc)
                        except Exception:
                            pass

                # Step 4: Click 'Optimize' Tab & Uncheck 'Caption'
                report(65, "Navigating to 'Optimize' tab & unchecking Caption...")
                try:
                    optimize_tab = page.query_selector(
                        '[role="tab"]:has-text("Optimize"), [role="tab"]:has-text("Optimise"), '
                        'button:has-text("Optimize"), div[role="button"]:has-text("Optimize"), '
                        'span:has-text("Optimize")'
                    )
                    if optimize_tab:
                        optimize_tab.click()
                        time.sleep(2)

                    if disable_caption:
                        caption_nodes = page.query_selector_all(
                            'label:has-text("Caption"), div:has-text("Caption"), span:has-text("Caption"), '
                            '[aria-label*="caption" i], [aria-label*="Caption" i]'
                        )
                        caption_unturned = False
                        for node in caption_nodes:
                            chk = node.query_selector('input[type="checkbox"]')
                            if chk and chk.is_checked():
                                chk.click()
                                caption_unturned = True
                                break
                            aria_checked = node.get_attribute("aria-checked")
                            if aria_checked == "true":
                                node.click()
                                caption_unturned = True
                                break
                            sub_sw = node.query_selector(
                                '[role="checkbox"], [role="switch"]')
                            if sub_sw and sub_sw.get_attribute("aria-checked") == "true":
                                sub_sw.click()
                                caption_unturned = True
                                break

                        if caption_unturned:
                            report(
                                72, "Auto-generated Caption successfully unchecked/disabled.")
                        else:
                            report(
                                72, "Caption toggle was already disabled or not present.")
                except Exception as opt_err:
                    report(72, f"Note on Optimize tab: {opt_err}")

                # Step 5: Click 'Publish' tab -> Switch ON 'Add to playlist' -> Choose playlist
                report(78, "Navigating to 'Publish' tab...")
                try:
                    publish_tab = page.query_selector(
                        '[role="tab"]:has-text("Publish"), [role="tab"]:has-text("Share"), '
                        'button:has-text("Publish"), div[role="button"]:has-text("Publish"), '
                        'span:has-text("Publish")'
                    )
                    if publish_tab:
                        publish_tab.click()
                        time.sleep(2)

                    if playlist and not str(playlist).startswith("(None"):
                        report(
                            82, f"Toggling 'Add to playlist' switch for '{playlist}'...")
                        pl_switches = page.query_selector_all(
                            'label:has-text("Add to playlist"), div:has-text("Add to playlist"), '
                            'span:has-text("Add to playlist"), [aria-label*="playlist" i]'
                        )
                        pl_toggled_on = False
                        for psw in pl_switches:
                            chk = psw.query_selector('input[type="checkbox"]')
                            if chk:
                                if not chk.is_checked():
                                    chk.click()
                                pl_toggled_on = True
                                break
                            aria_checked = psw.get_attribute("aria-checked")
                            if aria_checked is not None:
                                if aria_checked != "true":
                                    psw.click()
                                pl_toggled_on = True
                                break
                            sub = psw.query_selector(
                                '[role="checkbox"], [role="switch"]')
                            if sub:
                                if sub.get_attribute("aria-checked") != "true":
                                    sub.click()
                                pl_toggled_on = True
                                break

                        time.sleep(2)
                        report(
                            86, f"Selecting playlist '{playlist}' from dropdown...")
                        pl_dropdown = page.query_selector(
                            'div[role="combobox"], div[role="button"]:has-text("Select"), '
                            'div[role="button"]:has-text("Choose"), input[placeholder*="playlist" i]'
                        )
                        if pl_dropdown:
                            pl_dropdown.click()
                            time.sleep(1)
                            opt = page.query_selector(
                                f'[role="option"]:has-text("{playlist}"), div[role="listbox"] div:has-text("{playlist}"), '
                                f'span:has-text("{playlist}"), li:has-text("{playlist}")'
                            )
                            if opt:
                                opt.click()
                            else:
                                page.keyboard.type(playlist)
                                time.sleep(0.5)
                                page.keyboard.press("Enter")
                except Exception as pub_err:
                    report(88, f"Note on Playlist configuration: {pub_err}")

                # Step 6: Click 'Save' / 'Publish'
                report(92, "Locating Save / Publish button...")
                save_btn = page.wait_for_selector(
                    'button:has-text("Save"), div[role="button"]:has-text("Save"), '
                    'button:has-text("Publish"), div[role="button"]:has-text("Publish")',
                    timeout=60000
                )

                if save_btn:
                    report(96, "Clicking Save / Publish button...")
                    save_btn.click()
                    time.sleep(6)
                    report(
                        100, f"✅ Successfully published {len(valid_paths)} bulk video(s) via Meta Bulk Composer!")
                    return {
                        "success": True,
                        "method": "bulk_browser_automation",
                        "video_count": len(valid_paths),
                        "video_paths": valid_paths,
                        "asset_id": target_asset_id,
                        "playlist": playlist,
                        "url": bulk_url,
                    }
                else:
                    raise RuntimeError(
                        "Could not find or click the Save/Publish button in Bulk Upload Composer.")

            finally:
                try:
                    browser_context.storage_state(path=state_file)
                except Exception:
                    pass
                browser_context.close()

    def post(
        self,
        video_path: str,
        title: str = "",
        description: str = "",
        page_id: str = "",
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """High-level post interface for single video."""
        return self.upload_video_via_playwright(
            video_path=video_path,
            title=title,
            description=description,
            page_id=page_id,
            progress_callback=progress_callback,
        )

    def bulk_post(
        self,
        video_paths: List[str],
        title: str = "",
        description: str = "",
        asset_id: str = DEFAULT_ASSET_ID,
        playlist: str = "",
        disable_caption: bool = True,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """High-level bulk post interface for Meta Business Suite Bulk Upload Composer."""
        return self.upload_bulk_videos_via_playwright(
            video_paths=video_paths,
            title=title,
            description=description,
            asset_id=asset_id,
            playlist=playlist,
            disable_caption=disable_caption,
            progress_callback=progress_callback,
        )


def main():
    """Command-line interface for facebook_browser_poster."""
    parser = argparse.ArgumentParser(
        description="Facebook Browser Automation Video Poster (Zero Meta App / Zero Token Required)"
    )
    parser.add_argument("--video", type=str, default="",
                        help="Path to MP4/MKV video file to upload")
    parser.add_argument("--videos", nargs="+", default=[],
                        help="Multiple video paths for bulk posting")
    parser.add_argument("--bulk", action="store_true",
                        help="Use Meta Business Suite Bulk Upload Composer")
    parser.add_argument("--asset-id", type=str, default=DEFAULT_ASSET_ID,
                        help=f"Meta Business Suite Asset ID (default: {DEFAULT_ASSET_ID})")
    parser.add_argument("--playlist", type=str, default="",
                        help="Playlist name to add video(s) to")
    parser.add_argument("--disable-caption", action="store_true", default=True,
                        help="Uncheck auto-generated captions in Optimize tab")
    parser.add_argument("--title", type=str, default="",
                        help="Video post title")
    parser.add_argument("--description", type=str, default="",
                        help="Video caption or description")
    parser.add_argument("--page-id", type=str, default="",
                        help="Facebook Page ID (optional)")
    parser.add_argument("--profile-dir", type=str, default="",
                        help="Chrome User Data directory")
    parser.add_argument("--profile-name", type=str, default="Default",
                        help="Chrome profile folder name (e.g. 'Default', 'Profile 1')")
    parser.add_argument("--chrome-path", type=str, default="",
                        help="Path to Chrome executable")
    parser.add_argument("--headless", action="store_true",
                        help="Run browser headlessly")
    parser.add_argument("--login", action="store_true",
                        help="Launch Chrome in interactive mode to log in to Facebook")

    args = parser.parse_args()

    poster = FacebookBrowserPoster(
        user_data_dir=args.profile_dir or None,
        profile_name=args.profile_name,
        chrome_path=args.chrome_path or None,
        headless=args.headless,
    )

    if args.login:
        target_url = f"{MBS_BULK_COMPOSER_URL}?asset_id={args.asset_id or DEFAULT_ASSET_ID}" if args.bulk else MBS_COMPOSER_URL
        print(
            f"[*] Opening Chrome profile for interactive Facebook login ({target_url})...")
        proc = poster.launch_profile_for_login(target_url=target_url)
        print(
            f"[*] Chrome launched (PID: {proc.pid}). Log into Facebook and close the browser when done.")
        return

    # Determine bulk mode vs single video
    bulk_files = args.videos or (
        [args.video] if args.video and args.bulk else [])
    if args.bulk or len(bulk_files) > 1:
        if not bulk_files and args.video:
            bulk_files = [args.video]
        if not bulk_files:
            parser.print_help()
            print(
                "\n[!] Error: --videos <paths...> or --video <path> required for bulk mode.")
            sys.exit(1)

        try:
            res = poster.bulk_post(
                video_paths=bulk_files,
                title=args.title,
                description=args.description,
                asset_id=args.asset_id or args.page_id or DEFAULT_ASSET_ID,
                playlist=args.playlist,
                disable_caption=args.disable_caption,
            )
            print(json.dumps(res, indent=2))
        except Exception as e:
            print(f"[!] Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.video:
        parser.print_help()
        print(
            "\n[!] Error: --video <path> is required when not using --login or --bulk.")
        sys.exit(1)

    try:
        res = poster.post(
            video_path=args.video,
            title=args.title,
            description=args.description,
            page_id=args.page_id,
        )
        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
