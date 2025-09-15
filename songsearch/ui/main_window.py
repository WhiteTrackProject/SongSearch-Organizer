from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QItemSelection,
    QItemSelectionModel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.db import connect, fts_query_from_text, init_db, query_tracks
from .details_panel import DetailsPanel

logger = logging.getLogger(__name__)


class TrackTableModel(QAbstractTableModel):
    """Simple table model that exposes tracks from the SQLite database."""

    COLUMNS: tuple[tuple[str, str], ...] = (
        ("title", "Título"),
        ("artist", "Artista"),
        ("album", "Álbum"),
        ("genre", "Género"),
        ("year", "Año"),
        ("duration", "Duración"),
        ("bitrate", "Bitrate"),
        ("format", "Formato"),
        ("path", "Ruta"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Qt model API
    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        column = index.column()
        if row < 0 or row >= len(self._rows) or column < 0 or column >= len(self.COLUMNS):
            return None

        key = self.COLUMNS[column][0]
        value = self._rows[row].get(key)

        if role == Qt.DisplayRole:
            return self._format_value(key, value)
        if role == Qt.TextAlignmentRole and key in {"year", "duration", "bitrate"}:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section][1]
            return None
        return section + 1

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # type: ignore[override]
        if not index.isValid():
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def set_rows(self, rows: Iterable[Mapping[str, Any] | sqlite3.Row]) -> None:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            try:
                normalized.append(dict(row))
            except Exception:  # pragma: no cover - defensive fallback
                logger.debug("Cannot normalize row: %r", row)
        self.beginResetModel()
        self._rows = normalized
        self.endResetModel()

    def clear(self) -> None:
        self.set_rows([])

    def row_data(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def index_for_path(self, path: str | None) -> int | None:
        if not path:
            return None
        for idx, row in enumerate(self._rows):
            if row.get("path") == path:
                return idx
        return None

    def _format_value(self, key: str, value: Any) -> str:
        if value in (None, ""):
            return "—"
        if key == "duration":
            try:
                total_seconds = float(value)
            except (TypeError, ValueError):
                return str(value)
            minutes, seconds = divmod(int(total_seconds + 0.5), 60)
            return f"{minutes:d}:{seconds:02d}"
        if key == "bitrate":
            try:
                bitrate = int(value)
            except (TypeError, ValueError):
                return str(value)
            if bitrate >= 1000:
                bitrate //= 1000
            return f"{bitrate} kbps"
        return str(value)


class MainWindow(QMainWindow):
    """Main application window for the SongSearch Organizer UI."""

    MAX_RESULTS = 5000
    SEARCH_DEBOUNCE_MS = 250

    def __init__(
        self,
        con: sqlite3.Connection | None = None,
        data_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data_dir = (data_dir or Path.home() / ".songsearch").expanduser()
        self._owns_connection = con is None
        if con is None:
            db_path = init_db(self._data_dir)
            con = connect(db_path)
            logger.info("Base de datos cargada desde %s", db_path)
        self._con = con

        self._model = TrackTableModel(self)
        self._details = DetailsPanel(con=self._con, data_dir=self._data_dir, parent=self)
        self._current_path: str | None = None

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(self.SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.refresh_results)

        self._search = QLineEdit(self)
        self._table = QTableView(self)
        self._status = QStatusBar(self)

        self._build_ui()
        self.refresh_results()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("SongSearch Organizer")
        self.resize(1280, 720)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._search.setPlaceholderText("Buscar título, artista, álbum, género o ruta…")
        self._search.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Horizontal, central)
        splitter.setChildrenCollapsible(False)

        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.setWordWrap(False)
        self._table.horizontalHeader().setSectionsMovable(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.verticalHeader().setVisible(False)

        splitter.addWidget(self._table)
        splitter.addWidget(self._details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        self.setCentralWidget(central)
        self.setStatusBar(self._status)
        self._status.showMessage("Listo")

        selection_model = self._table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_search_text_changed(self, _: str) -> None:
        self._search_timer.start()

    def _on_selection_changed(
        self, selected: QItemSelection, _: QItemSelection
    ) -> None:  # pragma: no cover - UI callback
        if not selected.indexes():
            self._current_path = None
            self._details.clear_details()
            return
        index = selected.indexes()[0]
        data = self._model.row_data(index.row())
        if not data:
            self._current_path = None
            self._details.clear_details()
            return
        path = data.get("path")
        self._current_path = path if isinstance(path, str) else None
        if self._current_path:
            self._details.show_for_path(self._current_path, record=data)
        else:
            self._details.clear_details()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def refresh_results(self) -> None:
        if self._con is None:
            self._model.clear()
            self._details.clear_details()
            self._status.showMessage("Sin conexión a la base de datos")
            return

        query_text = self._search.text().strip()
        search_hint = bool(query_text)
        start = time.perf_counter()
        try:
            if query_text:
                fts_query = fts_query_from_text(query_text)
                if fts_query is None:
                    rows: list[sqlite3.Row] = []
                else:
                    rows = list(query_tracks(self._con, fts_query=fts_query))
                    search_hint = False
            else:
                rows = list(query_tracks(self._con))
                search_hint = False
        except sqlite3.Error as exc:  # pragma: no cover - defensive logging
            logger.exception("Database query failed: %s", exc)
            QMessageBox.critical(
                self,
                "Error de base de datos",
                f"No se pudo consultar la base de datos.\n\n{exc}",
            )
            return
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        total = len(rows)
        if total > self.MAX_RESULTS:
            display_rows = rows[: self.MAX_RESULTS]
            truncated = True
        else:
            display_rows = rows
            truncated = False

        self._model.set_rows(display_rows)

        if not self._restore_selection():
            self._auto_select_first()

        shown = len(display_rows)
        message = self._format_status_message(
            shown=shown,
            total=total,
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            search_hint=search_hint,
        )
        self._status.showMessage(message)

        if shown == 0:
            self._details.clear_details()
            self._current_path = None

    def _format_status_message(
        self,
        *,
        shown: int,
        total: int,
        truncated: bool,
        elapsed_ms: float,
        search_hint: bool,
    ) -> str:
        if search_hint and shown == 0:
            base = "Introduce texto alfanumérico para buscar"
        elif total == 0:
            base = "Sin resultados"
        elif truncated:
            base = f"Mostrando {shown} de {total} pistas"
        else:
            base = f"{shown} pistas"
        return f"{base} · {elapsed_ms:.0f} ms"

    def _restore_selection(self) -> bool:
        if not self._current_path:
            return False
        row = self._model.index_for_path(self._current_path)
        if row is None:
            self._current_path = None
            return False
        self._select_row(row)
        return True

    def _auto_select_first(self) -> None:
        if self._model.rowCount() <= 0:
            return
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return
        if selection_model.hasSelection():
            return
        self._select_row(0)

    def _select_row(self, row: int) -> None:
        if row < 0 or row >= self._model.rowCount():
            return
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return
        index = self._model.index(row, 0)
        selection_model.select(
            index,
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self._table.scrollTo(index, QAbstractItemView.PositionAtCenter)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------
    def closeEvent(  # noqa: N802
        self, event: QCloseEvent
    ) -> None:  # pragma: no cover - UI callback
        if self._owns_connection and self._con is not None:
            try:
                self._con.close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("Error closing database connection", exc_info=True)
        self._con = None
        super().closeEvent(event)
