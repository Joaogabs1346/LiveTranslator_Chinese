import json
from unittest.mock import MagicMock

import pytest
import requests

from livescreen_translator.config import TRANSLATION_SYSTEM_PROMPT
from livescreen_translator.ollama_client import (OllamaClient, OllamaModelNotFound, OllamaOffline,
                                                 OllamaOutOfMemory, OllamaTimeout, OllamaError,
                                                 parse_model_list, parse_translation, clean_translation)


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if payload is None:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = payload
    return r


def make_client(session):
    return OllamaClient("http://localhost:11434/", "qwen3:8b", timeout=5, session=session)


def test_parse_translation_basic():
    assert parse_translation({"response": "  Hello world \n"}) == "Hello world"


def test_parse_translation_strips_think_and_quotes():
    raw = {"response": "<think>reasoning here</think>\n\"Start the game\""}
    assert parse_translation(raw) == "Start the game"


def test_parse_translation_prefix_removed():
    assert clean_translation("Translation: Attack") == "Attack"


def test_parse_translation_chat_shape():
    assert parse_translation({"message": {"content": "Hi"}}) == "Hi"


def test_parse_translation_error_field():
    with pytest.raises(OllamaError):
        parse_translation({"error": "boom"})


def test_parse_translation_missing_field():
    with pytest.raises(OllamaError):
        parse_translation({"foo": 1})


def test_parse_model_list():
    tags = {"models": [{"name": "qwen3:8b"}, {"model": "llama3:latest"}, {"name": "qwen3:8b"}]}
    assert parse_model_list(tags) == ["llama3:latest", "qwen3:8b"]
    assert parse_model_list({}) == []


def test_test_connection_ok():
    s = MagicMock(); s.get.return_value = _resp(200, {"version": "0.6.1"})
    st = make_client(s).test_connection()
    assert st.connected and st.version == "0.6.1"
    s.get.assert_called_once()
    assert s.get.call_args[0][0] == "http://localhost:11434/api/version"


def test_test_connection_offline():
    s = MagicMock(); s.get.side_effect = requests.exceptions.ConnectionError()
    st = make_client(s).test_connection()
    assert not st.connected and "Offline" in st.message


def test_list_models_offline_raises():
    s = MagicMock(); s.get.side_effect = requests.exceptions.ConnectionError()
    with pytest.raises(OllamaOffline):
        make_client(s).list_models()


def test_has_model_latest_alias():
    s = MagicMock(); s.get.return_value = _resp(200, {"models": [{"name": "qwen3:latest"}]})
    assert make_client(s).has_model("qwen3")


def test_translate_payload_and_result():
    s = MagicMock(); s.post.return_value = _resp(200, {"response": "Hello"})
    c = make_client(s)
    assert c.translate("你好") == "Hello"
    url = s.post.call_args[0][0]
    payload = s.post.call_args[1]["json"]
    assert url == "http://localhost:11434/api/generate"
    assert payload["model"] == "qwen3:8b"
    assert payload["prompt"] == "你好"
    assert payload["system"] == TRANSLATION_SYSTEM_PROMPT
    assert payload["stream"] is False
    assert "image" not in json.dumps(payload).lower()


def test_translate_empty_skips_request():
    s = MagicMock()
    assert make_client(s).translate("   ") == ""
    s.post.assert_not_called()


def test_translate_model_not_found():
    s = MagicMock(); s.post.return_value = _resp(404, {"error": "model 'x' not found"})
    with pytest.raises(OllamaModelNotFound):
        make_client(s).translate("你好")


def test_translate_timeout():
    s = MagicMock(); s.post.side_effect = requests.exceptions.ReadTimeout()
    with pytest.raises(OllamaTimeout):
        make_client(s).translate("你好")


def test_translate_offline():
    s = MagicMock(); s.post.side_effect = requests.exceptions.ConnectionError()
    with pytest.raises(OllamaOffline):
        make_client(s).translate("你好")


def test_translate_out_of_memory():
    s = MagicMock(); s.post.return_value = _resp(500, {"error": "model requires more system memory"})
    with pytest.raises(OllamaOutOfMemory):
        make_client(s).translate("你好")



def test_clean_strips_no_think():
    assert clean_translation("Hello there /no_think") == "Hello there"
