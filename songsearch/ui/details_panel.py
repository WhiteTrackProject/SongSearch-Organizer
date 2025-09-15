from __future__ import annotations

import logging
import sqlite3
from typing import Any, Iterable, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ..core.db import get_by_path

logger = logging.getLogger(__name__)


class DetailsPanel(QWidget):
    """Widget that shows the metadata of the currently selected track."""

    def __init__(
        self,
        con: sqlite3.Connection | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._con = con
        self._current_data: dict[str, Any] | None = None

        self._value_labels: dict[str, QLabel] = {}

        self._setup_ui()
        self.clear_details()

    # ----------------------------------------------------------------------------------
    # UI helpers
    # ----------------------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        for key, label in self._build_detail_labels():
            form.addRow(label, self._value_labels[key])

        layout.addLayout(form)

        actions = QHBoxLayout()
        actions.setSpacing(6)

        self.btn_open = QPushButton("Abrir…")
        actions.addWidget(self.btn_open)

        self.btn_reveal = QPushButton("Mostrar en carpeta")
        actions.addWidget(self.btn_reveal)

        self.btn_copy_path = QPushButton("Copiar ruta")
        actions.addWidget(self.btn_copy_path)

        self.btn_musicbrainz = QPushButton("MusicBrainz")
        actions.addWidget(self.btn_musicbrainz)

        self.btn_spectrum = QPushButton("Espectro")
        actions.addWidget(self.btn_spectrum)

        actions.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(actions)

    def _build_detail_labels(self) -> Iterable[tuple[str, QLabel]]:
        """Return an iterable of ``(field, label_widget)`` pairs for the form."""

        label_defs = [
            ("title", "Título"),
            ("artist", "Artista"),
            ("album", "Álbum"),
            ("genre", "Género"),
            ("year", "Año"),
            ("format", "Formato"),
            ("bitrate", "Bitrate"),
            ("samplerate", "Frecuencia"),
            ("channels", "Canales"),
            ("duration", "Duración"),
            ("path", "Ruta"),
            ("acoustid_id", "AcoustID"),
            ("mb_release_id", "MB Release"),
        ]

        for field, text in label_defs:
            value_label = QLabel()
            value_label.setObjectName(f"value_{field}")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._value_labels[field] = value_label
            yield field, QLabel(f"{text}:")

    # ----------------------------------------------------------------------------------
    # State management
    # ----------------------------------------------------------------------------------
    def clear_details(self) -> None:
        """Reset the panel to its empty state.

        Besides clearing the textual values, this method now disables every
        action button to avoid leaving interactions enabled when no track is
        selected.
        """

        self._current_data = None
        for label in self._value_labels.values():
            label.setText("—")
        self._toggle_action_buttons(False)

    def show_for_path(
        self,
        path: str | None,
        record: Mapping[str, Any] | None = None,
    ) -> None:
        """Populate the panel with the information stored for *path*.

        ``record`` can be provided to skip the database lookup. The action
        buttons are enabled only when a valid track record is available.
        """

        # Always start from a clean state so that stale values/buttons are reset.
        self.clear_details()

        if not path and record is None:
            return

        data = record or self._fetch_record(path)
        if not data:
            return

        normalized = self._normalize_record(data)
        if not normalized:
            return

        self._current_data = normalized
        for field, label in self._value_labels.items():
            label.setText(self._format_field_value(field, normalized.get(field)))

        self._toggle_action_buttons(True)

    # ----------------------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------------------
    def _fetch_record(self, path: str | None) -> Mapping[str, Any] | None:
        if not path or self._con is None:
            return None
        try:
            return get_by_path(self._con, path)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Cannot fetch track for %s: %s", path, exc)
            return None

    def _normalize_record(self, data: Mapping[str, Any] | Any) -> dict[str, Any] | None:
        if not data:
            return None
        if isinstance(data, Mapping):
            return dict(data)
        try:
            return dict(data)  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - fallback for exotic row types
            return None

    def _format_field_value(self, field: str, value: Any) -> str:
        if value is None:
            return "—"
        if field == "duration":
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                return str(value)
            minutes, secs = divmod(int(seconds + 0.5), 60)
            return f"{minutes:d}:{secs:02d}"
        if field == "bitrate":
            try:
                return f"{int(value)} kbps"
            except (TypeError, ValueError):
                return str(value)
        if field == "samplerate":
            try:
                return f"{int(value)} Hz"
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def _toggle_action_buttons(self, enabled: bool) -> None:
        for button in self._iter_action_buttons():
            button.setEnabled(enabled)

    def _iter_action_buttons(self) -> Iterable[QPushButton]:
        for name, value in self.__dict__.items():
            if name.startswith("btn_") and isinstance(value, QPushButton):
                yield value

