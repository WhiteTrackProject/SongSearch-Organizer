from __future__ import annotations

import html
import importlib
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, find_dotenv, load_dotenv, set_key
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
    QMenuBar,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSplitter,
    QStatusBar,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

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


class _HelpWorker(QThread):
    """Execute help-center requests without blocking the UI thread."""

    result_ready = Signal(str, str)
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        func: Callable[..., Any],
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        task: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._func = func
        self._args = tuple(args or ())
        self._kwargs = dict(kwargs or {})
        self._task = task

    def run(self) -> None:  # pragma: no cover - background thread
        try:
            result = self._invoke()
        except Exception as exc:  # noqa: BLE001 - bubble up to UI thread
            logger.exception("Help request failed: %s", exc)
            message = str(exc) or "No se pudo completar la consulta."
            self.failed.emit(self._task, message)
        else:
            self.result_ready.emit(self._task, str(result))

    def _invoke(self) -> Any:
        try:
            return self._func(*self._args, **self._kwargs)
        except TypeError as exc:  # pragma: no cover - defensive retry
            if not self._kwargs:
                raise
            logger.debug("Retrying help callable without keyword args: %s", exc)
            return self._func(*self._args)


class _HelpCenterDialog(QDialog):  # pragma: no cover - UI container
    """Modal dialog that displays the intelligent help center."""

    request_chat = Signal(str)
    request_ui_improvements = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        overview_html: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Centro de ayuda")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self._overview = QLabel(self)
        self._overview.setObjectName("HelpOverviewLabel")
        self._overview.setWordWrap(True)
        self._overview.setTextFormat(Qt.RichText)
        self._overview.setText(overview_html)
        layout.addWidget(self._overview)

        self._history = QTextBrowser(self)
        self._history.setObjectName("HelpHistory")
        self._history.setOpenExternalLinks(True)
        self._history.setMinimumHeight(240)
        layout.addWidget(self._history, 1)

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(12)
        self._prompt = QLineEdit(self)
        self._prompt.setPlaceholderText("Describe tu duda o el contexto que quieres mejorar…")
        input_layout.addWidget(self._prompt, 1)

        self._ask_button = QPushButton("Preguntar", self)
        self._ask_button.setDefault(True)
        input_layout.addWidget(self._ask_button)
        layout.addLayout(input_layout)

        self._suggest_button = QPushButton("Sugerir mejoras de la UI", self)
        layout.addWidget(self._suggest_button, 0, Qt.AlignRight)

        self._feedback_label = QLabel("", self)
        self._feedback_label.setObjectName("HelpFeedbackLabel")
        self._feedback_label.setWordWrap(True)
        self._feedback_label.setVisible(False)
        layout.addWidget(self._feedback_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._interactive_widgets = [self._prompt, self._ask_button, self._suggest_button]

        self._ask_button.clicked.connect(self._emit_chat_request)
        self._prompt.returnPressed.connect(self._emit_chat_request)
        self._suggest_button.clicked.connect(self._emit_ui_request)

    def set_overview_html(self, overview_html: str) -> None:
        self._overview.setText(overview_html)

    def focus_prompt(self) -> None:
        self._prompt.setFocus(Qt.ActiveWindowFocusReason)

    def set_loading(self, active: bool) -> None:
        for widget in self._interactive_widgets:
            widget.setEnabled(not active)

    def show_feedback(self, text: str, *, error: bool = False) -> None:
        self._feedback_label.setVisible(bool(text))
        self._feedback_label.setText(text)
        if error:
            self._feedback_label.setStyleSheet("color: #d14343; font-weight: 600;")
        else:
            self._feedback_label.setStyleSheet("color: #5f6c7b;")

    def update_history(self, history: Sequence[Mapping[str, Any]]) -> None:
        if not history:
            self._history.setHtml(
                "<p><i>Inicia una conversación con la ayuda inteligente para resolver "
                "dudas sobre la aplicación.</i></p>"
            )
            return

        blocks: list[str] = []
        for entry in history:
            role = str(entry.get("role", "assistant"))
            content = str(entry.get("content", ""))
            mode = str(entry.get("mode", "chat")) or "chat"
            if role == "user":
                label = "Tú"
            elif role == "assistant":
                label = "Asistente" if mode == "chat" else "Asistente (UI)"
            else:
                label = "Sistema"
            safe = html.escape(content).replace("\n", "<br/>")
            blocks.append(
                "<div class='help-entry' style='margin-bottom: 12px;'>"
                f"<p style='margin:0; font-weight:600;'>{label}</p>"
                f"<div style='margin-top:4px;'>{safe}</div>"
                "</div>"
            )
        self._history.setHtml("".join(blocks))
        scrollbar = self._history.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def _emit_chat_request(self) -> None:
        if not self._ask_button.isEnabled():
            return
        prompt = self._prompt.text().strip()
        if not prompt:
            self.show_feedback("Escribe una pregunta antes de enviar.", error=True)
            return
        self.show_feedback("")
        self._prompt.clear()
        self.request_chat.emit(prompt)

    def _emit_ui_request(self) -> None:
        if not self._suggest_button.isEnabled():
            return
        prompt = self._prompt.text().strip()
        if not prompt:
            self.show_feedback(
                "Describe el área de la interfaz para generar sugerencias.",
                error=True,
            )
            return
        self.show_feedback("")
        self._prompt.clear()
        self.request_ui_improvements.emit(prompt)


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
                (
                    "Debes introducir tanto la clave de AcoustID "
                    "como tu cuenta/contacto de MusicBrainz."
                ),
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
        self._help_dialog: _HelpCenterDialog | None = None
        self._help_worker: _HelpWorker | None = None
        self._help_history: list[dict[str, str]] = []
        self._help_callables: dict[str, Callable[..., Any]] = {}
        self._active_help_mode: str | None = None
        self._table_caption: QLabel | None = None
        self._inspector_caption: QLabel | None = None
        self._shortcuts: list[QShortcut] = []
        self._action_configure_api: QAction | None = None
        self._action_scan: QAction | None = None
        self._action_open_track: QAction | None = None
        self._action_reveal_track: QAction | None = None
        self._action_copy_paths: QAction | None = None
        self._action_exit: QAction | None = None
        self._action_refresh: QAction | None = None
        self._action_focus_search: QAction | None = None
        self._action_clear_search: QAction | None = None
        self._action_select_all: QAction | None = None
        self._action_enrich: QAction | None = None
        self._action_spectrum: QAction | None = None
        self._action_help_overview: QAction | None = None
        self._action_about: QAction | None = None
        self._action_enrich_default_tip = (
            "Enriquecer metadatos mediante AcoustID y MusicBrainz para la pista seleccionada."
        )
        self._action_spectrum_default_tip = "Generar el espectro de la pista seleccionada."
        # fmt: off
        self._action_copy_default_tip = (
            "Copiar al portapapeles la ruta de las pistas seleccionadas."
        )
        # fmt: on

        self._build_ui()
        self._create_actions()
        self._build_menus()
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
        self._api_key = (
            os.getenv("ACOUSTID_API_KEY") or stored.get("ACOUSTID_API_KEY", "")
        ).strip()
        self._musicbrainz_ua = (
            os.getenv("MUSICBRAINZ_USER_AGENT") or stored.get("MUSICBRAINZ_USER_AGENT", "") or ""
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
                f"No se pudieron guardar las credenciales en el archivo .env.\nDetalle: {exc}",
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
                hint += (
                    "\nDescárgalo desde https://ffmpeg.org/download.html "
                    "y añade la carpeta bin al PATH."
                )
            else:
                hint += (
                    "\nInstálalo con tu gestor de paquetes, por ejemplo: sudo apt install ffmpeg"
                )
            return hint
        if tool == "fpcalc":
            hint = "Chromaprint (fpcalc) no se encontró en tu PATH."
            if _is_macos():
                hint += "\nInstálalo con: brew install chromaprint"
            elif _is_windows():
                hint += (
                    "\nDescárgalo desde https://acoustid.org/chromaprint "
                    "e incluye la carpeta bin en tu PATH."
                )
            else:
                hint += (
                    "\nInstálalo con tu gestor de paquetes, por ejemplo: "
                    "sudo apt install chromaprint"
                )
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
                "Configura las claves de AcoustID/MusicBrainz "
                "desde «Configurar APIs…» para habilitar el enriquecimiento."
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

        combos: list[tuple[QKeySequence, Callable[[], None]]] = []
        if self._action_focus_search is None:
            combos.append((QKeySequence.Find, self._focus_search))
        if self._action_refresh is None:
            combos.append((QKeySequence.Refresh, self.refresh_results))
        for sequence, handler in combos:
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.ShortcutFocusReason)
        self._search.selectAll()

    def _clear_search(self) -> None:
        if not self._search.text():
            return
        self._search_timer.stop()
        self._search.clear()
        self.refresh_results()
        self._focus_search()
        self._update_action_state()

    def _select_all_rows(self) -> None:
        self._table.setFocus(Qt.ShortcutFocusReason)
        self._table.selectAll()

    def _build_help_overview_html(self) -> str:
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
        # fmt: off
        ffmpeg_text = (
            "✅ listo"
            if ffmpeg_ok
            else self._dependency_hint("ffmpeg").replace("\n", "<br/>")
        )
        dependency_lines.append(f"<li><b>ffmpeg</b>: {ffmpeg_text}</li>")
        fpcalc_text = (
            "✅ listo"
            if fpcalc_ok
            else self._dependency_hint("fpcalc").replace("\n", "<br/>")
        )
        # fmt: on
        dependency_lines.append(f"<li><b>Chromaprint (fpcalc)</b>: {fpcalc_text}</li>")
        if self._api_key and self._musicbrainz_ua:
            dependency_lines.append("<li><b>APIs</b>: ✅ credenciales configuradas.</li>")
        else:
            dependency_lines.append(
                "<li><b>APIs</b>: Configura tu clave de AcoustID y el identificador "
                "de MusicBrainz desde «Configurar APIs…».</li>"
            )

        dependencies = "<ul>" + "".join(dependency_lines) + "</ul>"
        return (
            "<p style=\"font-size: 15px;\">"
            "SongSearch Organizer reúne tus herramientas en una sola vista con estética macOS."
            "</p>"
            "<p><b>Atajos esenciales</b></p>"
            f"{tips}"
            "<p><b>Estado actual</b></p>"
            f"{dependencies}"
            "<p>"
            "Escribe tu pregunta y pulsa «Preguntar» para consultar al asistente inteligente "
            "o pide «Sugerir mejoras de la UI» para recibir ideas de refinamiento visual."
            "</p>"
        )

    def _open_help_center(self) -> None:  # pragma: no cover - UI dialog
        self._refresh_dependency_state()
        overview = self._build_help_overview_html()

        dialog = _HelpCenterDialog(self, overview_html=overview)
        dialog.request_chat.connect(self._on_help_chat_requested)
        dialog.request_ui_improvements.connect(self._on_help_ui_improvements_requested)
        dialog.finished.connect(self._on_help_dialog_finished)

        self._help_dialog = dialog
        dialog.update_history(self._help_history)
        if self._help_worker is not None:
            busy_mode = self._active_help_mode or "chat"
            busy_text = (
                "Consultando al asistente…"
                if busy_mode == "chat"
                else "Generando sugerencias de interfaz…"
            )
            dialog.show_feedback(busy_text, error=False)
            dialog.set_loading(True)
        else:
            dialog.show_feedback("")
            dialog.set_loading(False)
        dialog.focus_prompt()
        dialog.exec()

    def _show_about_dialog(self) -> None:  # pragma: no cover - UI dialog
        message = (
            "<p><b>SongSearch Organizer</b></p>"
            f"<p>Versión {__version__}</p>"
            "<p>Gestiona, busca y enriquece tu biblioteca musical con AcoustID y MusicBrainz.</p>"
        )
        QMessageBox.about(self, "Acerca de SongSearch Organizer", message)

    # ------------------------------------------------------------------
    # Help center helpers
    # ------------------------------------------------------------------
    def _on_help_chat_requested(self, prompt: str) -> None:
        clean = prompt.strip()
        if not clean:
            return
        self._append_help_message("user", clean, mode="chat")
        self._start_help_request(mode="chat", prompt=clean)

    def _on_help_ui_improvements_requested(self, prompt: str) -> None:
        clean = prompt.strip()
        if not clean:
            return
        self._append_help_message("user", clean, mode="ui")
        self._start_help_request(mode="ui", prompt=clean)

    def _append_help_message(self, role: str, content: str, *, mode: str) -> None:
        entry = {"role": role, "content": content, "mode": mode}
        self._help_history.append(entry)
        if self._help_dialog is not None:
            self._help_dialog.update_history(self._help_history)

    def _resolve_help_callable(self, name: str) -> Callable[..., Any]:
        cached = self._help_callables.get(name)
        if cached is not None:
            return cached

        candidates = (
            "songsearch.core.help_center",
            "songsearch.core.help",
            "songsearch.core.assistant",
        )
        searched_modules: list[str] = []
        last_error: Exception | None = None
        for module_name in candidates:
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                continue
            except Exception as exc:  # pragma: no cover - defensive logging
                last_error = exc
                continue
            searched_modules.append(module_name)
            func = getattr(module, name, None)
            if callable(func):
                self._help_callables[name] = func
                return func

        if last_error is not None:
            raise RuntimeError(
                f"No se pudo inicializar la ayuda inteligente: {last_error}"
            ) from last_error
        if searched_modules:
            joined = ", ".join(searched_modules)
            raise RuntimeError(
                f"La ayuda inteligente no está disponible. No se encontró '{name}' en: {joined}."
            )
        raise RuntimeError(
            "La ayuda inteligente no está disponible. Añade el módulo "
            "'songsearch.core.help_center' con las funciones necesarias."
        )

    def _start_help_request(self, *, mode: str, prompt: str) -> None:
        if self._help_worker is not None:
            if self._help_dialog is not None:
                self._help_dialog.show_feedback(
                    "Ya hay una consulta en curso. Espera a que finalice para enviar otra.",
                    error=True,
                )
            return

        func_name = "ask_chat" if mode == "chat" else "suggest_ui_improvements"
        try:
            func = self._resolve_help_callable(func_name)
        except Exception as exc:
            message = str(exc) or "La ayuda inteligente no está disponible."
            self._append_help_message("system", message, mode=mode)
            if self._help_dialog is not None:
                self._help_dialog.show_feedback(message, error=True)
            else:
                QMessageBox.warning(self, "Ayuda inteligente", message)
            return

        history_snapshot = tuple(dict(entry) for entry in self._help_history)
        worker = _HelpWorker(
            func=func,
            args=(prompt,),
            kwargs={"history": history_snapshot},
            task=mode,
            parent=self,
        )
        worker.result_ready.connect(self._on_help_worker_result)
        worker.failed.connect(self._on_help_worker_failed)
        worker.finished.connect(self._reset_help_worker)
        worker.finished.connect(worker.deleteLater)

        self._help_worker = worker
        self._active_help_mode = mode

        if self._help_dialog is not None:
            busy_text = (
                "Consultando al asistente…"
                if mode == "chat"
                else "Generando sugerencias de interfaz…"
            )
            self._help_dialog.show_feedback(busy_text, error=False)
            self._help_dialog.set_loading(True)

        worker.start()

    def _on_help_worker_result(self, mode: str, response: str) -> None:
        self._append_help_message("assistant", response, mode=mode or "chat")
        if self._help_dialog is not None:
            self._help_dialog.set_loading(False)
            self._help_dialog.show_feedback("")

    def _on_help_worker_failed(self, mode: str, message: str) -> None:
        friendly = message or "No se pudo completar la consulta."
        self._append_help_message("system", friendly, mode=mode or "chat")
        if self._help_dialog is not None:
            self._help_dialog.set_loading(False)
            self._help_dialog.show_feedback(friendly, error=True)
        else:
            QMessageBox.critical(self, "Ayuda inteligente", friendly)

    def _reset_help_worker(self) -> None:
        self._help_worker = None
        self._active_help_mode = None

    def _on_help_dialog_finished(self, _: int) -> None:
        if self._help_dialog is not None:
            self._help_dialog.deleteLater()
        self._help_dialog = None

    def _update_summary_badge(self, *, shown: int, total: int, truncated: bool) -> None:
        if self._summary_badge is None:
            return
        if total <= 0:
            self._summary_badge.setText("Sin resultados")
            self._summary_badge.setToolTip(
                "Escanea tu biblioteca o escribe en la búsqueda para empezar."
            )
            return
        if shown == total and not truncated:
            self._summary_badge.setText(f"{total} pistas")
        else:
            self._summary_badge.setText(f"{shown} / {total} pistas")
        if truncated:
            self._summary_badge.setToolTip(
                f"Mostrando los primeros {shown} resultados de {total} disponibles."
            )
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

        self._help_button = QPushButton(
            _load_icon("help.png"),
            "Centro de ayuda",
            header,
        )
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

        self._btn_config = QPushButton(
            _load_icon("settings.png"), "Configurar APIs…", actions_container
        )
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

        for button in (
            self._btn_config,
            self._btn_scan,
            self._btn_enrich,
            self._btn_spectrum,
            self._help_button,
        ):
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
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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

        self._inspector_caption = QLabel(
            "Selecciona una pista para ver sus metadatos", details_card
        )
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

        self._build_menus()

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

    def _create_actions(self) -> None:
        self._action_configure_api = QAction(_load_icon("settings.png"), "Configurar APIs…", self)
        self._action_configure_api.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
        self._action_configure_api.setStatusTip(
            "Define las credenciales de AcoustID y MusicBrainz."
        )
        self._action_configure_api.setMenuRole(QAction.MenuRole.PreferencesRole)
        self._action_configure_api.triggered.connect(self._open_api_settings)

        self._action_scan = QAction(_load_icon("scan.png"), "Escanear…", self)
        self._action_scan.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._action_scan.setStatusTip("Explora una carpeta y añade sus pistas a la biblioteca.")
        self._action_scan.triggered.connect(self._open_scan_dialog)

        self._action_open_track = QAction(_load_icon("open.png"), "Abrir", self)
        self._action_open_track.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        self._action_open_track.setStatusTip(
            "Reproduce la pista seleccionada con la aplicación predeterminada."
        )
        self._action_open_track.triggered.connect(self._open_selected_track)

        self._action_reveal_track = QAction(_load_icon("reveal.png"), "Mostrar en carpeta", self)
        self._action_reveal_track.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self._action_reveal_track.setStatusTip(
            "Abre el explorador de archivos en la ubicación de la pista."
        )
        self._action_reveal_track.triggered.connect(self._reveal_selected_track)

        self._action_exit = QAction("Salir", self)
        self._action_exit.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        self._action_exit.setMenuRole(QAction.MenuRole.QuitRole)
        self._action_exit.triggered.connect(self.close)

        self._action_copy_paths = QAction(_load_icon("copy.png"), "Copiar ruta", self)
        self._action_copy_paths.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self._action_copy_paths.setStatusTip("Copia la ruta de la pista al portapapeles.")
        self._action_copy_paths.triggered.connect(self._copy_selected_paths)

        self._action_focus_search = QAction("Buscar", self)
        self._action_focus_search.setShortcut(QKeySequence(QKeySequence.StandardKey.Find))
        self._action_focus_search.setStatusTip("Enfoca el cuadro de búsqueda.")
        self._action_focus_search.triggered.connect(self._focus_search)

        self._action_clear_search = QAction("Limpiar búsqueda", self)
        self._action_clear_search.setShortcut(QKeySequence("Esc"))
        self._action_clear_search.setStatusTip("Limpia el texto de búsqueda actual.")
        self._action_clear_search.triggered.connect(self._clear_search)

        self._action_select_all = QAction("Seleccionar todo", self)
        self._action_select_all.setShortcut(QKeySequence(QKeySequence.StandardKey.SelectAll))
        self._action_select_all.setStatusTip("Selecciona todas las filas visibles.")
        self._action_select_all.triggered.connect(self._select_all_rows)

        self._action_refresh = QAction(_load_icon("refresh.png"), "Actualizar resultados", self)
        self._action_refresh.setShortcut(QKeySequence(QKeySequence.StandardKey.Refresh))
        self._action_refresh.setStatusTip("Vuelve a ejecutar la búsqueda actual.")
        self._action_refresh.triggered.connect(self.refresh_results)

        self._action_enrich = QAction(_load_icon("enrich.png"), "Enriquecer", self)
        self._action_enrich.setShortcut(QKeySequence("Ctrl+E"))
        self._action_enrich.setStatusTip("Busca metadatos en AcoustID y MusicBrainz.")
        self._action_enrich.triggered.connect(self._enrich_selected)

        self._action_spectrum = QAction(_load_icon("spectrum.png"), "Espectro", self)
        self._action_spectrum.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self._action_spectrum.setStatusTip("Genera el espectro de la pista seleccionada.")
        self._action_spectrum.triggered.connect(self._generate_spectrum_selected)

        self._action_help_overview = QAction(_load_icon("help.png"), "Centro de ayuda", self)
        self._action_help_overview.setShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents))
        self._action_help_overview.setStatusTip("Descubre atajos, dependencias y consejos de uso.")
        self._action_help_overview.setMenuRole(QAction.MenuRole.HelpRole)
        self._action_help_overview.triggered.connect(self._open_help_center)

        self._action_about = QAction("Acerca de SongSearch Organizer", self)
        self._action_about.setMenuRole(QAction.MenuRole.AboutRole)
        self._action_about.triggered.connect(self._show_about_dialog)

        for action in (
            self._action_configure_api,
            self._action_scan,
            self._action_open_track,
            self._action_reveal_track,
            self._action_exit,
            self._action_copy_paths,
            self._action_focus_search,
            self._action_clear_search,
            self._action_select_all,
            self._action_refresh,
            self._action_enrich,
            self._action_spectrum,
            self._action_help_overview,
            self._action_about,
        ):
            if action is not None:
                self.addAction(action)

        self._update_action_state()

    def _build_menus(self) -> None:
        menu_bar: QMenuBar = self.menuBar()
        menu_bar.clear()

        def add_group(menu: QMenu, *actions: QAction | None) -> None:
            valid_actions = [action for action in actions if action is not None]
            if not valid_actions:
                return
            if menu.actions():
                menu.addSeparator()
            for action in valid_actions:
                menu.addAction(action)

        file_menu = menu_bar.addMenu("&Archivo")
        add_group(file_menu, self._action_configure_api, self._action_scan)
        add_group(file_menu, self._action_open_track, self._action_reveal_track)
        add_group(file_menu, self._action_exit)

        edit_menu = menu_bar.addMenu("&Edición")
        add_group(edit_menu, self._action_copy_paths)
        add_group(edit_menu, self._action_focus_search, self._action_clear_search)
        add_group(edit_menu, self._action_select_all)

        tools_menu = menu_bar.addMenu("&Herramientas")
        add_group(tools_menu, self._action_refresh)
        add_group(tools_menu, self._action_enrich, self._action_spectrum)

        help_menu = menu_bar.addMenu("Ay&uda")
        for action in (self._action_help_overview, self._action_about):
            if action is not None:
                help_menu.addAction(action)

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
        if self._action_scan is not None:
            self._action_scan.setEnabled(False)
        self._status.showMessage(f"Escaneando {directory}…")
        worker.start()

    def _reset_scan_worker(self) -> None:
        if self._btn_scan is not None:
            self._btn_scan.setEnabled(True)
        if self._action_scan is not None:
            self._action_scan.setEnabled(True)
        self._scan_worker = None
        self._update_action_state()

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

        def add_group(*actions: QAction | None) -> None:
            valid_actions = [action for action in actions if action is not None]
            if not valid_actions:
                return
            if menu.actions():
                menu.addSeparator()
            for action in valid_actions:
                menu.addAction(action)

        add_group(self._action_open_track, self._action_reveal_track)
        add_group(self._action_spectrum, self._action_enrich)
        add_group(self._action_copy_paths)

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
        self._update_action_state()

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
        has_rows = self._model.rowCount() > 0 if self._model is not None else False
        search_has_text = bool(self._search.text())
        enable_enrich = has_selection and self._can_enrich_metadata
        enrich_hint = (
            self._enrich_disabled_reason or "Configura las APIs para habilitar el enriquecimiento."
        )
        enable_spectrum = has_selection and self._can_generate_spectrum
        spectrum_hint = self._spectrum_disabled_reason or "Instala ffmpeg para generar espectros."

        if self._btn_enrich is not None:
            self._btn_enrich.setEnabled(enable_enrich)
            self._btn_enrich.setToolTip("" if enable_enrich else enrich_hint)
        if self._action_enrich is not None:
            self._action_enrich.setEnabled(enable_enrich)
            self._action_enrich.setStatusTip(
                self._action_enrich_default_tip if enable_enrich else enrich_hint
            )

        if self._btn_spectrum is not None:
            self._btn_spectrum.setEnabled(enable_spectrum)
            self._btn_spectrum.setToolTip("" if enable_spectrum else spectrum_hint)
        if self._action_spectrum is not None:
            self._action_spectrum.setEnabled(enable_spectrum)
            self._action_spectrum.setStatusTip(
                self._action_spectrum_default_tip if enable_spectrum else spectrum_hint
            )

        if self._action_open_track is not None:
            self._action_open_track.setEnabled(has_selection)
        if self._action_reveal_track is not None:
            self._action_reveal_track.setEnabled(has_selection)
        if self._action_copy_paths is not None:
            self._action_copy_paths.setEnabled(has_selection)

        if self._action_clear_search is not None:
            self._action_clear_search.setEnabled(search_has_text)

        if self._action_select_all is not None:
            self._action_select_all.setEnabled(has_rows)

        if self._action_refresh is not None:
            self._action_refresh.setEnabled(self._con is not None)

        if self._action_focus_search is not None:
            self._action_focus_search.setEnabled(True)

        open_tip = "Abrir la pista seleccionada con la aplicación predeterminada del sistema."
        reveal_tip = "Abrir el explorador de archivos en la ubicación de la pista seleccionada."
        copy_disabled_tip = "Selecciona al menos una pista para copiar su ruta."

        if self._action_open_track is not None:
            self._action_open_track.setStatusTip(
                open_tip if has_selection else "Selecciona una pista para poder abrirla."
            )
        if self._action_reveal_track is not None:
            self._action_reveal_track.setStatusTip(
                reveal_tip
                if has_selection
                else "Selecciona una pista para mostrarla en la carpeta."
            )
        if self._action_copy_paths is not None:
            self._action_copy_paths.setStatusTip(
                self._action_copy_default_tip if has_selection else copy_disabled_tip
            )

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
