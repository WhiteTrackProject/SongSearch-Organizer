from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QCloseEvent, QColor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.db import connect, fts_query_from_text, init_db, query_tracks
from ..core.scanner import scan_path
from ..core.spectrum import open_external
from .details_panel import DetailsPanel
from .theme import ensure_styled_background

logger = logging.getLogger(__name__)

_ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"


def _load_icon(name: str) -> QIcon:
    """Return a ``QIcon`` for *name* if the asset exists."""

    path = _ICON_DIR / name
    return QIcon(str(path)) if path.exists() else QIcon()


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_windows() -> bool:
    return sys.platform.startswith("win")


class _ScanWorker(QThread):
    """Background worker that scans a directory without blocking the UI."""

    finished = Signal(Path)
    failed = Signal(object)

    def __init__(self, db_path: Path, target: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._target = target

    def run(self) -> None:  # pragma: no cover - heavy IO in background thread
        try:
            con = connect(self._db_path)
            try:
                scan_path(con, self._target)
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001 - propagate to UI thread
            logger.exception("Background scan failed: %s", exc)
            self.failed.emit(exc)
        else:
            self.finished.emit(self._target)


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
    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
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
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section][1]
            return None
        return section + 1

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
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
        self._db_path: Path | None = None
        if con is None:
            db_path = init_db(self._data_dir)
            con = connect(db_path)
            logger.info("Base de datos cargada desde %s", db_path)
            self._db_path = db_path
        else:
            self._db_path = self._resolve_db_path(con)
        self._con: sqlite3.Connection | None = con

        self._model = TrackTableModel(self)
        self._details = DetailsPanel(con=self._con, data_dir=self._data_dir, parent=self)
        self._details.btn_open.clicked.connect(self._open_selected_track)
        self._details.btn_reveal.clicked.connect(self._reveal_selected_track)
        self._details.btn_copy_path.clicked.connect(self._copy_selected_paths)
        self._current_path: str | None = None

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(self.SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.refresh_results)

        self._search = QLineEdit(self)
        self._table = QTableView(self)
        self._status = QStatusBar(self)

        self._btn_scan: QPushButton | None = None
        self._btn_enrich: QPushButton | None = None
        self._btn_spectrum: QPushButton | None = None
        self._scan_worker: _ScanWorker | None = None

        self._build_ui()
        self.refresh_results()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("SongSearch Organizer")
        self.resize(1280, 720)

        central = QWidget(self)
        central.setObjectName("MainContainer")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QWidget(central)
        header.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 24, 24, 12)
        header_layout.setSpacing(16)

        search_container = QWidget(header)
        search_container.setObjectName("SearchContainer")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)

        self._search.setPlaceholderText("Buscar título, artista, álbum, género o ruta…")
        self._search.setClearButtonEnabled(True)
        self._search.setObjectName("SearchField")
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.returnPressed.connect(self.refresh_results)
        search_layout.addWidget(self._search, 1)

        search_hint = QLabel("↵ ejecutar", search_container)
        search_hint.setObjectName("SearchHint")
        search_layout.addWidget(search_hint)

        header_layout.addWidget(search_container, 1, Qt.AlignVCenter)

        actions_container = QWidget(header)
        actions_container.setObjectName("HeaderActions")
        actions_layout = QHBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self._btn_scan = QPushButton(_load_icon("scan.png"), "Escanear…", actions_container)
        self._btn_scan.clicked.connect(self._open_scan_dialog)
        actions_layout.addWidget(self._btn_scan)

        self._btn_enrich = QPushButton(_load_icon("enrich.png"), "Enriquecer", actions_container)
        self._btn_enrich.clicked.connect(self._enrich_selected)
        self._btn_enrich.setEnabled(False)
        actions_layout.addWidget(self._btn_enrich)

        self._btn_spectrum = QPushButton(_load_icon("spectrum.png"), "Espectro", actions_container)
        self._btn_spectrum.clicked.connect(self._generate_spectrum_selected)
        self._btn_spectrum.setEnabled(False)
        actions_layout.addWidget(self._btn_spectrum)

        header_layout.addWidget(actions_container, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        splitter.setOpaqueResize(False)

        table_card = QFrame(splitter)
        table_card.setObjectName("TableCard")
        ensure_styled_background(table_card)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 18, 18, 18)
        table_layout.setSpacing(0)

        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_table_context_menu)
        header_view = self._table.horizontalHeader()
        header_view.setSectionsMovable(True)
        header_view.setStretchLastSection(True)
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        header_view.setHighlightSections(False)
        header_view.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table_layout.addWidget(self._table)

        details_card = QFrame(splitter)
        details_card.setObjectName("DetailsCard")
        ensure_styled_background(details_card)
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(18, 18, 18, 18)
        details_layout.setSpacing(0)
        details_layout.addWidget(self._details)

        for card in (table_card, details_card):
            shadow = QGraphicsDropShadowEffect(card)
            shadow.setBlurRadius(28)
            shadow.setOffset(0, 14)
            shadow.setColor(QColor(7, 10, 22, 150))
            card.setGraphicsEffect(shadow)

        splitter.addWidget(table_card)
        splitter.addWidget(details_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.setStatusBar(self._status)
        self._status.setObjectName("MainStatusBar")
        self._status.setSizeGripEnabled(False)
        self._status.showMessage("Listo")

        selection_model = self._table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _open_scan_dialog(self) -> None:  # pragma: no cover - UI callback
        if self._scan_worker is not None and self._scan_worker.isRunning():
            QMessageBox.information(
                self,
                "Escaneo en progreso",
                "Ya hay un escaneo ejecutándose. Espera a que finalice.",
            )
            return

        directory = QFileDialog.getExistingDirectory(
            self,
            "Selecciona la carpeta a escanear",
            str(self._data_dir),
        )
        if not directory:
            return

        self._start_scan(Path(directory))

    def _start_scan(self, directory: Path) -> None:
        db_path = self._db_path
        if db_path is None:
            QMessageBox.critical(
                self,
                "Base de datos no disponible",
                "No se pudo determinar la ruta de la base de datos para escanear.",
            )
            return
        if not directory.exists():
            QMessageBox.warning(
                self,
                "Carpeta no encontrada",
                f"La carpeta seleccionada no existe:\n{directory}",
            )
            return

        worker = _ScanWorker(db_path, directory, self)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(self._reset_scan_worker)
        worker.failed.connect(self._reset_scan_worker)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._scan_worker = worker
        if self._btn_scan is not None:
            self._btn_scan.setEnabled(False)
        self._status.showMessage(f"Escaneando {directory}…")
        worker.start()

    def _reset_scan_worker(self) -> None:
        if self._btn_scan is not None:
            self._btn_scan.setEnabled(True)
        self._scan_worker = None

    def _on_scan_finished(self, directory: Path) -> None:
        self._status.showMessage(f"Escaneo completado: {directory}", 5000)
        self.refresh_results()

    def _on_scan_failed(self, error: object) -> None:
        message = str(error) if error else "No se pudo completar el escaneo."
        QMessageBox.critical(self, "Error al escanear", message)
        self._status.showMessage("Error durante el escaneo", 5000)

    def _show_table_context_menu(self, pos: QPoint) -> None:  # pragma: no cover - UI callback
        index = self._table.indexAt(pos)
        if index.isValid():
            self._select_row(index.row())

        menu = self._build_table_menu()
        if menu is None:
            return

        global_pos = self._table.viewport().mapToGlobal(pos)
        menu.exec(global_pos)

    def _build_table_menu(self) -> QMenu | None:
        paths = self._selected_paths()
        if not paths:
            return None

        menu = QMenu(self)

        action_open = QAction(_load_icon("open.png"), "Abrir", menu)
        action_open.triggered.connect(self._open_selected_track)
        menu.addAction(action_open)

        action_reveal = QAction(_load_icon("reveal.png"), "Mostrar en carpeta", menu)
        action_reveal.triggered.connect(self._reveal_selected_track)
        menu.addAction(action_reveal)

        menu.addSeparator()

        action_spectrum = QAction(_load_icon("spectrum.png"), "Espectro", menu)
        action_spectrum.triggered.connect(self._generate_spectrum_selected)
        menu.addAction(action_spectrum)

        action_enrich = QAction(_load_icon("enrich.png"), "Enriquecer", menu)
        action_enrich.triggered.connect(self._enrich_selected)
        menu.addAction(action_enrich)

        action_copy = QAction(_load_icon("copy.png"), "Copiar ruta", menu)
        action_copy.triggered.connect(self._copy_selected_paths)
        menu.addAction(action_copy)

        return menu

    def _open_selected_track(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Sin selección", "Selecciona una pista para abrirla.")
            return

        path = paths[0]
        if not path.exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                f"No se encontró el archivo en disco:\n{path}",
            )
            return
        try:
            open_external(path)
        except Exception as exc:  # noqa: BLE001 - show feedback to user
            QMessageBox.critical(
                self,
                "Error al abrir",
                f"No se pudo abrir el archivo:\n{exc}",
            )

    def _reveal_selected_track(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(
                self,
                "Sin selección",
                "Selecciona una pista para mostrarla en el explorador.",
            )
            return

        self._reveal_in_file_manager(paths[0])

    def _copy_selected_paths(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Sin selección", "No hay rutas para copiar.")
            return

        clipboard = QGuiApplication.clipboard()
        clipboard.setText("\n".join(str(p) for p in paths))
        self._status.showMessage("Ruta copiada al portapapeles", 3000)

    def _enrich_selected(self) -> None:
        if not self._current_path:
            QMessageBox.information(
                self,
                "Sin selección",
                "Selecciona una pista antes de enriquecer metadatos.",
            )
            return
        # Delegamos en el panel de detalles para reutilizar la lógica existente.
        self._details.btn_enrich.click()

    def _generate_spectrum_selected(self) -> None:
        if not self._current_path:
            QMessageBox.information(
                self,
                "Sin selección",
                "Selecciona una pista antes de generar el espectro.",
            )
            return
        self._details.btn_spectrum.click()

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
            self._update_action_state()
            return
        index = selected.indexes()[0]
        data = self._model.row_data(index.row())
        if not data:
            self._current_path = None
            self._details.clear_details()
            self._update_action_state()
            return
        path = data.get("path")
        self._current_path = path if isinstance(path, str) else None
        if self._current_path:
            self._details.show_for_path(self._current_path, record=data)
        else:
            self._details.clear_details()
        self._update_action_state()

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
        self._update_action_state()

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
    # Helpers
    # ------------------------------------------------------------------
    def _selected_paths(self) -> list[Path]:
        selection_model = self._table.selectionModel()
        paths: list[Path] = []
        if selection_model is not None:
            for index in selection_model.selectedRows():
                record = self._model.row_data(index.row())
                path_value = record.get("path") if record else None
                if isinstance(path_value, str):
                    paths.append(Path(path_value))
        if not paths and self._current_path:
            paths.append(Path(self._current_path))
        return paths

    def _reveal_in_file_manager(self, path: Path) -> None:
        target = path if path.exists() else path.parent
        if target is None or not target.exists():
            target = Path.home()
        try:
            if _is_macos():
                if path.is_dir():
                    subprocess.Popen(["open", str(target)])
                else:
                    subprocess.Popen(["open", "-R", str(path)])
            elif _is_windows():
                if path.exists() and path.is_file():
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    subprocess.Popen(["explorer", str(target)])
            else:
                launch_target = path if path.is_dir() else target
                subprocess.Popen(["xdg-open", str(launch_target)])
        except Exception as exc:  # noqa: BLE001 - show UI feedback
            QMessageBox.critical(
                self,
                "Mostrar en carpeta",
                f"No se pudo abrir el explorador de archivos:\n{exc}",
            )

    def _update_action_state(self) -> None:
        has_selection = bool(self._current_path)
        if self._btn_enrich is not None:
            self._btn_enrich.setEnabled(has_selection)
        if self._btn_spectrum is not None:
            self._btn_spectrum.setEnabled(has_selection)

    def _resolve_db_path(self, con: sqlite3.Connection | None) -> Path | None:
        if con is None:
            return None
        try:
            row = con.execute("PRAGMA database_list").fetchone()
        except Exception:  # pragma: no cover - defensive
            return None
        if not row:
            return None
        path_str = row[2]
        if not path_str:
            return None
        try:
            return Path(path_str)
        except Exception:  # pragma: no cover - fallback for exotic paths
            return None

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
