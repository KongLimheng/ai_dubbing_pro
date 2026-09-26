import json
import os
import sys
from runtime_paths import app_path


class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_index = 0
        self.failed_proxies = set()
        self.enabled = False
        self.load_proxies()

    def load_proxies(self):
        self.proxies = []
        self.current_index = 0
        self.failed_proxies.clear()
        self.enabled = False

        config = get_proxy_config()
        self.enabled = bool(config.get("enabled", config.get("proxy_enabled", False)))
        if not self.enabled:
            return

        proxy_str = config.get("proxy_list", "")
        if not proxy_str:
            return

        lines = [p.strip() for p in proxy_str.split("\n") if p.strip()]
        for line in lines:
            if not line.startswith(("http://", "https://", "socks")):
                line = f"http://{line}"
            self.proxies.append(line)

        # Allow None as a direct fallback
        if self.proxies and None not in self.proxies:
            self.proxies.append(None)

    def get_next_proxy(self):
        if not self.proxies:
            return None

        attempts = 0
        max_attempts = len(self.proxies)

        while attempts < max_attempts:
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)

            if proxy not in self.failed_proxies:
                return proxy

            attempts += 1

        print("[PROXY] All proxies failed, resetting failed list")
        self.failed_proxies.clear()
        return self.proxies[0] if self.proxies else None

    def mark_proxy_failed(self, proxy):
        if proxy:
            self.failed_proxies.add(proxy)
            print(f"[PROXY] Marked as failed: {proxy}")

    def reset_failures(self):
        self.failed_proxies.clear()


class ProxyConfig(dict):
    """
    A dictionary wrapper for proxy configuration that safely handles
    both 'enabled' and 'proxy_enabled' keys, avoiding KeyError.
    """
    def __getitem__(self, key):
        if key in self:
            return super().__getitem__(key)
        if key in ("enabled", "proxy_enabled"):
            return super().get("enabled", super().get("proxy_enabled", False))
        return None

    def get(self, key, default=None):
        if key in ("enabled", "proxy_enabled"):
            val = super().get("enabled", super().get("proxy_enabled", default))
            return val if val is not None else default
        return super().get(key, default)


def get_proxy_config():
    try:
        from settings_manager import get_config_file_path

        config_file = get_config_file_path()
    except Exception:
        config_file = app_path(".app_config.json")

    config = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass

    enabled = bool(config.get("enabled", config.get("proxy_enabled", False)))
    proxy_list = str(config.get("proxy_list", "") or "")

    return ProxyConfig({
        "enabled": enabled,
        "proxy_enabled": enabled,
        "proxy_list": proxy_list,
    })


def save_proxy_config(enabled, proxy_list):
    try:
        from settings_manager import get_config_file_path

        config_file = get_config_file_path()
    except Exception:
        config_file = app_path(".app_config.json")

    try:
        config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass

        config["enabled"] = bool(enabled)
        config["proxy_enabled"] = bool(enabled)
        config["proxy_list"] = str(proxy_list or "")

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        proxy_manager.load_proxies()
        return True
    except Exception as e:
        print(f"Error saving proxy config: {e}")
        return False


proxy_manager = ProxyManager()
