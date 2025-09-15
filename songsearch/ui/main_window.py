from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.cover_art import ensure_cover_for_path
from ..core.db import connect, fts_query_from_text, get_by_path, init_db, query_tracks
from ..core.scanner import scan_path

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".songsearch"
DB_PATH = init_db(DATA_DIR)

ICON_SIZE = 64
TOOLTIP_PREVIEW_SIZE = 256


class ScanThread(QThread):
    finished = Signal()

    def __init__(self, db_path: Path, path: str):
        super().__init__()
        self.db_path = Path(db_path)
        self.path = path

    def run(self):
        con = None
        try:
            con = connect(self.db_path)
            scan_path(
                con,
                Path(self.path),
                should_interrupt=self.isInterruptionRequested,
            )
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Error while scanning %s", self.path)
        finally:
            if con is not None:
                con.close()
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SongSearch Organizer (v{__version__})")
        self.resize(1100, 700)
        self.con = connect(DB_PATH)
        self._visible_paths: set[str] = set()
        self._scan_thread: ScanThread | None = None

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Buscar (título, artista, álbum, género, ruta)…")
        self.search.textChanged.connect(self.refresh)

        self.btn_scan = QPushButton("Escanear carpeta…")
        self.btn_scan.clicked.connect(self.scan_dialog)

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filtro:"))
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_scan)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Título", "Artista", "Álbum", "Género", "Año", "Ruta"]
        )
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.table.verticalHeader().setDefaultSectionSize(ICON_SIZE + 12)

        root = QWidget(self)
        lay = QVBoxLayout(root)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.progress)
        self.setCentralWidget(root)

        self.refresh()

    def refresh(self):
        t0 = time.perf_counter()
        text = self.search.text().strip()
        if text:
            fts_query = fts_query_from_text(text)
            if fts_query:
                rows = query_tracks(self.con, fts_query=fts_query)
            else:
                rows = []
        else:
            rows = query_tracks(self.con)
        header = self.table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        sort_enabled = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._visible_paths.clear()
        for r in rows[:5000]:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            self._set_row_from_data(row_idx, r)
        self.table.setSortingEnabled(sort_enabled)
        if sort_enabled and sort_section >= 0:
            self.table.sortItems(sort_section, sort_order)
        elapsed = time.perf_counter() - t0
        self.statusBar().showMessage(f"{len(rows)} resultados en {elapsed:.3f} s")

    def _set_row_from_data(self, row_idx: int, row_data) -> None:
        if isinstance(row_data, dict):
            data_map = row_data
        else:
            data_map = dict(row_data)
        icon, tooltip, cover_art_path = self._cover_icon_and_tooltip(data_map)
        columns = [
            ("title", 0),
            ("artist", 1),
            ("album", 2),
            ("genre", 3),
            ("year", 4),
            ("path", 5),
        ]
        for key, column in columns:
            value = data_map.get(key)
            text = "" if value is None else str(value)
            item = self.table.item(row_idx, column)
            if item is None:
                item = QTableWidgetItem(text)
                self.table.setItem(row_idx, column, item)
            else:
                item.setText(text)
            if column == 0:
                item.setData(Qt.UserRole, data_map.get("path"))
                item.setData(Qt.UserRole + 1, str(cover_art_path) if cover_art_path else None)
                item.setData(Qt.UserRole + 2, data_map.get("cover_art_url"))
                item.setIcon(icon if icon is not None else QIcon())
            item.setToolTip(tooltip or "")
        self._visible_paths.add(data_map["path"])

    def _cover_icon_and_tooltip(self, data_map) -> tuple[QIcon | None, str | None, Path | None]:
        track_path = data_map.get("path")
        if not track_path:
            return None, None, None
        cover_art_url = data_map.get("cover_art_url")
        cover_art_path = self._ensure_cover_art(track_path, cover_art_url)
        if not cover_art_path:
            return None, None, None
        pixmap = QPixmap(str(cover_art_path))
        if pixmap.isNull():
            logger.debug("Pixmap is null for cover %s", cover_art_path)
            return None, None, None
        icon_pixmap = pixmap.scaled(
            ICON_SIZE, ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        icon = QIcon(icon_pixmap)
        try:
            resolved = cover_art_path.resolve()
        except Exception:  # pragma: no cover - fallback for exotic paths
            resolved = cover_art_path
            try:
                resolved = cover_art_path.absolute()
            except Exception:
                pass
        try:
            uri = resolved.as_uri()
        except Exception:  # pragma: no cover - final fallback
            uri = f"file://{resolved.as_posix()}"
        tooltip = (
            f'<div style="margin:4px"><img src="{uri}" width="{TOOLTIP_PREVIEW_SIZE}" /></div>'
        )
        return icon, tooltip, cover_art_path

    def _ensure_cover_art(self, track_path: str, cover_art_url: str | None) -> Path | None:
        if not track_path:
            return None
        try:
            return ensure_cover_for_path(DATA_DIR, Path(track_path), cover_art_url)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Cannot resolve cover for %s: %s", track_path, exc)
            return None

    def _find_row_index_by_path(self, path: str) -> int | None:
        if not path:
            return None
        for idx in range(self.table.rowCount()):
            item = self.table.item(idx, 5)
            if item and item.text() == path:
                return idx
        return None

    def refresh_cover_for_path(self, path: str):
        if not path:
            return
        if self._visible_paths and path not in self._visible_paths:
            return
        row_idx = self._find_row_index_by_path(path)
        if row_idx is None:
            return
        row_data = get_by_path(self.con, path)
        if not row_data:
            return
        self._set_row_from_data(row_idx, row_data)
        if self.table.isSortingEnabled():
            header = self.table.horizontalHeader()
            section = header.sortIndicatorSection()
            order = header.sortIndicatorOrder()
            if section >= 0:
                self.table.sortItems(section, order)

    def refresh_covers_for_paths(self, paths: Iterable[str]):
        for path in paths:
            self.refresh_cover_for_path(path)

    def scan_dialog(self):
        if self._scan_thread is not None and self._scan_thread.isRunning():
            QMessageBox.warning(
                self,
                "Escaneo en progreso",
                "Ya hay un escaneo en curso. Espera a que termine antes de iniciar otro.",
            )
            return
        d = QFileDialog.getExistingDirectory(self, "Selecciona carpeta de música")
        if d:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self._scan_thread = ScanThread(DB_PATH, d)
            self._scan_thread.finished.connect(self.on_scan_finished)
            self._scan_thread.start()

    def on_scan_finished(self):
        self.progress.setVisible(False)
        self._scan_thread = None
        self.refresh()
        logger.info("scan completed")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  # pragma: no cover - GUI specific
        thread = self._scan_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.wait()
            thread.deleteLater()
            self._scan_thread = None
            self.progress.setVisible(False)
        super().closeEvent(event)
