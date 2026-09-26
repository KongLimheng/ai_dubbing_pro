"""Lazy wrappers for optional AI SDKs."""

import importlib
import sys
import types
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)


def _create_gemini_rest_fallback():
    """Lightweight REST-based fallback for google.generativeai."""
    mod = types.ModuleType("google.generativeai")
    mod._api_key = ""

    def configure(api_key=None):
        if api_key:
            mod._api_key = str(api_key).strip()

    class _ModelObj:
        def __init__(self, name, display_name=""):
            self.name = name
            self.display_name = display_name or name

        def __repr__(self):
            return f"Model(name={self.name!r})"

    def list_models():
        import requests
        key = mod._api_key
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        models = []
        for item in data.get("models", []):
            models.append(_ModelObj(item.get("name", ""), item.get("displayName", "")))
        return models

    class _ContentResponse:
        def __init__(self, text):
            self.text = text

    class GenerativeModel:
        def __init__(self, model_name="gemini-2.5-flash", **kwargs):
            clean_name = model_name
            if clean_name.startswith("models/"):
                clean_name = clean_name[len("models/"):]
            self.model_name = clean_name

        def generate_content(self, contents, **kwargs):
            import requests
            key = mod._api_key
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={key}"
            text_prompt = str(contents)
            if isinstance(contents, list) and contents:
                text_prompt = " ".join(str(c) for c in contents)
            payload = {
                "contents": [{
                    "parts": [{"text": text_prompt}]
                }]
            }
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            text_result = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text_result = "".join(p.get("text", "") for p in parts)
            return _ContentResponse(text_result)

    mod.configure = configure
    mod.list_models = list_models
    mod.GenerativeModel = GenerativeModel
    mod.__version__ = "0.8.6-rest-fallback"
    return mod


_CACHED_DISCOVERY_DOC = None


def _patch_google_generativeai(mod):
    """
    Patch google.generativeai to:
    1. Fix $discovery/rest HTTP 400 error on new API key formats (AQ.Ab8...).
    2. Default to transport='rest' for reliable HTTPS without gRPC timeouts.
    3. Clear cached clients on configure() so new keys take effect immediately.
    """
    try:
        from google.generativeai import client as c
        import googleapiclient.discovery
        import googleapiclient.http
        import httplib2

        # 1. Patch FileServiceClient._setup_discovery_api to eliminate &key={api_key} on $discovery/rest
        if hasattr(c, "FileServiceClient"):
            def _patched_setup_discovery_api(self, metadata=()):
                global _CACHED_DISCOVERY_DOC
                api_key = self._client_options.api_key
                if api_key is None:
                    raise ValueError(
                        "Invalid operation: Uploading to the File API requires an API key. Please provide a valid API key."
                    )
                if not _CACHED_DISCOVERY_DOC:
                    # Public Google API discovery doc does not need &key={api_key}.
                    # Passing new-style Gemini keys (e.g. AQ.Ab8...) causes HTTP 400.
                    # Fetching without key returns 200 OK.
                    request = googleapiclient.http.HttpRequest(
                        http=httplib2.Http(),
                        postproc=lambda resp, content: (resp, content),
                        uri=f"{c.GENAI_API_DISCOVERY_URL}?version=v1beta",
                        headers=dict(metadata),
                    )
                    response, content = request.execute()
                    request.http.close()
                    _CACHED_DISCOVERY_DOC = content.decode("utf-8")

                self._local.discovery_api = googleapiclient.discovery.build_from_document(
                    _CACHED_DISCOVERY_DOC, developerKey=api_key
                )

            c.FileServiceClient._setup_discovery_api = _patched_setup_discovery_api

        # 2. Patch configure() to default to transport="rest" and clear stale cached clients
        orig_configure = mod.configure
        def _patched_configure(*args, **kwargs):
            if "transport" not in kwargs and not args[1:]:
                kwargs["transport"] = "rest"
            res = orig_configure(*args, **kwargs)
            if hasattr(c, "_client_manager") and hasattr(c._client_manager, "clients"):
                c._client_manager.clients.clear()
            return res

        mod.configure = _patched_configure
    except Exception as e:
        print(f"[WARN] Failed to patch google.generativeai discovery API: {e}")


class _LazyModule:
    def __init__(self, module_name):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            try:
                self._module = importlib.import_module(self._module_name)
                if self._module_name == "google.generativeai":
                    _patch_google_generativeai(self._module)
            except ImportError:
                if self._module_name == "google.generativeai":
                    self._module = _create_gemini_rest_fallback()
                    # Ensure google package exists in sys.modules
                    if "google" not in sys.modules:
                        google_pkg = types.ModuleType("google")
                        sys.modules["google"] = google_pkg
                    sys.modules["google.generativeai"] = self._module
                    setattr(sys.modules["google"], "generativeai", self._module)
                else:
                    raise
        return self._module

    def __getattr__(self, name):
        return getattr(self._load(), name)


genai = _LazyModule("google.generativeai")

# Pre-populate sys.modules if native package missing so `from google import generativeai` works
try:
    import google.generativeai as _real_genai  # noqa: F401
    _patch_google_generativeai(_real_genai)
except ImportError:
    genai._load()


