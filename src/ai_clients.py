"""
Central AI Client Module for AI Dubber Ultimate.

Provides modern Google GenAI SDK (google-genai) client management with:
- Client caching and factory (get_genai_client)
- Pure REST fallback if google-genai package is missing
- Backward-compatibility shim for legacy google.generativeai callers
  (including pre-compiled bytecode in core_app.pyc and workers.pyc).
"""

import importlib
import os
import sys
import threading
import time
import types
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from google import genai as _google_genai
    from google.genai import types as genai_types
    from google.genai.errors import APIError as GenAIError
except ImportError:
    _google_genai = None
    genai_types = None
    GenAIError = Exception


_GENAI_CLIENT_CACHE = {}
_CACHE_LOCK = threading.Lock()
_ACTIVE_API_KEY = None


class ModelInfoWrapper:
    """Wrapper ensuring both modern .supported_actions and legacy .supported_generation_methods exist."""

    def __init__(self, raw_model):
        self._raw = raw_model
        self.name = getattr(raw_model, "name", "")
        self.display_name = getattr(raw_model, "display_name", "") or self.name
        actions = getattr(raw_model, "supported_actions", None)
        if actions is None:
            actions = getattr(raw_model, "supported_generation_methods", None)
        if actions is None:
            actions = ["generateContent"]
        self.supported_actions = list(actions)
        self.supported_generation_methods = list(actions)

    def __getattr__(self, item):
        return getattr(self._raw, item)

    def __repr__(self):
        return f"Model(name={self.name!r}, display_name={self.display_name!r})"


class ContentResponseWrapper:
    """Wrapper ensuring .text attribute is always accessible."""

    def __init__(self, raw_response_or_text):
        if isinstance(raw_response_or_text, str):
            self.text = raw_response_or_text
            self._raw = None
        else:
            self._raw = raw_response_or_text
            self.text = getattr(raw_response_or_text, "text", "") or ""

    def __getattr__(self, item):
        if self._raw is not None:
            return getattr(self._raw, item)
        raise AttributeError(
            f"'ContentResponseWrapper' object has no attribute '{item}'")

    def __repr__(self):
        preview = (self.text[:40] +
                   "...") if len(self.text) > 40 else self.text
        return f"<ContentResponse text={preview!r}>"


def _build_genai_config(kwargs):
    """Convert legacy kwargs (request_options, generation_config) into GenerateContentConfig."""
    if not genai_types:
        return None

    config_kwargs = {}
    req_opts = kwargs.get("request_options") or {}
    timeout = req_opts.get("timeout")
    if timeout is not None:
        timeout_ms = int(timeout * 1000) if timeout < 1000 else int(timeout)
        config_kwargs["http_options"] = genai_types.HttpOptions(
            timeout=timeout_ms)

    gen_cfg = kwargs.get("generation_config") or {}
    if isinstance(gen_cfg, dict):
        if "temperature" in gen_cfg:
            config_kwargs["temperature"] = gen_cfg["temperature"]
        if "max_output_tokens" in gen_cfg:
            config_kwargs["max_output_tokens"] = gen_cfg["max_output_tokens"]
        if "top_p" in gen_cfg:
            config_kwargs["top_p"] = gen_cfg["top_p"]
        if "top_k" in gen_cfg:
            config_kwargs["top_k"] = gen_cfg["top_k"]

    if config_kwargs:
        return genai_types.GenerateContentConfig(**config_kwargs)
    return None


class LegacyGenerativeModel:
    """Compatibility wrapper for genai.GenerativeModel routing to client.models.generate_content."""

    def __init__(self, model_name="gemini-2.5-flash", **kwargs):
        self.model_name = str(model_name).strip()
        self._init_kwargs = kwargs

    def generate_content(self, contents, **kwargs):
        merged_kwargs = dict(self._init_kwargs)
        merged_kwargs.update(kwargs)

        client = get_genai_client()
        cfg = _build_genai_config(merged_kwargs)

        clean_model = self.model_name
        response = client.models.generate_content(
            model=clean_model,
            contents=contents,
            config=cfg,
        )
        return ContentResponseWrapper(response)


def _create_gemini_rest_client(api_key):
    """Pure REST fallback client matching the google.genai.Client interface."""
    import requests

    class _RestModels:
        def __init__(self, key):
            self.key = key

        def list(self, **kwargs):
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.key}"
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for item in data.get("models", []):
                m_obj = types.SimpleNamespace(
                    name=item.get("name", ""),
                    display_name=item.get("displayName", ""),
                    supported_actions=item.get(
                        "supportedGenerationMethods", ["generateContent"]),
                    supported_generation_methods=item.get(
                        "supportedGenerationMethods", ["generateContent"]),
                )
                models.append(ModelInfoWrapper(m_obj))
            return models

        def generate_content(self, model, contents, config=None, **kwargs):
            clean_name = model
            if clean_name.startswith("models/"):
                clean_name = clean_name[len("models/"):]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_name}:generateContent?key={self.key}"

            parts = []
            if isinstance(contents, list):
                for item in contents:
                    if hasattr(item, "uri"):
                        parts.append({"fileData": {"fileUri": item.uri, "mimeType": getattr(
                            item, "mime_type", "audio/mp3")}})
                    else:
                        parts.append({"text": str(item)})
            else:
                parts.append({"text": str(contents)})

            payload = {"contents": [{"parts": parts}]}
            timeout = 120
            if config and hasattr(config, "http_options") and getattr(config.http_options, "timeout", None):
                timeout = max(5, int(config.http_options.timeout / 1000))

            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            text_result = ""
            if candidates:
                p_list = candidates[0].get("content", {}).get("parts", [])
                text_result = "".join(p.get("text", "") for p in p_list)
            return ContentResponseWrapper(text_result)

    class _RestFiles:
        def __init__(self, key):
            self.key = key

        def upload(self, *, file, **kwargs):
            import json
            import mimetypes
            file_path = str(file)
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or "audio/mp3"
            size = os.path.getsize(file_path)

            upload_init_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={self.key}"
            headers = {
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            }
            metadata = {"file": {"displayName": os.path.basename(file_path)}}
            init_resp = requests.post(
                upload_init_url, headers=headers, json=metadata, timeout=30)
            init_resp.raise_for_status()
            upload_url = init_resp.headers.get("X-Goog-Upload-URL")

            with open(file_path, "rb") as f:
                data = f.read()

            upload_headers = {
                "Content-Length": str(size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            }
            final_resp = requests.post(
                upload_url, headers=upload_headers, data=data, timeout=120)
            final_resp.raise_for_status()
            res_json = final_resp.json().get("file", {})
            return types.SimpleNamespace(
                name=res_json.get("name", ""),
                uri=res_json.get("uri", ""),
                state=types.SimpleNamespace(name="ACTIVE"),
                mime_type=mime_type,
            )

        def get(self, *, name, **kwargs):
            url = f"https://generativelanguage.googleapis.com/v1beta/{name}?key={self.key}"
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            res_json = resp.json()
            return types.SimpleNamespace(
                name=res_json.get("name", name),
                uri=res_json.get("uri", ""),
                state=types.SimpleNamespace(
                    name=res_json.get("state", "ACTIVE")),
                mime_type=res_json.get("mimeType", "audio/mp3"),
            )

        def delete(self, *, name, **kwargs):
            url = f"https://generativelanguage.googleapis.com/v1beta/{name}?key={self.key}"
            resp = requests.delete(url, timeout=15)
            return resp.status_code in (200, 204)

    class _RestClient:
        def __init__(self, key):
            self.models = _RestModels(key)
            self.files = _RestFiles(key)

    return _RestClient(api_key)


def get_genai_client(api_key=None):
    """
    Get or create a cached google.genai.Client instance for the provided API key.
    If api_key is None, resolves from active key or settings_manager.
    """
    global _ACTIVE_API_KEY

    target_key = api_key
    if not target_key:
        target_key = _ACTIVE_API_KEY

    if not target_key:
        try:
            from settings_manager import get_gemini_api_config
            cfg = get_gemini_api_config()
            target_key = cfg.get("api_key")
            if not target_key and cfg.get("api_keys"):
                target_key = cfg.get("api_keys")[0]
        except Exception:
            pass

    key_str = str(target_key).strip() if target_key else ""
    if not key_str:
        raise ValueError(
            "No Gemini API key provided. Please configure an API key in Settings.")

    with _CACHE_LOCK:
        if key_str in _GENAI_CLIENT_CACHE:
            return _GENAI_CLIENT_CACHE[key_str]

        if _google_genai is not None:
            client = _google_genai.Client(api_key=key_str)
        else:
            client = _create_gemini_rest_client(api_key=key_str)

        _GENAI_CLIENT_CACHE[key_str] = client
        return client


class _GenAICompatibilityShim:
    """Transparent compatibility shim emulating legacy google.generativeai module."""

    def __init__(self):
        self.GenerativeModel = LegacyGenerativeModel
        self.types = genai_types
        self.__version__ = "google-genai-compatibility-shim-2.0"

    def configure(self, api_key=None, transport=None, **kwargs):
        global _ACTIVE_API_KEY
        if api_key:
            _ACTIVE_API_KEY = str(api_key).strip()

    def list_models(self, **kwargs):
        client = get_genai_client()
        raw_models = client.models.list()
        wrapped = []
        for m in raw_models:
            wrapped.append(ModelInfoWrapper(m))
        return wrapped

    def upload_file(self, path, **kwargs):
        client = get_genai_client()
        return client.files.upload(file=path)

    def get_file(self, name, **kwargs):
        client = get_genai_client()
        return client.files.get(name=name)

    def delete_file(self, name, **kwargs):
        client = get_genai_client()
        return client.files.delete(name=name)

    def get_client(self, api_key=None):
        return get_genai_client(api_key=api_key)

    @property
    def Client(self):
        return _google_genai.Client if _google_genai is not None else _create_gemini_rest_client

    def __getattr__(self, name):
        if _google_genai is not None and hasattr(_google_genai, name):
            return getattr(_google_genai, name)
        raise AttributeError(
            f"module 'google.generativeai' has no attribute '{name}'")


# Singleton shim instance
genai_shim = _GenAICompatibilityShim()
genai = genai_shim

# Install shim into sys.modules so `import google.generativeai` routes to genai_shim
if "google" not in sys.modules:
    google_pkg = types.ModuleType("google")
    sys.modules["google"] = google_pkg

sys.modules["google.generativeai"] = genai_shim
setattr(sys.modules["google"], "generativeai", genai_shim)
