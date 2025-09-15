from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QAction,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from .. import __version__
from ..core.cover_art import ensure_cover_for_path
from ..core.db import connect, fts_query_from_text, get_by_path, init_db, query_tracks
from ..core.metadata_enricher import enrich_file
from ..core.scanner import scan_path
from ..integrations.rekordbox import RekordboxAdapter, export_playlist_to_m3u
from .details_panel import DetailsPanel

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".songsearch"
DB_PATH = init_db(DATA_DIR)

ICON_SIZE = 64
TOOLTIP_PREVIEW_SIZE = 256
MAX_VISIBLE_ROWS = 5000
BATCH_ENRICH_LIMIT = 50


class ScanThread(QThread):
    finished = Signal()

    def __init__(self, db_path: Path, path: str):
        super().__init__()
        self.db_path = Path(db_path)
        self.path = path

    def run(self) -> None:  # pragma: no cover - Qt threading integration
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


class BatchEnrichThread(QThread):
    finished_with_counts = Signal(int, int)
    error = Signal(str)

    def __init__(
        self,
        db_path: Path,
        paths: Iterable[str],
        *,
        min_confidence: float = 0.6,
        write_tags: bool = False,
    ) -> None:
        super().__init__()
        self._db_path = Path(db_path)
        self._paths = [Path(p) for p in paths if p]
        self._min_confidence = float(min_confidence)
        self._write_tags = bool(write_tags)

    def run(self) -> None:  # pragma: no cover - Qt threading integration
        if not self._paths:
            self.finished_with_counts.emit(0, 0)
            return

        con = connect(self._db_path)
        ok = 0
        fail = 0
        error_message: str | None = None
        try:
            for path in self._paths:
                if self.isInterruptionRequested():
                    break
                if not path.exists():
                    logger.debug("Skipping missing file during enrich: %s", path)
                    continue
                try:
                    updated = enrich_file(
                        con,
                        path,
                        min_confidence=self._min_confidence,
                        write_tags=self._write_tags,
                    )
                except RuntimeError as exc:
                    error_message = str(exc)
                    fail += 1
                    logger.warning("Enrich aborted for %s: %s", path, exc)
                    break
                except Exception as exc:  # pragma: no cover - defensive logging
                    fail += 1
                    logger.exception("Unexpected error enriching %s: %s", path, exc)
                else:
                    if updated:
                        ok += 1
        finally:
            con.close()

        if error_message:
            self.error.emit(error_message)
        self.finished_with_counts.emit(ok, fail)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"SongSearch Organizer (v{__version__})")
        self.resize(1200, 760)

        self.con = connect(DB_PATH)
        self._visible_paths: set[str] = set()
        self._scan_thread: ScanThread | None = None
        self._batch_enrich_thread: BatchEnrichThread | None = None
        self._rekordbox_adapter: RekordboxAdapter | None = None

        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_tabs()

        self.refresh()
        self._reload_rekordbox()

    # ------------------------------------------------------------------
    # UI setup helpers
    # ------------------------------------------------------------------
    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("Acciones", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        self.action_scan = QAction("Escanear…", self)
        self.action_scan.triggered.connect(self.scan_dialog)
        toolbar.addAction(self.action_scan)

        self.action_enrich = QAction("Enriquecer", self)
        self.action_enrich.triggered.connect(self._enrich_selected_tracks)
        toolbar.addAction(self.action_enrich)

        self.action_spectrum = QAction("Espectro", self)
        self.action_spectrum.triggered.connect(self._spectrum_selected_tracks)
        toolbar.addAction(self.action_spectrum)

        self.action_organize = QAction("Organizar…", self)
        self.action_organize.triggered.connect(self._show_organize_hint)
        toolbar.addAction(self.action_organize)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Filtro:", self))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Buscar (título, artista, álbum, género, ruta)…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.setMinimumWidth(240)
        toolbar.addWidget(self.search)

    def _setup_statusbar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)

        self.status_count = QLabel("0 resultados", self)
        self.status_info = QLabel("Listo", self)

        status.addWidget(self.status_count)
        status.addPermanentWidget(self.status_info)

        self.progress = QProgressBar(self)
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(180)
        self.progress.setRange(0, 0)
        status.addPermanentWidget(self.progress)

    def _setup_tabs(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)

        self._setup_library_tab()
        self._setup_rekordbox_tab()

        self.setCentralWidget(self.tabs)

    def _setup_library_tab(self) -> None:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal, container)

        self.library_table = QTableWidget(0, 6, splitter)
        self.library_table.setHorizontalHeaderLabels(
            ["Título", "Artista", "Álbum", "Género", "Año", "Ruta"]
        )
        self.library_table.setSortingEnabled(True)
        self.library_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library_table.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.library_table.verticalHeader().setDefaultSectionSize(ICON_SIZE + 12)
        self.library_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.library_table.customContextMenuRequested.connect(self._show_library_context_menu)
        self.library_table.itemSelectionChanged.connect(self._on_library_selection_changed)

        splitter.addWidget(self.library_table)

        self.details_panel = DetailsPanel(self.con, DATA_DIR, splitter)
        splitter.addWidget(self.details_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self.tabs.addTab(container, "Biblioteca")

    def _setup_rekordbox_tab(self) -> None:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)

        self.rb_status_label = QLabel("Rekordbox no detectado", container)
        self.rb_status_label.setWordWrap(True)
        header.addWidget(self.rb_status_label, 1)

        self.rb_badge_label = QLabel(container)
        self.rb_badge_label.setObjectName("rekordboxBadge")
        self.rb_badge_label.setStyleSheet(
            "QLabel#rekordboxBadge {"
            " border-radius: 8px;"
            " padding: 2px 8px;"
            " font-weight: 600;"
            " color: white;"
            " background-color: #555555;"
            "}"
        )
        self.rb_badge_label.setVisible(False)
        header.addWidget(self.rb_badge_label)

        self.rb_reload_button = QPushButton("Recargar", container)
        self.rb_reload_button.clicked.connect(self._reload_rekordbox)
        header.addWidget(self.rb_reload_button)

        self.rb_create_button = QPushButton("Crear playlist", container)
        self.rb_create_button.clicked.connect(self._create_rekordbox_playlist)
        header.addWidget(self.rb_create_button)

        self.rb_delete_button = QPushButton("Borrar playlist", container)
        self.rb_delete_button.clicked.connect(self._delete_rekordbox_playlist)
        header.addWidget(self.rb_delete_button)

        self.rb_add_button = QPushButton("Añadir pistas", container)
        self.rb_add_button.clicked.connect(self._add_tracks_to_rekordbox)
        header.addWidget(self.rb_add_button)

        self.rb_remove_button = QPushButton("Eliminar pistas", container)
        self.rb_remove_button.clicked.connect(self._remove_tracks_from_rekordbox)
        header.addWidget(self.rb_remove_button)

        self.rb_export_button = QPushButton("Exportar M3U", container)
        self.rb_export_button.clicked.connect(self._export_rekordbox_playlist)
        header.addWidget(self.rb_export_button)

        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal, container)
        self.rb_tree = QTreeWidget(splitter)
        self.rb_tree.setHeaderLabels(["Playlists"])
        self.rb_tree.itemSelectionChanged.connect(self._on_rekordbox_selection_changed)

        self.rb_table = QTableWidget(0, 3, splitter)
        self.rb_table.setHorizontalHeaderLabels(["Título", "Artista", "Ruta"])
        self.rb_table.setSortingEnabled(True)
        self.rb_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rb_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rb_table.itemSelectionChanged.connect(self._update_rekordbox_selection_buttons)

        splitter.addWidget(self.rb_tree)
        splitter.addWidget(self.rb_table)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self.tabs.addTab(container, "Rekordbox")

    # ------------------------------------------------------------------
    # Biblioteca
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        t0 = time.perf_counter()
        text = self.search.text().strip()
        if text:
            fts_query = fts_query_from_text(text)
            rows = query_tracks(self.con, fts_query=fts_query) if fts_query else []
        else:
            rows = query_tracks(self.con)

        header = self.library_table.horizontalHeader()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        sorting_enabled = self.library_table.isSortingEnabled()

        self.library_table.setSortingEnabled(False)
        selected_path = self._current_selected_path()

        self.library_table.setRowCount(0)
        self._visible_paths.clear()
        for row in rows[:MAX_VISIBLE_ROWS]:
            row_idx = self.library_table.rowCount()
            self.library_table.insertRow(row_idx)
            self._set_row_from_data(row_idx, row)

        self.library_table.setSortingEnabled(sorting_enabled)
        if sorting_enabled and sort_section >= 0:
            self.library_table.sortItems(sort_section, sort_order)

        total = len(rows)
        visible = min(total, MAX_VISIBLE_ROWS)
        elapsed = time.perf_counter() - t0
        self.status_count.setText(f"{visible} / {total} resultados")
        self.status_info.setText(f"Consulta en {elapsed:.3f} s")

        if selected_path:
            self._reselect_path(selected_path)
        elif total == 0:
            self.details_panel.clear_details()

    def _set_row_from_data(self, row_idx: int, row_data: Any) -> None:
        if isinstance(row_data, dict):
            data_map = row_data
        else:
            try:
                data_map = dict(row_data)
            except Exception:  # pragma: no cover - defensive conversion
                data_map = {}

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
            item = self.library_table.item(row_idx, column)
            if item is None:
                item = QTableWidgetItem(text)
                self.library_table.setItem(row_idx, column, item)
            else:
                item.setText(text)
            if column == 0:
                item.setData(Qt.UserRole, data_map.get("path"))
                item.setData(Qt.UserRole + 1, str(cover_art_path) if cover_art_path else None)
                item.setData(Qt.UserRole + 2, data_map.get("cover_art_url"))
                item.setIcon(icon if icon is not None else QIcon())
            item.setToolTip(tooltip or "")
        if data_map.get("path"):
            self._visible_paths.add(data_map["path"])

    def _cover_icon_and_tooltip(
        self, data_map: dict[str, Any]
    ) -> tuple[QIcon | None, str | None, Path | None]:
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

    def _current_selected_path(self) -> str | None:
        paths = self._selected_library_paths()
        return paths[0] if paths else None

    def _reselect_path(self, path: str) -> None:
        idx = self._find_row_index_by_path(path)
        if idx is None:
            self.details_panel.clear_details()
            return
        self.library_table.blockSignals(True)
        self.library_table.selectRow(idx)
        self.library_table.blockSignals(False)
        self._on_library_selection_changed()
        self.library_table.scrollToItem(self.library_table.item(idx, 0))

    def _find_row_index_by_path(self, path: str) -> int | None:
        if not path:
            return None
        for idx in range(self.library_table.rowCount()):
            item = self.library_table.item(idx, 5)
            if item and item.text() == path:
                return idx
        return None

    def refresh_cover_for_path(self, path: str) -> None:
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
        if self.library_table.isSortingEnabled():
            header = self.library_table.horizontalHeader()
            section = header.sortIndicatorSection()
            order = header.sortIndicatorOrder()
            if section >= 0:
                self.library_table.sortItems(section, order)

    def refresh_covers_for_paths(self, paths: Iterable[str]) -> None:
        for path in paths:
            self.refresh_cover_for_path(path)

    def _selected_library_paths(self) -> list[str]:
        selection = self.library_table.selectionModel()
        if selection is None:
            return []
        paths: list[str] = []
        for index in selection.selectedRows():
            item = self.library_table.item(index.row(), 5)
            if item:
                paths.append(item.text())
        return paths

    def _on_library_selection_changed(self) -> None:
        paths = self._selected_library_paths()
        if not paths:
            self.details_panel.clear_details()
            return
        path = paths[0]
        record = None
        try:
            record = get_by_path(self.con, path)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Cannot fetch record for %s: %s", path, exc)
        self.details_panel.show_for_path(path, record)

    def _show_library_context_menu(self, pos: QPoint) -> None:
        paths = self._selected_library_paths()
        menu = QMenu(self)
        open_action = menu.addAction("Abrir…")
        open_action.setEnabled(bool(paths))
        open_action.triggered.connect(self._open_selected_track)

        reveal_action = menu.addAction("Mostrar en carpeta")
        reveal_action.setEnabled(bool(paths))
        reveal_action.triggered.connect(self._reveal_selected_track)

        copy_action = menu.addAction("Copiar ruta")
        copy_action.setEnabled(bool(paths))
        copy_action.triggered.connect(self._copy_selected_path)

        menu.addSeparator()

        enrich_action = menu.addAction("Enriquecer metadatos")
        enrich_action.setEnabled(bool(paths))
        enrich_action.triggered.connect(self._enrich_selected_tracks)

        spectrum_action = menu.addAction("Generar espectro")
        spectrum_action.setEnabled(bool(paths))
        spectrum_action.triggered.connect(self._spectrum_selected_tracks)

        menu.exec(self.library_table.viewport().mapToGlobal(pos))

    def _open_selected_track(self) -> None:
        paths = self._selected_library_paths()
        if not paths:
            return
        file_path = Path(paths[0])
        if not file_path.exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                f"No se encontró el archivo:\n{file_path}",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))

    def _reveal_selected_track(self) -> None:
        paths = self._selected_library_paths()
        if not paths:
            return
        file_path = Path(paths[0])
        if not file_path.exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                f"No se encontró el archivo:\n{file_path}",
            )
            return
        try:
            if sys.platform == "darwin":
                subprocess.call(["open", "-R", str(file_path)])
            elif os.name == "nt":
                subprocess.call(["explorer", f"/select,{file_path}"])
            else:
                subprocess.call(["xdg-open", str(file_path.parent)])
        except Exception as exc:  # pragma: no cover - platform dependent
            QMessageBox.warning(self, "No se pudo abrir la carpeta", str(exc))

    def _copy_selected_path(self) -> None:
        paths = self._selected_library_paths()
        if not paths:
            return
        QApplication.clipboard().setText(paths[0])
        self.status_info.setText("Ruta copiada al portapapeles")

    def _enrich_selected_tracks(self) -> None:
        if self._batch_enrich_thread is not None and self._batch_enrich_thread.isRunning():
            return
        paths = self._selected_library_paths()
        if not paths:
            QMessageBox.information(self, "Enriquecer", "Selecciona al menos una pista.")
            return
        limited = paths[:BATCH_ENRICH_LIMIT]
        thread = BatchEnrichThread(DB_PATH, limited)
        thread.finished_with_counts.connect(self._on_batch_enrich_finished)
        thread.finished.connect(self._on_batch_enrich_thread_done)
        thread.error.connect(self._on_batch_enrich_error)
        thread.start()
        self._batch_enrich_thread = thread
        self.action_enrich.setEnabled(False)
        self.status_info.setText(f"Enriqueciendo {len(limited)} pistas…")

    def _on_batch_enrich_finished(self, ok: int, fail: int) -> None:
        if ok or fail:
            self.status_info.setText(f"Enriquecidas {ok}, errores {fail}")
        else:
            self.status_info.setText("Enriquecimiento completado")
        self.refresh()

    def _on_batch_enrich_thread_done(self) -> None:
        thread = self._batch_enrich_thread
        if thread is not None:
            thread.deleteLater()
        self._batch_enrich_thread = None
        self.action_enrich.setEnabled(True)

    def _on_batch_enrich_error(self, message: str) -> None:
        QMessageBox.warning(self, "Enriquecer", message)

    def _spectrum_selected_tracks(self) -> None:
        paths = self._selected_library_paths()
        if not paths:
            QMessageBox.information(self, "Espectro", "Selecciona una pista.")
            return
        path = Path(paths[0])
        if not path.exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                f"No se encontró el archivo:\n{path}",
            )
            return
        self.details_panel.show_for_path(str(path))
        self.details_panel.btn_spectrum.click()

    def _show_organize_hint(self) -> None:
        QMessageBox.information(
            self,
            "Organizar",
            "La organización avanzada está disponible desde la CLI:\n"
            "songsearch organize --help",
        )

    # ------------------------------------------------------------------
    # Rekordbox
    # ------------------------------------------------------------------
    def _reload_rekordbox(self) -> None:
        self._rekordbox_adapter = RekordboxAdapter.detect()
        adapter = self._rekordbox_adapter

        self.rb_tree.clear()
        self.rb_table.setRowCount(0)

        if adapter is None:
            self.rb_status_label.setText(
                "Rekordbox no detectado. Configura REKORDBOX_DB_PATH para activar la integración."
            )
            self._update_rekordbox_badge(None)
            self._set_rekordbox_controls_enabled(False)
            return

        playlists = adapter.list_playlists()
        if playlists:
            self.rb_status_label.setText(f"DB: {adapter.db_path}")
        else:
            self.rb_status_label.setText(f"DB: {adapter.db_path} (sin playlists)")
        self._populate_rekordbox_tree(playlists)
        self._update_rekordbox_badge(adapter)
        self._set_rekordbox_controls_enabled(True)
        self._update_rekordbox_selection_buttons()

    def _populate_rekordbox_tree(self, playlists: Iterable[dict[str, Any]]) -> None:
        items: dict[Any, QTreeWidgetItem] = {}
        for playlist in playlists:
            name = str(playlist.get("name") or "(sin nombre)")
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.UserRole, playlist)
            items[playlist.get("id")] = item
        for playlist in playlists:
            item = items.get(playlist.get("id"))
            if item is None:
                continue
            parent_id = playlist.get("parent_id")
            parent_item = items.get(parent_id)
            if parent_item is not None and parent_item is not item:
                parent_item.addChild(item)
            else:
                self.rb_tree.addTopLevelItem(item)
        self.rb_tree.expandToDepth(0)

    def _update_rekordbox_badge(self, adapter: RekordboxAdapter | None) -> None:
        if adapter is None:
            self.rb_badge_label.setVisible(False)
            return
        if adapter.can_write:
            self.rb_badge_label.setText("Experimental")
            self.rb_badge_label.setStyleSheet(
                "QLabel#rekordboxBadge {"
                " border-radius: 8px;"
                " padding: 2px 8px;"
                " font-weight: 600;"
                " color: #3b2000;"
                " background-color: #ffcf66;"
                "}"
            )
        else:
            self.rb_badge_label.setText("Solo lectura")
            self.rb_badge_label.setStyleSheet(
                "QLabel#rekordboxBadge {"
                " border-radius: 8px;"
                " padding: 2px 8px;"
                " font-weight: 600;"
                " color: white;"
                " background-color: #555555;"
                "}"
            )
        self.rb_badge_label.setVisible(True)

    def _set_rekordbox_controls_enabled(self, enabled: bool) -> None:
        self.rb_tree.setEnabled(enabled)
        self.rb_table.setEnabled(enabled)
        self.rb_export_button.setEnabled(enabled)
        self.rb_reload_button.setEnabled(True)
        write_enabled = bool(enabled and self._rekordbox_adapter and self._rekordbox_adapter.can_write)
        for button in (self.rb_create_button, self.rb_delete_button, self.rb_add_button, self.rb_remove_button):
            button.setEnabled(write_enabled)

    def _current_rekordbox_playlist(self) -> dict[str, Any] | None:
        selected = self.rb_tree.selectedItems()
        if not selected:
            return None
        data = selected[0].data(0, Qt.UserRole)
        if isinstance(data, dict):
            return data
        try:
            return dict(data)  # type: ignore[arg-type]
        except Exception:
            return None

    def _on_rekordbox_selection_changed(self) -> None:
        adapter = self._rekordbox_adapter
        playlist = self._current_rekordbox_playlist()
        if adapter is None or playlist is None:
            self.rb_table.setRowCount(0)
            self._update_rekordbox_selection_buttons()
            return
        rows = adapter.list_tracks_in_playlist(playlist.get("id"))
        self._populate_rekordbox_tracks(rows)
        self._update_rekordbox_selection_buttons()

    def _populate_rekordbox_tracks(self, rows: Iterable[dict[str, Any]]) -> None:
        self.rb_table.setRowCount(0)
        for row in rows:
            idx = self.rb_table.rowCount()
            self.rb_table.insertRow(idx)
            self.rb_table.setItem(idx, 0, QTableWidgetItem(str(row.get("title") or "")))
            self.rb_table.setItem(idx, 1, QTableWidgetItem(str(row.get("artist") or "")))
            self.rb_table.setItem(idx, 2, QTableWidgetItem(str(row.get("path") or "")))

    def _update_rekordbox_selection_buttons(self) -> None:
        adapter = self._rekordbox_adapter
        playlist_selected = self._current_rekordbox_playlist() is not None
        write_enabled = bool(adapter and adapter.can_write and playlist_selected)
        self.rb_delete_button.setEnabled(write_enabled)
        self.rb_add_button.setEnabled(write_enabled)
        has_track_selection = bool(self.rb_table.selectionModel() and self.rb_table.selectionModel().selectedRows())
        self.rb_remove_button.setEnabled(write_enabled and has_track_selection)
        self.rb_export_button.setEnabled(bool(adapter) and playlist_selected)

    def _create_rekordbox_playlist(self) -> None:
        adapter = self._rekordbox_adapter
        if not adapter:
            QMessageBox.information(self, "Rekordbox", "No se detectó ninguna base de datos.")
            return
        if not adapter.can_write:
            QMessageBox.information(self, "Rekordbox", "La integración está en modo solo lectura.")
            return
        parent = self._current_rekordbox_playlist()
        name, ok = QInputDialog.getText(self, "Nueva playlist", "Nombre:")
        if not ok or not name:
            return
        try:
            adapter.create_playlist(name, parent_id=parent.get("id") if parent else None)
        except Exception as exc:  # pragma: no cover - optional integration
            QMessageBox.warning(self, "Rekordbox", str(exc))
            return
        self._reload_rekordbox()

    def _delete_rekordbox_playlist(self) -> None:
        adapter = self._rekordbox_adapter
        playlist = self._current_rekordbox_playlist()
        if not adapter or not playlist:
            QMessageBox.information(self, "Rekordbox", "Selecciona una playlist.")
            return
        if not adapter.can_write:
            QMessageBox.information(self, "Rekordbox", "La integración está en modo solo lectura.")
            return
        confirm = QMessageBox.question(
            self,
            "Borrar playlist",
            f"¿Seguro que quieres borrar '{playlist.get('name')}'?",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            adapter.delete_playlist(playlist.get("id"))
        except Exception as exc:  # pragma: no cover - optional integration
            QMessageBox.warning(self, "Rekordbox", str(exc))
            return
        self._reload_rekordbox()

    def _add_tracks_to_rekordbox(self) -> None:
        adapter = self._rekordbox_adapter
        playlist = self._current_rekordbox_playlist()
        if not adapter or not playlist:
            QMessageBox.information(self, "Rekordbox", "Selecciona una playlist.")
            return
        if not adapter.can_write:
            QMessageBox.information(self, "Rekordbox", "La integración está en modo solo lectura.")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Añadir pistas", str(Path.home()))
        if not files:
            return
        try:
            added = adapter.add_tracks_to_playlist(playlist.get("id"), files)
        except Exception as exc:  # pragma: no cover - optional integration
            QMessageBox.warning(self, "Rekordbox", str(exc))
            return
        QMessageBox.information(
            self,
            "Rekordbox",
            f"Añadidas {added} pistas a '{playlist.get('name')}'.",
        )
        self._on_rekordbox_selection_changed()

    def _remove_tracks_from_rekordbox(self) -> None:
        adapter = self._rekordbox_adapter
        playlist = self._current_rekordbox_playlist()
        if not adapter or not playlist:
            QMessageBox.information(self, "Rekordbox", "Selecciona una playlist.")
            return
        if not adapter.can_write:
            QMessageBox.information(self, "Rekordbox", "La integración está en modo solo lectura.")
            return
        selection = self.rb_table.selectionModel()
        if selection is None:
            QMessageBox.information(self, "Rekordbox", "Selecciona al menos una pista.")
            return
        paths = []
        for idx in selection.selectedRows():
            item = self.rb_table.item(idx.row(), 2)
            if item:
                paths.append(item.text())
        if not paths:
            QMessageBox.information(self, "Rekordbox", "Selecciona al menos una pista.")
            return
        try:
            removed = adapter.remove_tracks_from_playlist(playlist.get("id"), paths)
        except Exception as exc:  # pragma: no cover - optional integration
            QMessageBox.warning(self, "Rekordbox", str(exc))
            return
        QMessageBox.information(
            self,
            "Rekordbox",
            f"Eliminadas {removed} pistas de '{playlist.get('name')}'.",
        )
        self._on_rekordbox_selection_changed()

    def _export_rekordbox_playlist(self) -> None:
        adapter = self._rekordbox_adapter
        playlist = self._current_rekordbox_playlist()
        if not adapter or not playlist:
            QMessageBox.information(self, "Rekordbox", "Selecciona una playlist.")
            return
        rows = adapter.list_tracks_in_playlist(playlist.get("id"))
        if not rows:
            QMessageBox.information(self, "Rekordbox", "La playlist está vacía.")
            return
        default_name = str(playlist.get("name") or "playlist").replace("/", "-")
        out, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar playlist",
            f"{default_name}.m3u8",
            "Playlists (*.m3u *.m3u8)",
        )
        if not out:
            return
        try:
            export_playlist_to_m3u(rows, out)
        except Exception as exc:  # pragma: no cover - IO heavy
            QMessageBox.warning(self, "Rekordbox", str(exc))
            return
        QMessageBox.information(self, "Rekordbox", f"Exportada a {out}")

    # ------------------------------------------------------------------
    # Escaneo
    # ------------------------------------------------------------------
    def scan_dialog(self) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            QMessageBox.warning(
                self,
                "Escaneo en progreso",
                "Ya hay un escaneo en curso. Espera a que termine antes de iniciar otro.",
            )
            return
        directory = QFileDialog.getExistingDirectory(self, "Selecciona carpeta de música")
        if not directory:
            return
        self.progress.setVisible(True)
        self.action_scan.setEnabled(False)
        self.status_info.setText(f"Escaneando {directory}…")
        thread = ScanThread(DB_PATH, directory)
        thread.finished.connect(self.on_scan_finished)
        thread.start()
        self._scan_thread = thread

    def on_scan_finished(self) -> None:
        self.progress.setVisible(False)
        self.action_scan.setEnabled(True)
        self._scan_thread = None
        self.status_info.setText("Escaneo completado")
        self.refresh()
        logger.info("scan completed")

    # ------------------------------------------------------------------
    # Qt lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        thread = self._scan_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.wait()
            thread.deleteLater()
            self._scan_thread = None
        enrich_thread = self._batch_enrich_thread
        if enrich_thread is not None and enrich_thread.isRunning():
            enrich_thread.requestInterruption()
            enrich_thread.wait()
            enrich_thread.deleteLater()
            self._batch_enrich_thread = None
        try:
            self.con.close()
        except Exception:
            pass
        super().closeEvent(event)
