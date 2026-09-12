"""Minimal Ollama HTTP client (local only). Sends ONLY OCR text, never images."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import requests

from .config import TRANSLATION_SYSTEM_PROMPT

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaError(Exception):
    """Base error."""


class OllamaOffline(OllamaError):
    """Server not reachable."""


class OllamaModelNotFound(OllamaError):
    """Requested model is not installed."""


class OllamaTimeout(OllamaError):
    """Request took longer than the configured timeout."""


class OllamaOutOfMemory(OllamaError):
    """Ollama reported not enough memory to load the model."""


@dataclass
class ConnectionStatus:
    connected: bool
    version: str = ""
    message: str = ""


def clean_translation(text: str) -> str:
    text = _THINK_RE.sub("", text)
    text = re.sub(r"\s*/no_think\s*$", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        text = text[1:-1].strip()
    for prefix in ("Translation:", "English:", "Translated text:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text


def parse_translation(response_json: dict) -> str:
    """Extract and clean the translation from an /api/generate (non-stream) response."""
    if not isinstance(response_json, dict):
        raise OllamaError("Invalid response type")
    if "error" in response_json:
        raise OllamaError(str(response_json["error"]))
    text = response_json.get("response")
    if text is None and "message" in response_json:
        text = (response_json.get("message") or {}).get("content", "")
    if text is None:
        raise OllamaError("Response has no 'response' field")
    return clean_translation(str(text))


def parse_model_list(tags_json: dict) -> List[str]:
    models = tags_json.get("models") if isinstance(tags_json, dict) else None
    if not models:
        return []
    names = []
    for m in models:
        name = m.get("name") or m.get("model")
        if name:
            names.append(name)
    return sorted(set(names))


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3:8b",
                 timeout: float = 30.0, session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self._session = session or requests.Session()

    def test_connection(self) -> ConnectionStatus:
        try:
            r = self._session.get(f"{self.base_url}/api/version", timeout=min(5.0, self.timeout))
            if r.status_code != 200:
                return ConnectionStatus(False, message=f"HTTP {r.status_code}")
            version = (r.json() or {}).get("version", "")
            return ConnectionStatus(True, version=version, message=f"Connected (Ollama {version})")
        except requests.exceptions.Timeout:
            return ConnectionStatus(False, message="Timeout")
        except requests.exceptions.RequestException as e:
            return ConnectionStatus(False, message=f"Offline: {e.__class__.__name__}")
        except ValueError:
            return ConnectionStatus(False, message="Invalid JSON from server")

    def list_models(self) -> List[str]:
        try:
            r = self._session.get(f"{self.base_url}/api/tags", timeout=min(8.0, self.timeout))
        except requests.exceptions.Timeout as e:
            raise OllamaTimeout("Timed out listing models") from e
        except requests.exceptions.RequestException as e:
            raise OllamaOffline(f"Ollama offline: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise OllamaError(f"HTTP {r.status_code} listing models")
        return parse_model_list(r.json())

    def has_model(self, model: Optional[str] = None) -> bool:
        model = model or self.model
        models = self.list_models()
        return model in models or f"{model}:latest" in models

    def build_payload(self, text: str) -> dict:
        return {
            "model": self.model,
            "system": TRANSLATION_SYSTEM_PROMPT,
            "prompt": text,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 512},
            "keep_alive": "10m",
        }

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        payload = self.build_payload(text)
        try:
            r = self._session.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            raise OllamaTimeout(f"Translation timed out after {self.timeout:.0f}s") from e
        except requests.exceptions.RequestException as e:
            raise OllamaOffline(f"Ollama offline: {e.__class__.__name__}") from e

        if r.status_code == 404:
            raise OllamaModelNotFound(f"Model '{self.model}' not found. Run: ollama pull {self.model}")
        if r.status_code != 200:
            msg = ""
            try:
                msg = (r.json() or {}).get("error", "")
            except ValueError:
                msg = r.text[:200]
            low = msg.lower()
            if "not found" in low:
                raise OllamaModelNotFound(msg)
            if "memory" in low or "oom" in low:
                raise OllamaOutOfMemory(msg)
            raise OllamaError(f"HTTP {r.status_code}: {msg}")
        try:
            data = r.json()
        except ValueError as e:
            raise OllamaError("Invalid JSON in translation response") from e
        return parse_translation(data)
