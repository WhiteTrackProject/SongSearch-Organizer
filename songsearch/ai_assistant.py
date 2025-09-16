from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

DEFAULT_MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = (
    "Eres SongSearch Organizer, un asistente experto en bibliotecas musicales. "
    "Responde en español con instrucciones claras y accionables."
)
UI_SYSTEM_PROMPT = (
    "Actúa como diseñador UX/UI senior para SongSearch Organizer. "
    "Analiza la descripción y propone mejoras concretas en español."
)
MAX_OUTPUT_TOKENS = 500
TEMPERATURE = 0.3


def _ensure_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta OPENAI_API_KEY; configúralo en tu entorno o en el archivo .env."
        )
    return api_key


def _resolve_model(override: str | None) -> str:
    if override:
        return override
    env_model = os.getenv("OPENAI_MODEL")
    if env_model:
        return env_model
    return DEFAULT_MODEL


def _get_openai_class() -> Any:  # pragma: no cover - small helper
    from openai import OpenAI  # type: ignore[import-not-found]

    return OpenAI


def _create_client() -> Any:
    api_key = _ensure_api_key()
    openai_cls = _get_openai_class()
    return openai_cls(api_key=api_key)


def _extract_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()
    output = getattr(response, "output", None)
    if isinstance(output, list) and output:
        try:
            content = output[0]["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            pass
        else:
            return str(content).strip()
    raise RuntimeError("La respuesta del modelo no contiene texto utilizable.")


def _format_concerns(concerns: Sequence[str] | None) -> str:
    if not concerns:
        return "- Sin incidencias reportadas."
    return "\n".join(f"- {item}" for item in concerns)


def _send_messages(
    *, system_prompt: str, user_text: str, model: str | None = None
) -> str:
    client = _create_client()
    payload = [
        {
            "role": "system",
            "content": [{"type": "text", "text": system_prompt}],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": user_text}],
        },
    ]
    response = client.responses.create(
        model=_resolve_model(model),
        input=payload,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return _extract_text(response)


def ask_chat(question: str, *, model: str | None = None) -> str:
    """Pregunta al asistente general de SongSearch Organizer."""
    return _send_messages(system_prompt=SYSTEM_PROMPT, user_text=question.strip(), model=model)


def suggest_ui_improvements(
    ui_snapshot: str, *, concerns: Sequence[str] | None = None, model: str | None = None
) -> str:
    """Solicita propuestas de mejoras visuales o de UX para la aplicación."""
    user_text = (
        "Descripción de la interfaz actual:\n"
        f"{ui_snapshot.strip()}\n\n"
        "Problemas o áreas de mejora reportadas:\n"
        f"{_format_concerns(concerns)}\n\n"
        "Sugiere mejoras priorizadas y accionables para SongSearch Organizer."
    )
    return _send_messages(
        system_prompt=UI_SYSTEM_PROMPT,
        user_text=user_text,
        model=model,
    )
