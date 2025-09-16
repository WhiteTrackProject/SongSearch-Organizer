from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
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
from PySide6.QtGui import QAction, QCloseEvent, QColor, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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
    QShortcut,
    QSplitter,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from dotenv import dotenv_values, find_dotenv, load_dotenv, set_key

from .. import __version__
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


class ApiCredentialsDialog(QDialog):
    """Simple dialog to capture API credentials from the user."""

    def __init__(
        self,
        parent: QWidget | None = None,
        acoustid_key: str = "",
        musicbrainz_ua: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar APIs")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._acoustid_edit = QLineEdit(self)
        self._acoustid_edit.setPlaceholderText("Clave de API de AcoustID")
        self._acoustid_edit.setText(acoustid_key)
        form.addRow("AcoustID API key", self._acoustid_edit)

        self._musicbrainz_edit = QLineEdit(self)
        self._musicbrainz_edit.setPlaceholderText(
            f"SongSearchOrganizer/{__version__} (tu_email@ejemplo.com)"
        )
        self._musicbrainz_edit.setText(musicbrainz_ua)
        form.addRow("Cuenta MusicBrainz", self._musicbrainz_edit)

        layout.addLayout(form)

        hint = QLabel(
            "Introduce tu clave de AcoustID y el identificador de cuenta/contacto de MusicBrainz.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        acoustid = self._acoustid_edit.text().strip()
        musicbrainz = self._musicbrainz_edit.text().strip()
        if not acoustid or not musicbrainz:
            QMessageBox.warning(
                self,
                "Faltan datos",
                "Debes introducir tanto la clave de AcoustID como tu cuenta/contacto de MusicBrainz.",
            )
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self._acoustid_edit.text().strip(), self._musicbrainz_edit.text().strip()


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
        self._env_path = self._data_dir / ".env"
        self._load_env_files()
        self._api_key: str = ""
        self._musicbrainz_ua: str = ""
        self._dependency_state: dict[str, bool] = {}
        self._can_enrich_metadata = False
        self._can_generate_spectrum = False
        self._enrich_disabled_reason: str | None = None
        self._spectrum_disabled_reason: str | None = None
        self._dependency_warning_shown = False
        self._startup_handled = False
        self._load_api_credentials()
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
        self._btn_config: QPushButton | None = None
        self._scan_worker: _ScanWorker | None = None
        self._summary_badge: QLabel | None = None
        self._help_button: QPushButton | None = None
        self._table_caption: QLabel | None = None
        self._inspector_caption: QLabel | None = None
        self._shortcuts: list[QShortcut] = []

        self._build_ui()
        self._setup_shortcuts()
        self._refresh_dependency_state()
        self.refresh_results()
        QTimer.singleShot(0, self._handle_startup_prompts)

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    def _load_env_files(self) -> None:
        repo_env = find_dotenv(usecwd=True)
        if repo_env:
            load_dotenv(repo_env, override=False)
        if self._env_path.exists():
            load_dotenv(self._env_path, override=False)

    def _load_api_credentials(self) -> None:
        stored = dotenv_values(self._env_path) if self._env_path.exists() else {}
        self._api_key = (os.getenv("ACOUSTID_API_KEY") or stored.get("ACOUSTID_API_KEY", "")).strip()
        self._musicbrainz_ua = (
            os.getenv("MUSICBRAINZ_USER_AGENT")
            or stored.get("MUSICBRAINZ_USER_AGENT", "")
            or ""
        ).strip()

    def _handle_startup_prompts(self) -> None:
        if self._startup_handled:
            return
        self._startup_handled = True
        self._refresh_dependency_state()
        self._maybe_prompt_api_credentials()
        self._maybe_warn_dependencies(force_dialog=True)

    def _maybe_prompt_api_credentials(self, *, force: bool = False) -> None:
        self._load_api_credentials()
        if not force and self._api_key and self._musicbrainz_ua:
            return

        dialog = ApiCredentialsDialog(self, self._api_key, self._musicbrainz_ua)
        if dialog.exec() == QDialog.Accepted:
            api_key, musicbrainz = dialog.values()
            self._save_api_credentials(api_key, musicbrainz)
            if self._status:
                self._status.showMessage("Credenciales guardadas", 5000)
        else:
            if self._status:
                self._status.showMessage(
                    "Configura las APIs para habilitar el enriquecimiento de metadatos.",
                    8000,
                )
        self._refresh_dependency_state()
        self._maybe_warn_dependencies()

    def _save_api_credentials(self, api_key: str, musicbrainz: str) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            set_key(str(self._env_path), "ACOUSTID_API_KEY", api_key, quote_mode="never")
            set_key(
                str(self._env_path),
                "MUSICBRAINZ_USER_AGENT",
                musicbrainz,
                quote_mode="never",
            )
        except Exception as exc:  # noqa: BLE001 - mostrar el error al usuario
            logger.exception("No se pudieron guardar las credenciales: %s", exc)
            QMessageBox.critical(
                self,
                "Error al guardar",
                "No se pudieron guardar las credenciales en el archivo .env.\n"
                f"Detalle: {exc}",
            )
            return

        os.environ["ACOUSTID_API_KEY"] = api_key
        os.environ["MUSICBRAINZ_USER_AGENT"] = musicbrainz
        self._api_key = api_key
        self._musicbrainz_ua = musicbrainz

    def _refresh_dependency_state(self) -> None:
        self._load_api_credentials()
        ffmpeg_available = shutil.which("ffmpeg") is not None
        fpcalc_available = shutil.which("fpcalc") is not None
        self._dependency_state = {"ffmpeg": ffmpeg_available, "fpcalc": fpcalc_available}

        if ffmpeg_available:
            self._can_generate_spectrum = True
            self._spectrum_disabled_reason = None
        else:
            self._can_generate_spectrum = False
            self._spectrum_disabled_reason = self._dependency_hint("ffmpeg")

        enrich_reasons: list[str] = []
        if not self._api_key or not self._musicbrainz_ua:
            missing_fields = []
            if not self._api_key:
                missing_fields.append("ACOUSTID_API_KEY")
            if not self._musicbrainz_ua:
                missing_fields.append("MUSICBRAINZ_USER_AGENT")
            hint = "Configura tus credenciales de AcoustID/MusicBrainz desde «Configurar APIs…»."
            if missing_fields:
                hint += "\nFaltan: " + ", ".join(missing_fields) + "."
            enrich_reasons.append(hint)
        if not fpcalc_available:
            enrich_reasons.append(self._dependency_hint("fpcalc"))
        self._can_enrich_metadata = not enrich_reasons
        self._enrich_disabled_reason = "\n\n".join(enrich_reasons) if enrich_reasons else None

        self._details.update_capabilities(
            can_enrich=self._can_enrich_metadata,
            can_generate_spectrum=self._can_generate_spectrum,
            enrich_reason=self._enrich_disabled_reason,
            spectrum_reason=self._spectrum_disabled_reason,
        )
        self._update_action_state()

    def _dependency_hint(self, tool: str) -> str:
        if tool == "ffmpeg":
            hint = "ffmpeg no se encontró en tu PATH."
            if _is_macos():
                hint += "\nInstálalo con: brew install ffmpeg"
            elif _is_windows():
                hint += "\nDescárgalo desde https://ffmpeg.org/download.html y añade la carpeta bin al PATH."
            else:
                hint += "\nInstálalo con tu gestor de paquetes, por ejemplo: sudo apt install ffmpeg"
            return hint
        if tool == "fpcalc":
            hint = "Chromaprint (fpcalc) no se encontró en tu PATH."
            if _is_macos():
                hint += "\nInstálalo con: brew install chromaprint"
            elif _is_windows():
                hint += "\nDescárgalo desde https://acoustid.org/chromaprint e incluye la carpeta bin en tu PATH."
            else:
                hint += "\nInstálalo con tu gestor de paquetes, por ejemplo: sudo apt install chromaprint"
            return hint
        return f"{tool} no está disponible en tu PATH."

    def _maybe_warn_dependencies(self, *, force_dialog: bool = False) -> None:
        missing_messages: list[str] = []
        missing_labels: list[str] = []
        if not self._dependency_state.get("ffmpeg", False):
            missing_messages.append(self._dependency_hint("ffmpeg"))
            missing_labels.append("ffmpeg")
        if not self._dependency_state.get("fpcalc", False):
            missing_messages.append(self._dependency_hint("fpcalc"))
            missing_labels.append("Chromaprint (fpcalc)")
        if not (self._api_key and self._musicbrainz_ua):
            missing_messages.append(
                "Configura las claves de AcoustID/MusicBrainz desde «Configurar APIs…» para habilitar el enriquecimiento."
            )
            missing_labels.append("credenciales de AcoustID/MusicBrainz")

        if not missing_messages:
            self._dependency_warning_shown = False
            return

        if force_dialog or not self._dependency_warning_shown:
            QMessageBox.warning(
                self,
                "Dependencias pendientes",
                "Se detectaron requisitos sin configurar:\n\n" + "\n\n".join(missing_messages),
            )
        if self._status:
            self._status.showMessage(
                "Pendiente: " + ", ".join(missing_labels),
                10000,
            )
        self._dependency_warning_shown = True

    def _open_api_settings(self) -> None:
        self._maybe_prompt_api_credentials(force=True)

    def _setup_shortcuts(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setParent(None)
        self._shortcuts.clear()

        combos: list[tuple[QKeySequence, Callable[[], None]]] = [
            (QKeySequence.Find, self._focus_search),
            (QKeySequence.Refresh, self.refresh_results),
        ]
        for sequence, handler in combos:
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.ShortcutFocusReason)
        self._search.selectAll()

    def _open_help_center(self) -> None:  # pragma: no cover - UI dialog
        self._refresh_dependency_state()

        tips = """
        <ul>
            <li><b>⌘F / Ctrl+F</b> enfoca la búsqueda instantáneamente.</li>
            <li><b>Enter</b> ejecuta la consulta actual.</li>
            <li><b>Doble clic</b> abre la pista seleccionada con tu reproductor predeterminado.</li>
            <li><b>Clic derecho</b> muestra acciones rápidas sobre la fila.</li>
        </ul>
        """.strip()

        dependency_lines: list[str] = []
        ffmpeg_ok = self._dependency_state.get("ffmpeg", False)
        fpcalc_ok = self._dependency_state.get("fpcalc", False)
        ffmpeg_text = "✅ listo" if ffmpeg_ok else self._dependency_hint("ffmpeg").replace("\n", "<br/>")
        dependency_lines.append(f"<li><b>ffmpeg</b>: {ffmpeg_text}</li>")
        fpcalc_text = "✅ listo" if fpcalc_ok else self._dependency_hint("fpcalc").replace("\n", "<br/>")
        dependency_lines.append(f"<li><b>Chromaprint (fpcalc)</b>: {fpcalc_text}</li>")
        if self._api_key and self._musicbrainz_ua:
            dependency_lines.append("<li><b>APIs</b>: ✅ credenciales configuradas.</li>")
        else:
            dependency_lines.append(
                "<li><b>APIs</b>: Configura tu clave de AcoustID y el identificador de MusicBrainz desde «Configurar APIs…».</li>"
            )

        dependencies = "<ul>" + "".join(dependency_lines) + "</ul>"
        message = """
            <p style="font-size: 15px;">
                SongSearch Organizer reúne tus herramientas en una sola vista con estética macOS.
            </p>
            <p><b>Atajos esenciales</b></p>
            {tips}
            <p><b>Estado actual</b></p>
            {deps}
            <p>
                Necesitas más ayuda? Revisa el README o pulsa «Configurar APIs…» para verificar tus credenciales.
            </p>
        """.format(tips=tips, deps=dependencies)

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Centro de ayuda")
        dialog.setIcon(QMessageBox.Information)
        dialog.setTextFormat(Qt.RichText)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.Close)
        dialog.exec()

    def _update_summary_badge(self, *, shown: int, total: int, truncated: bool) -> None:
        if self._summary_badge is None:
            return
        if total <= 0:
            self._summary_badge.setText("Sin resultados")
            self._summary_badge.setToolTip("Escanea tu biblioteca o escribe en la búsqueda para empezar.")
            return
        if shown == total and not truncated:
            self._summary_badge.setText(f"{total} pistas")
        else:
            self._summary_badge.setText(f"{shown} / {total} pistas")
        if truncated:
            self._summary_badge.setToolTip(f"Mostrando los primeros {shown} resultados de {total} disponibles.")
        else:
            self._summary_badge.setToolTip("")

    def _update_table_caption(
        self,
        *,
        query_text: str,
        shown: int,
        total: int,
        truncated: bool,
        elapsed_ms: float,
    ) -> None:
        if self._table_caption is None:
            return
        if total == 0:
            if query_text:
                self._table_caption.setText("Sin coincidencias para tu búsqueda")
            else:
                self._table_caption.setText("Escanea una carpeta para poblar la biblioteca")
            self._table_caption.setToolTip("")
            return
        base = f"{shown} pistas" if shown == total else f"{shown}/{total} pistas"
        if truncated:
            base += " · vista limitada"
        self._table_caption.setText(f"{base} · {elapsed_ms:.0f} ms")
        if query_text:
            self._table_caption.setToolTip(f"Filtro activo: {query_text}")
        else:
            self._table_caption.setToolTip("")

    def _update_inspector_caption(self, record: Mapping[str, Any] | None) -> None:
        if self._inspector_caption is None:
            return
        if not record:
            self._inspector_caption.setText("Selecciona una pista para ver sus metadatos")
            self._inspector_caption.setToolTip("")
            return
        title = str(record.get("title") or "")
        path_value = record.get("path")
        if not title:
            if isinstance(path_value, str):
                title = Path(path_value).stem
        artist = record.get("artist")
        subtitle = title if title else "Pista seleccionada"
        if artist:
            subtitle = f"{subtitle} — {artist}"
        self._inspector_caption.setText(subtitle)
        self._inspector_caption.setToolTip(subtitle)

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
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(32, 32, 32, 24)
        header_layout.setSpacing(20)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(16)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)

        title_label = QLabel("SongSearch Organizer", header)
        title_label.setObjectName("HeaderTitle")
        title_block.addWidget(title_label)

        subtitle_label = QLabel("Colección musical con inspiración macOS", header)
        subtitle_label.setObjectName("HeaderSubtitle")
        subtitle_label.setWordWrap(True)
        title_block.addWidget(subtitle_label)

        title_row.addLayout(title_block)
        title_row.addStretch(1)

        self._summary_badge = QLabel("Sin resultados", header)
        self._summary_badge.setObjectName("SummaryBadge")
        title_row.addWidget(self._summary_badge, 0, Qt.AlignVCenter)

        self._help_button = QPushButton(_load_icon("help.png"), "Centro de ayuda", header)
        self._help_button.setObjectName("HelpButton")
        self._help_button.setProperty("helpButton", True)
        self._help_button.clicked.connect(self._open_help_center)
        title_row.addWidget(self._help_button, 0, Qt.AlignVCenter)

        header_layout.addLayout(title_row)

        toolbar_frame = QFrame(header)
        toolbar_frame.setObjectName("ToolbarCard")
        ensure_styled_background(toolbar_frame)
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(20, 16, 20, 16)
        toolbar_layout.setSpacing(18)

        search_container = QWidget(toolbar_frame)
        search_container.setObjectName("SearchContainer")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(12, 0, 12, 0)
        search_layout.setSpacing(12)

        self._search.setPlaceholderText("Buscar título, artista, álbum, género o ruta…")
        self._search.setClearButtonEnabled(True)
        self._search.setObjectName("SearchField")
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.returnPressed.connect(self.refresh_results)
        search_layout.addWidget(self._search, 1)

        search_hint = QLabel("⌘F / Ctrl+F", search_container)
        search_hint.setObjectName("SearchHint")
        search_layout.addWidget(search_hint, 0, Qt.AlignVCenter)

        toolbar_layout.addWidget(search_container, 1)

        actions_container = QWidget(toolbar_frame)
        actions_container.setObjectName("HeaderActions")
        actions_layout = QHBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)

        self._btn_config = QPushButton(_load_icon("settings.png"), "Configurar APIs…", actions_container)
        self._btn_config.setProperty("toolbarButton", True)
        self._btn_config.clicked.connect(self._open_api_settings)
        actions_layout.addWidget(self._btn_config)

        self._btn_scan = QPushButton(_load_icon("scan.png"), "Escanear…", actions_container)
        self._btn_scan.setProperty("toolbarButton", True)
        self._btn_scan.clicked.connect(self._open_scan_dialog)
        actions_layout.addWidget(self._btn_scan)

        self._btn_enrich = QPushButton(_load_icon("enrich.png"), "Enriquecer", actions_container)
        self._btn_enrich.setProperty("toolbarButton", True)
        self._btn_enrich.clicked.connect(self._enrich_selected)
        self._btn_enrich.setEnabled(False)
        actions_layout.addWidget(self._btn_enrich)

        self._btn_spectrum = QPushButton(_load_icon("spectrum.png"), "Espectro", actions_container)
        self._btn_spectrum.setProperty("toolbarButton", True)
        self._btn_spectrum.clicked.connect(self._generate_spectrum_selected)
        self._btn_spectrum.setEnabled(False)
        actions_layout.addWidget(self._btn_spectrum)

        toolbar_layout.addWidget(actions_container, 0)

        for button in (self._btn_config, self._btn_scan, self._btn_enrich, self._btn_spectrum, self._help_button):
            if button is not None:
                button.setCursor(Qt.PointingHandCursor)

        header_layout.addWidget(toolbar_frame)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        splitter.setOpaqueResize(False)

        table_card = QFrame(splitter)
        table_card.setObjectName("TableCard")
        ensure_styled_background(table_card)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(20, 20, 20, 20)
        table_layout.setSpacing(12)

        table_header = QVBoxLayout()
        table_header.setContentsMargins(0, 0, 0, 0)
        table_header.setSpacing(2)
        table_title = QLabel("Biblioteca", table_card)
        table_title.setObjectName("CardTitle")
        table_header.addWidget(table_title)

        self._table_caption = QLabel("Escanea una carpeta para poblar la biblioteca", table_card)
        self._table_caption.setObjectName("CardSubtitle")
        self._table_caption.setWordWrap(True)
        table_header.addWidget(self._table_caption)

        table_layout.addLayout(table_header)

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
        details_layout.setContentsMargins(20, 20, 20, 20)
        details_layout.setSpacing(12)

        inspector_header = QVBoxLayout()
        inspector_header.setContentsMargins(0, 0, 0, 0)
        inspector_header.setSpacing(2)
        inspector_title = QLabel("Inspector", details_card)
        inspector_title.setObjectName("CardTitle")
        inspector_header.addWidget(inspector_title)

        self._inspector_caption = QLabel("Selecciona una pista para ver sus metadatos", details_card)
        self._inspector_caption.setObjectName("CardSubtitle")
        self._inspector_caption.setWordWrap(True)
        inspector_header.addWidget(self._inspector_caption)

        details_layout.addLayout(inspector_header)
        details_layout.addWidget(self._details, 1)

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

        self._update_summary_badge(shown=0, total=0, truncated=False)
        self._update_table_caption(
            query_text="",
            shown=0,
            total=0,
            truncated=False,
            elapsed_ms=0.0,
        )
        self._update_inspector_caption(None)

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
        action_spectrum.setEnabled(self._can_generate_spectrum)
        if not self._can_generate_spectrum and self._spectrum_disabled_reason:
            action_spectrum.setStatusTip(self._spectrum_disabled_reason)
        menu.addAction(action_spectrum)

        action_enrich = QAction(_load_icon("enrich.png"), "Enriquecer", menu)
        action_enrich.triggered.connect(self._enrich_selected)
        action_enrich.setEnabled(self._can_enrich_metadata)
        if not self._can_enrich_metadata and self._enrich_disabled_reason:
            action_enrich.setStatusTip(self._enrich_disabled_reason)
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
            self._update_inspector_caption(None)
            self._update_action_state()
            return
        index = selected.indexes()[0]
        data = self._model.row_data(index.row())
        if not data:
            self._current_path = None
            self._details.clear_details()
            self._update_inspector_caption(None)
            self._update_action_state()
            return
        path = data.get("path")
        self._current_path = path if isinstance(path, str) else None
        if self._current_path:
            self._details.show_for_path(self._current_path, record=data)
            self._update_inspector_caption(data)
        else:
            self._details.clear_details()
            self._update_inspector_caption(None)
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
        self._update_summary_badge(shown=shown, total=total, truncated=truncated)
        self._update_table_caption(
            query_text=query_text,
            shown=shown,
            total=total,
            truncated=truncated,
            elapsed_ms=elapsed_ms,
        )

        if shown == 0:
            self._details.clear_details()
            self._current_path = None
            self._update_inspector_caption(None)
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
            enable_enrich = has_selection and self._can_enrich_metadata
            self._btn_enrich.setEnabled(enable_enrich)
            if enable_enrich:
                self._btn_enrich.setToolTip("")
            else:
                hint = self._enrich_disabled_reason or "Configura las APIs para habilitar el enriquecimiento."
                self._btn_enrich.setToolTip(hint)
        if self._btn_spectrum is not None:
            enable_spectrum = has_selection and self._can_generate_spectrum
            self._btn_spectrum.setEnabled(enable_spectrum)
            if enable_spectrum:
                self._btn_spectrum.setToolTip("")
            else:
                hint = self._spectrum_disabled_reason or "Instala ffmpeg para generar espectros."
                self._btn_spectrum.setToolTip(hint)

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
