from __future__ import annotations

import pytest

import songsearch.ai_assistant as ai


def test_ask_chat_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        ai.ask_chat("¿Cómo organizo mi biblioteca?")


def test_ask_chat_sends_expected_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-song")
    captured: dict[str, object] = {}

    class DummyResponses:
        def create(self, **kwargs):
            captured["payload"] = kwargs
            return type("Resp", (), {"output_text": "Respuesta generada"})()

    class DummyOpenAI:
        def __init__(self, *, api_key: str):
            captured["api_key"] = api_key
            self.responses = DummyResponses()

    monkeypatch.setattr(ai, "_get_openai_class", lambda: DummyOpenAI)

    answer = ai.ask_chat("¿Cómo escaneo mi biblioteca?")

    assert answer == "Respuesta generada"
    assert captured["api_key"] == "secret"

    payload = captured["payload"]
    assert payload["model"] == "gpt-song"
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][0]["content"][0]["text"] == ai.SYSTEM_PROMPT
    assert payload["input"][1]["content"][0]["text"] == "¿Cómo escaneo mi biblioteca?"
    assert payload["max_output_tokens"] == ai.MAX_OUTPUT_TOKENS


def test_suggest_ui_improvements_builds_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-song")
    captured: dict[str, object] = {}

    class DummyResponses:
        def create(self, **kwargs):
            captured["payload"] = kwargs
            return type("Resp", (), {"output_text": "Añade un panel lateral"})()

    class DummyOpenAI:
        def __init__(self, *, api_key: str):
            captured["api_key"] = api_key
            self.responses = DummyResponses()

    monkeypatch.setattr(ai, "_get_openai_class", lambda: DummyOpenAI)

    suggestion = ai.suggest_ui_improvements(
        "Cabecera con botones Escanear, Enriquecer y Espectro.",
        concerns=["Los botones no se distinguen", "Falta feedback visual"],
    )

    assert suggestion == "Añade un panel lateral"

    payload = captured["payload"]
    assert payload["model"] == "gpt-song"
    assert payload["input"][0]["content"][0]["text"] == ai.UI_SYSTEM_PROMPT

    user_text = payload["input"][1]["content"][0]["text"]
    assert "Cabecera con botones Escanear, Enriquecer y Espectro." in user_text
    assert "- Los botones no se distinguen" in user_text
    assert "- Falta feedback visual" in user_text
