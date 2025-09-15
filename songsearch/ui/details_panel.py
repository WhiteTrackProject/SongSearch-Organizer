from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ..core.db import connect, get_by_path
from ..core.metadata_enricher import enrich_file
from ..core.spectrum import generate_spectrogram, open_external

logger = logging.getLogger(__name__)


class _WorkerThread(QThread):
    """Simple worker that executes a callable in a background thread."""

    result_ready = Signal(object)
    error = Signal(object)

    def __init__(self, fn: Callable, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:  # pragma: no cover - Qt thread integration
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Background job failed: %s", exc)
            self.error.emit(exc)
        else:
            self.result_ready.emit(result)


class DetailsPanel(QWidget):
    """Widget that shows the metadata of the currently selected track."""

    def __init__(
        self,
        con: sqlite3.Connection | None = None,
        data_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DetailsPanel")
        self._con = con
        self._current_data: dict[str, Any] | None = None
        self._data_dir = (data_dir or Path.home() / ".songsearch").expanduser()
        self._spectrogram_dir = self._data_dir / "spectra"
        self._db_path = self._resolve_db_path(con)
        self._spectrum_thread: _WorkerThread | None = None
        self._enrich_thread: _WorkerThread | None = None
        self._enrich_min_confidence = 0.6
        self._enrich_write_tags = False

        self._value_labels: dict[str, QLabel] = {}

        self._setup_ui()
        self._connect_action_signals()
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

        self.btn_enrich = QPushButton("Enriquecer")
        actions.addWidget(self.btn_enrich)

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
            value_label.setProperty("valueLabel", True)
            self._value_labels[field] = value_label
            label = QLabel(f"{text}:")
            label.setProperty("formLabel", True)
            yield field, label

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
        for button in self._iter_action_buttons():
            self._set_button_busy(button, False)
            button.setEnabled(False)

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

    # ----------------------------------------------------------------------------------
    # UI actions
    # ----------------------------------------------------------------------------------
    def _connect_action_signals(self) -> None:
        self.btn_spectrum.clicked.connect(self._make_spectrum)
        self.btn_enrich.clicked.connect(self._enrich_one)

    def _set_button_busy(
        self,
        button: QPushButton | None,
        busy: bool,
        busy_text: str | None = None,
    ) -> None:
        if button is None:
            return
        if busy:
            if button.property("_idle_text") is None:
                button.setProperty("_idle_text", button.text())
            if busy_text is not None:
                button.setText(busy_text)
            button.setEnabled(False)
        else:
            idle_text = button.property("_idle_text")
            if idle_text is not None:
                button.setText(idle_text)
            button.setProperty("_idle_text", None)
            button.setEnabled(True)

    def _current_track_path(self) -> Path | None:
        data = self._current_data
        if not data:
            return None
        path = data.get("path")
        if not path:
            return None
        return Path(path)

    def _make_spectrum(self) -> None:
        path = self._current_track_path()
        if path is None:
            QMessageBox.warning(
                self,
                "Sin pista",
                "Selecciona una pista antes de generar el espectro.",
            )
            return
        if not path.exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                f"No se encontró el archivo:\n{path}",
            )
            return
        if self._spectrum_thread is not None and self._spectrum_thread.isRunning():
            return

        self._set_button_busy(self.btn_spectrum, True, "Generando…")
        worker = _WorkerThread(generate_spectrogram, path, self._spectrogram_dir)
        worker.setParent(self)
        self._spectrum_thread = worker
        worker.result_ready.connect(self._on_spectrum_ready)
        worker.error.connect(self._on_spectrum_error)
        worker.finished.connect(lambda: self._on_worker_finished("spectrum"))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_spectrum_ready(self, result: object) -> None:
        try:
            spectrum_path = Path(result)
        except TypeError:  # pragma: no cover - defensive
            logger.warning("Unexpected spectrum path: %s", result)
            return

        if not spectrum_path.exists():
            QMessageBox.warning(
                self,
                "Espectro no disponible",
                f"El archivo no se generó correctamente:\n{spectrum_path}",
            )
            return

        QMessageBox.information(
            self,
            "Espectro generado",
            f"Espectrograma guardado en:\n{spectrum_path}",
        )
        try:
            open_external(spectrum_path)
        except Exception as exc:  # pragma: no cover - external tools
            logger.warning("Cannot open spectrogram externally: %s", exc)

    def _on_spectrum_error(self, exc: object) -> None:
        message = str(exc) if exc else "Error desconocido al generar el espectro."
        QMessageBox.critical(
            self,
            "Error al generar espectro",
            message,
        )

    def _enrich_one(self) -> None:
        if self._enrich_thread is not None and self._enrich_thread.isRunning():
            return

        path = self._current_track_path()
        if path is None:
            QMessageBox.warning(
                self,
                "Sin pista",
                "Selecciona una pista antes de enriquecer metadatos.",
            )
            return
        if not path.exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                f"No se encontró el archivo:\n{path}",
            )
            return
        if not self._db_path or str(self._db_path) in {":memory:", ""}:
            QMessageBox.critical(
                self,
                "Base de datos no disponible",
                "No es posible acceder a la base de datos para enriquecer metadatos.",
            )
            return

        self._set_button_busy(self.btn_enrich, True, "Enriqueciendo…")
        worker = _WorkerThread(self._run_enrich_job, path)
        worker.setParent(self)
        self._enrich_thread = worker
        worker.result_ready.connect(lambda updates, p=path: self._on_enrich_ready(p, updates))
        worker.error.connect(self._on_enrich_error)
        worker.finished.connect(lambda: self._on_worker_finished("enrich"))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _run_enrich_job(self, path: Path):  # pragma: no cover - heavy IO
        db_path = self._db_path
        if db_path is None:
            raise RuntimeError("No se encontró la base de datos.")
        con = connect(db_path)
        try:
            return enrich_file(
                con,
                path,
                min_confidence=self._enrich_min_confidence,
                write_tags=self._enrich_write_tags,
            )
        finally:
            con.close()

    def _on_enrich_ready(self, path: Path, updates: object) -> None:
        if updates:
            QMessageBox.information(
                self,
                "Metadatos actualizados",
                "Los metadatos se han actualizado correctamente.",
            )
            self.show_for_path(str(path))
        else:
            QMessageBox.information(
                self,
                "Sin coincidencias",
                "No se encontraron coincidencias para actualizar metadatos.",
            )

    def _on_enrich_error(self, exc: object) -> None:
        message = str(exc) if exc else "No se pudo enriquecer los metadatos."
        QMessageBox.critical(
            self,
            "Error al enriquecer",
            message,
        )

    def _on_worker_finished(self, job: str) -> None:
        if job == "spectrum":
            button = self.btn_spectrum
            self._set_button_busy(button, False)
            if button is not None:
                button.setEnabled(self._current_data is not None)
            self._spectrum_thread = None
        elif job == "enrich":
            button = self.btn_enrich
            self._set_button_busy(button, False)
            if button is not None:
                button.setEnabled(self._current_data is not None)
            self._enrich_thread = None

    def _resolve_db_path(self, con: sqlite3.Connection | None) -> Path | None:
        if con is None:
            return None
        try:
            row = con.execute("PRAGMA database_list").fetchone()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Cannot resolve database path: %s", exc)
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
