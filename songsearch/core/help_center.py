from __future__ import annotations

"""Helpers that expose the intelligent help-center features to the UI layer."""

from collections.abc import Mapping, Sequence
from typing import Any

from .. import ai_assistant as ai

HistoryEntry = Mapping[str, Any]

_ROLE_LABELS = {
    "user": "Usuario",
    "assistant": "Asistente",
    "system": "Sistema",
}


def _clean_text(value: Any) -> str:
    return str(value).strip()


def _filter_history(
    history: Sequence[HistoryEntry] | None, *, mode: str
) -> list[HistoryEntry]:
    if not history:
        return []
    selected: list[HistoryEntry] = []
    for entry in history:
        try:
            entry_mode = str(entry.get("mode", ""))
        except AttributeError:
            continue
        if entry_mode == mode:
            selected.append(entry)
    return selected


def _render_history(entries: Sequence[HistoryEntry], *, mode: str) -> str:
    lines: list[str] = []
    for entry in entries:
        role = str(entry.get("role", "assistant"))
        content = _clean_text(entry.get("content", ""))
        if not content:
            continue
        label = _ROLE_LABELS.get(role, role.capitalize() or "Mensaje")
        if role == "assistant" and mode == "ui":
            label = "Asistente (UI)"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _build_ui_concerns(entries: Sequence[HistoryEntry]) -> list[str]:
    concerns: list[str] = []
    for entry in entries:
        content = _clean_text(entry.get("content", ""))
        if not content:
            continue
        role = str(entry.get("role", "user"))
        if role == "assistant":
            concerns.append(f"Respuesta previa del asistente: {content}")
        elif role == "system":
            concerns.append(f"Nota del sistema: {content}")
        else:
            concerns.append(content)
    return concerns


def ask_chat(prompt: str, history: Sequence[HistoryEntry] | None = None) -> str:
    """Proxy that adapts the UI conversation to ``ai_assistant.ask_chat``."""

    clean_prompt = _clean_text(prompt)
    past_entries = _filter_history(history, mode="chat")
    context = _render_history(past_entries, mode="chat")
    if context:
        message = (
            "Contexto de la conversación hasta ahora:\n"
            f"{context}\n\n"
            "Nueva consulta:\n"
            f"{clean_prompt}"
        )
    else:
        message = clean_prompt
    return ai.ask_chat(message)


def suggest_ui_improvements(
    prompt: str, history: Sequence[HistoryEntry] | None = None
) -> str:
    """Proxy that adapts the UI suggestion flow to ``ai_assistant`` helpers."""

    clean_prompt = _clean_text(prompt)
    past_entries = _filter_history(history, mode="ui")
    context = _render_history(past_entries, mode="ui")
    concerns = _build_ui_concerns(past_entries) or None
    if context:
        snapshot = (
            "Resumen del intercambio previo sobre la interfaz:\n"
            f"{context}\n\n"
            "Detalles adicionales proporcionados por el usuario:\n"
            f"{clean_prompt}"
        )
    else:
        snapshot = clean_prompt
    return ai.suggest_ui_improvements(snapshot, concerns=concerns)
