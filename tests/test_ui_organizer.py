from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip(
    "PySide6.QtWidgets",
    reason="PySide6 no está disponible o falta libGL.so.1 en el entorno de ejecución",
    "PySide6.QtGui",
    reason="Qt runtime with libEGL is required for UI tests",
    exc_type=ImportError,
)

import songsearch.ui.main_window as ui_main_window
from songsearch.core.db import connect, init_db
from songsearch.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise pytest.SkipTest(
            "Qt runtime with libEGL is required for UI tests"
        ) from exc

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    db_path = init_db(data_dir)
    con = connect(db_path)
    monkeypatch.setattr(MainWindow, "_handle_startup_prompts", lambda self: None)
    window = MainWindow(con=con, data_dir=data_dir)
    yield window
    window.close()
    con.close()


def test_simulate_button_invokes_simulate(qapp, main_window, monkeypatch, tmp_path):
    dest = tmp_path / "dest"
    template_name = "default"
    template_pattern = "{Artista}/{Título}.{ext}"

    monkeypatch.setattr(
        MainWindow,
        "_prompt_simulation_parameters",
        lambda self: (dest, template_name, template_pattern),
    )

    recorded: dict[str, object] = {}

    def fake_simulate(con, dest_arg, template_arg, **kwargs):
        recorded["args"] = (con, dest_arg, template_arg, kwargs)
        return [("source.mp3", str(dest / "source.mp3"))]

    monkeypatch.setattr(ui_main_window, "simulate", fake_simulate)

    preview_data: dict[str, object] = {}

    def fake_preview(self, plan, *, dest, template_name, template_pattern):
        preview_data["data"] = (plan, dest, template_name, template_pattern)

    monkeypatch.setattr(MainWindow, "_show_plan_preview", fake_preview)

    main_window._btn_simulate.click()
    qapp.processEvents()

    assert "args" in recorded
    con_arg, dest_arg, template_arg, kwargs = recorded["args"]
    assert con_arg is main_window._con
    assert dest_arg == dest
    assert template_arg == template_pattern
    assert kwargs == {}

    assert main_window._organizer_plan == preview_data["data"][0]
    assert preview_data["data"][1] == dest
    assert preview_data["data"][2] == template_name
    assert preview_data["data"][3] == template_pattern
    assert main_window._btn_apply_plan.isEnabled()


def test_apply_button_invokes_apply_plan(qapp, main_window, monkeypatch):
    plan = [("track.mp3", "/dest/track.mp3")]
    main_window._organizer_plan = list(plan)
    main_window._update_action_state()

    monkeypatch.setattr(
        MainWindow,
        "_prompt_apply_mode",
        lambda self: ("move", "Mover archivos"),
    )

    recorded: dict[str, object] = {}

    def fake_apply(plan_arg, mode, undo_log, con=None):
        recorded["args"] = (plan_arg, mode, undo_log, con)
        return undo_log

    monkeypatch.setattr(ui_main_window, "apply_plan", fake_apply)

    main_window._btn_apply_plan.click()
    qapp.processEvents()

    assert "args" in recorded
    plan_arg, mode_arg, undo_arg, con_arg = recorded["args"]
    assert plan_arg == plan
    assert mode_arg == "move"
    assert con_arg is main_window._con
    assert undo_arg == main_window._undo_log_path
    assert main_window._organizer_plan == []
    assert not main_window._btn_apply_plan.isEnabled()
