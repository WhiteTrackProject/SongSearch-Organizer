from __future__ import annotations

import typer
from typer.testing import CliRunner

from songsearch.cli import main as cli_main

_test_cli = typer.Typer()
_test_cli.command()(cli_main.chat)


def test_chat_command_uses_assistant(monkeypatch):
    runner = CliRunner()
    recorded: dict[str, str] = {}

    def fake_ask(prompt: str) -> str:
        recorded["prompt"] = prompt
        return "Respuesta asistida"

    monkeypatch.setattr(cli_main, "ask_chat", fake_ask)

    result = runner.invoke(_test_cli, ["¿Qué hace el modo simulate?"])

    assert result.exit_code == 0
    assert "Respuesta asistida" in result.stdout
    assert recorded["prompt"] == "¿Qué hace el modo simulate?"
