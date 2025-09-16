"""OpenAI assistant helpers used by the help centre and CLI."""

from __future__ import annotations

import os
from typing import Any, Mapping, MutableSequence, Sequence

_DEFAULT_MODEL = "gpt-4o-mini"
_SYSTEM_PROMPT = (
    "Eres el asistente de SongSearch Organizer. Responde de forma concisa, en "
    "español y ofrece pasos concretos para usar la aplicación. Si la pregunta no "
    "está relacionada con el proyecto, indica amablemente que no puedes ayudar."
)


class AssistantError(RuntimeError):
    """Base exception for the assistant helpers."""


class MissingAPIKeyError(AssistantError, ValueError):
    """Raised when the OPENAI_API_KEY environment variable is missing."""


def _client() -> Any:
    """Return an OpenAI client configured from environment variables.

    Raises
    ------
    MissingAPIKeyError
        If the ``OPENAI_API_KEY`` variable is missing or empty.
    """

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise MissingAPIKeyError("OPENAI_API_KEY no está configurada.")

    from openai import OpenAI  # imported lazily to avoid heavy import at module load

    return OpenAI(api_key=api_key)


def _prepare_messages(
    question: str, history: Sequence[Mapping[str, str]] | None = None
) -> list[dict[str, str]]:
    cleaned = question.strip()
    if not cleaned:
        raise ValueError("La pregunta no puede estar vacía.")

    messages: MutableSequence[dict[str, str]] = []
    if history:
        for message in history:
            role = message.get("role")
            content = message.get("content")
            if not (role and content):
                continue
            messages.append({"role": str(role), "content": str(content)})
    if not any(msg.get("role") == "system" for msg in messages):
        messages.insert(0, {"role": "system", "content": _SYSTEM_PROMPT})
    messages.append({"role": "user", "content": cleaned})
    return list(messages)


def _extract_text(completion: Any) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        return ""
    for choice in choices:
        message = getattr(choice, "message", None)
        if message is None:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        if isinstance(content, list):  # new Responses API may return structured parts
            parts: list[str] = []
            for part in content:
                text_value = getattr(part, "text", None) or getattr(part, "value", None)
                if isinstance(text_value, str):
                    text_value = text_value.strip()
                    if text_value:
                        parts.append(text_value)
            if parts:
                return "\n\n".join(parts)
    return ""


def ask_for_help(
    question: str,
    *,
    history: Sequence[Mapping[str, str]] | None = None,
    model: str | None = None,
) -> str:
    """Send *question* to the configured OpenAI model and return the reply text."""

    client = _client()
    selected_model = (model or os.getenv("OPENAI_MODEL", "").strip()) or _DEFAULT_MODEL
    messages = _prepare_messages(question, history)
    completion = client.chat.completions.create(model=selected_model, messages=messages, temperature=0.2)
    return _extract_text(completion)
