from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLineEdit, QTableWidget, QTableWidgetItem,
    QHBoxLayout, QPushButton, QFileDialog, QLabel, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from pathlib import Path
from ..core.db import connect, init_db, query_tracks
from ..core.scanner import scan_path
import logging

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".songsearch"
DB_PATH = init_db(DATA_DIR)


class ScanThread(QThread):
    finished = Signal()

    def __init__(self, con, path):
        super().__init__()
        self.con = con
        self.path = path

    def run(self):
        try:
            scan_path(self.con, Path(self.path))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SongSearch Organizer (v0.1)")
        self.resize(1100, 700)
        self.con = connect(DB_PATH)

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
        self.table.setHorizontalHeaderLabels(["Título","Artista","Álbum","Género","Año","Ruta"])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setEditTriggers(self.table.NoEditTriggers)

        root = QWidget(self)
        lay = QVBoxLayout(root)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.progress)
        self.setCentralWidget(root)

        self.refresh()

    def refresh(self):
        text = self.search.text().strip()
        if text:
            where = "(title LIKE ? OR artist LIKE ? OR album LIKE ? OR genre LIKE ? OR path LIKE ?)"
            params = tuple([f"%{text}%"] * 5)
        else:
            where, params = "", tuple()
        rows = query_tracks(self.con, where, params)
        self.table.setRowCount(0)
        for r in rows[:5000]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["title"] or ""))
            self.table.setItem(row, 1, QTableWidgetItem(r["artist"] or ""))
            self.table.setItem(row, 2, QTableWidgetItem(r["album"] or ""))
            self.table.setItem(row, 3, QTableWidgetItem(r["genre"] or ""))
            self.table.setItem(row, 4, QTableWidgetItem(str(r["year"] or "")))
            self.table.setItem(row, 5, QTableWidgetItem(r["path"]))

    def scan_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Selecciona carpeta de música")
        if d:
            self.progress.setVisible(True)
            self.progress.setRange(0,0)
            self.thread = ScanThread(self.con, d)
            self.thread.finished.connect(self.on_scan_finished)
            self.thread.start()

    def on_scan_finished(self):
        self.progress.setVisible(False)
        self.refresh()
        logger.info("scan completed")
