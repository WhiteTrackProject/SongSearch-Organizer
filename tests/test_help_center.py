from __future__ import annotations

import os
from typing import Any

import pytest

from songsearch.core import help_center


def test_help_center_ask_chat_includes_history(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_ask_chat(prompt: str) -> str:
        captured["prompt"] = prompt
        return "respuesta generada"

    monkeypatch.setattr(help_center.ai, "ask_chat", fake_ask_chat)

    history = (
        {"role": "user", "content": "Hola", "mode": "chat"},
        {
            "role": "assistant",
            "content": "Puedes revisar la pestaña Biblioteca para comenzar.",
            "mode": "chat",
        },
        {"role": "user", "content": "La cabecera está muy cargada", "mode": "ui"},
    )

    answer = help_center.ask_chat("¿Cómo mejoro mi flujo de trabajo?", history=history)

    assert answer == "respuesta generada"
    prompt = captured["prompt"]
    assert "Contexto de la conversación" in prompt
    assert "Usuario: Hola" in prompt
    assert "Nueva consulta" in prompt
    assert "¿Cómo mejoro mi flujo de trabajo?" in prompt
    assert "cabecera" not in prompt  # proviene de un historial de modo distinto


def test_help_center_suggest_ui_improvements_builds_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_suggest(snapshot: str, *, concerns: list[str] | None = None) -> str:
        captured["snapshot"] = snapshot
        captured["concerns"] = concerns
        return "ajusta el contraste"

    monkeypatch.setattr(help_center.ai, "suggest_ui_improvements", fake_suggest)

    history = (
        {"role": "user", "content": "Panel lateral saturado", "mode": "ui"},
        {
            "role": "assistant",
            "content": "Considera un diseño de dos columnas para agrupar filtros.",
            "mode": "ui",
        },
        {"role": "system", "content": "Consulta anterior completada", "mode": "ui"},
        {"role": "assistant", "content": "¿Necesitas algo más?", "mode": "chat"},
    )

    suggestion = help_center.suggest_ui_improvements(
        "Añadir botón de filtros rápidos",
        history=history,
    )

    assert suggestion == "ajusta el contraste"
    snapshot = captured["snapshot"]
    assert "Resumen del intercambio previo" in snapshot
    assert "Panel lateral saturado" in snapshot
    assert "dos columnas" in snapshot
    assert "Añadir botón de filtros rápidos" in snapshot

    concerns = captured["concerns"]
    assert concerns is not None
    assert concerns[0] == "Panel lateral saturado"
    assert any(item.startswith("Respuesta previa del asistente") for item in concerns)
    assert any(item.startswith("Nota del sistema") for item in concerns)


@pytest.fixture(scope="module")
def qapp() -> Any:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - entorno sin soporte gráfico
        pytest.skip(f"PySide6 no disponible: {exc}")

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_help_center_dialog_can_be_shown(qapp: Any) -> None:
    from songsearch.ui.main_window import _HelpCenterDialog

    dialog = _HelpCenterDialog()
    dialog.set_overview_html("<b>Centro de ayuda</b>")
    dialog.update_history([])
    dialog.show_feedback("Listo para ayudarte")
    dialog.show_feedback("Ups, ocurrió un problema", error=True)
    dialog.update_history(
        [
            {"role": "user", "content": "¿Cómo importo archivos?", "mode": "chat"},
            {
                "role": "assistant",
                "content": "Usa la acción Escanear carpeta en la barra superior.",
                "mode": "chat",
            },
        ]
    )
    dialog.set_loading(True)
    dialog.set_loading(False)
    dialog.focus_prompt()
    dialog.show()
    qapp.processEvents()
    dialog.close()
