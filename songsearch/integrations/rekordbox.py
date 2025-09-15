"""Best effort interface to explore the Rekordbox SQLite database.

The goal of this module is to provide a **best effort** interface that works
with the Rekordbox database layouts that are commonly found on macOS, Windows
and Linux installs. The implementation intentionally focuses on read-only
operations so that the UI can present the playlists without risking writes to
an external application database. When the structure cannot be determined the
adapter simply returns empty iterables instead of raising exceptions.
"""

from __future__ import annotations

import logging
import os
import platform
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = ["RekordboxAdapter", "export_playlist_to_m3u"]

logger = logging.getLogger(__name__)


def _candidate_paths() -> list[Path]:
    """Return potential Rekordbox database locations.

    Users can override the auto-detection by defining ``REKORDBOX_DB_PATH``.
    """

    custom = os.getenv("REKORDBOX_DB_PATH")
    paths: list[Path] = []
    if custom:
        paths.append(Path(custom).expanduser())

    home = Path.home()
    system = platform.system().lower()

    # Rekordbox 5 (classic)
    if "darwin" in system:
        paths.append(home / "Library" / "Pioneer" / "rekordbox" / "mastersqlite.db")
        paths.append(
            home / "Library" / "Application Support" / "Pioneer" / "rekordbox6" / "master.db"
        )
    elif "win" in system:
        appdata = os.getenv("APPDATA")
        if appdata:
            paths.append(Path(appdata) / "Pioneer" / "rekordbox" / "mastersqlite.db")
            paths.append(Path(appdata) / "Pioneer" / "rekordbox6" / "master.db")
    else:  # Linux or other Unix flavours
        paths.append(home / ".Pioneer" / "rekordbox" / "mastersqlite.db")
        paths.append(home / ".PioneerDJ" / "rekordbox6" / "master.db")

    # Remove duplicates while preserving order
    normalized: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        expanded = path.expanduser()
        if expanded not in seen:
            normalized.append(expanded)
            seen.add(expanded)
    return normalized


def export_playlist_to_m3u(
    rows: Iterable[dict[str, Any] | sqlite3.Row], output: str | Path
) -> Path:
    """Export *rows* to the UTF-8 encoded ``output`` file as an ``.m3u8`` list."""

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for row in rows:
            if isinstance(row, sqlite3.Row):
                data = dict(row)
            elif isinstance(row, dict):
                data = row
            else:
                try:
                    data = dict(row)  # type: ignore[arg-type]
                except Exception:  # pragma: no cover - best effort
                    data = {}
            title = str(data.get("title") or data.get("Name") or "")
            artist = str(data.get("artist") or data.get("ArtistName") or "")
            path = data.get("path") or data.get("AbsolutePath") or data.get("OriginalFileName")
            if isinstance(path, Path):
                path = str(path)
            if not isinstance(path, str):
                continue
            if title or artist:
                fh.write(f"#EXTINF:-1,{artist} - {title}\n")
            fh.write(f"{path}\n")
    return output_path


class RekordboxAdapter:
    """Minimal interface to explore a Rekordbox SQLite database."""

    def __init__(self, db_path: Path, can_write: bool = False) -> None:
        self.db_path = Path(db_path)
        self.can_write = bool(can_write)

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------
    @classmethod
    def detect(cls) -> "RekordboxAdapter | None":
        """Return an adapter instance when a database is discovered."""

        for candidate in _candidate_paths():
            try:
                if candidate.is_file():
                    can_write = os.access(candidate, os.W_OK)
                    logger.debug("Detected Rekordbox DB at %s (write=%s)", candidate, can_write)
                    return cls(candidate, can_write=can_write)
            except OSError as exc:  # pragma: no cover - filesystem corner cases
                logger.debug("Error while probing %s: %s", candidate, exc)
        return None

    # ------------------------------------------------------------------
    # Read-only operations
    # ------------------------------------------------------------------
    def list_playlists(self) -> list[dict[str, Any]]:
        """Return playlists ordered by parent/child relationships."""

        try:
            with self._connect() as con:
                if not self._has_table(con, "djmdPlaylist"):
                    return []
                query = (
                    "SELECT ID, Name, ParentID, Attribute FROM djmdPlaylist "
                    "ORDER BY COALESCE(ParentID, ID), SortIndex"
                )
                try:
                    rows = con.execute(query).fetchall()
                except sqlite3.OperationalError:
                    rows = con.execute(
                        "SELECT ID, Name, ParentID, Attribute FROM djmdPlaylist ORDER BY COALESCE(ParentID, ID), ID"
                    ).fetchall()
        except sqlite3.DatabaseError as exc:  # pragma: no cover - defensive
            logger.debug("Cannot read Rekordbox playlists: %s", exc)
            return []

        playlists: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, sqlite3.Row):
                data = dict(row)
            else:
                data = {
                    "ID": row[0] if len(row) > 0 else None,
                    "Name": row[1] if len(row) > 1 else None,
                    "ParentID": row[2] if len(row) > 2 else None,
                    "Attribute": row[3] if len(row) > 3 else None,
                }
            playlists.append(
                {
                    "id": data.get("ID"),
                    "name": data.get("Name") or "(sin nombre)",
                    "parent_id": data.get("ParentID"),
                    "attribute": data.get("Attribute"),
                }
            )
        return playlists

    def list_tracks_in_playlist(self, playlist_id: int | str) -> list[dict[str, Any]]:
        """Return tracks stored in *playlist_id* ordered by ``SortIndex``."""

        try:
            playlist_int = int(playlist_id)
        except (TypeError, ValueError):
            return []

        try:
            with self._connect() as con:
                if not self._has_table(con, "djmdPlaylistTrack"):
                    return []
                base_query = (
                    "SELECT pt.TrackID, s.Title, s.ArtistName, c.FilePath, c.FileName, c.OriginalFileName "
                    "FROM djmdPlaylistTrack pt "
                    "JOIN djmdSong s ON s.ID = pt.TrackID "
                    "LEFT JOIN djmdContent c ON c.ID = s.ContentID "
                    "WHERE pt.PlaylistID = ? ORDER BY pt.SortIndex"
                )
                try:
                    rows = con.execute(base_query, (playlist_int,)).fetchall()
                except sqlite3.OperationalError:
                    alt_query = base_query.replace("pt.SortIndex", "pt.ID")
                    rows = con.execute(alt_query, (playlist_int,)).fetchall()
        except sqlite3.DatabaseError as exc:  # pragma: no cover - defensive
            logger.debug("Cannot read Rekordbox playlist %s: %s", playlist_id, exc)
            return []

        results: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, sqlite3.Row):
                data = dict(row)
            else:
                data = {
                    "TrackID": row[0] if len(row) > 0 else None,
                    "Title": row[1] if len(row) > 1 else None,
                    "ArtistName": row[2] if len(row) > 2 else None,
                    "FilePath": row[3] if len(row) > 3 else None,
                    "FileName": row[4] if len(row) > 4 else None,
                    "OriginalFileName": row[5] if len(row) > 5 else None,
                }
            path = self._compose_path(data)
            results.append(
                {
                    "id": data.get("TrackID"),
                    "title": data.get("Title") or "",
                    "artist": data.get("ArtistName") or "",
                    "path": path or "",
                }
            )
        return results

    # ------------------------------------------------------------------
    # Mutation operations (not implemented by default)
    # ------------------------------------------------------------------
    def create_playlist(
        self, name: str, parent_id: int | None = None
    ) -> None:  # pragma: no cover - optional
        raise RuntimeError(
            "La escritura de playlists de Rekordbox no está habilitada en esta build."
        )

    def delete_playlist(self, playlist_id: int | str) -> None:  # pragma: no cover - optional
        raise RuntimeError(
            "La escritura de playlists de Rekordbox no está habilitada en esta build."
        )

    def add_tracks_to_playlist(
        self, playlist_id: int | str, paths: Iterable[str]
    ) -> int:  # pragma: no cover - optional
        raise RuntimeError(
            "La escritura de playlists de Rekordbox no está habilitada en esta build."
        )

    def remove_tracks_from_playlist(
        self, playlist_id: int | str, paths: Iterable[str]
    ) -> int:  # pragma: no cover - optional
        raise RuntimeError(
            "La escritura de playlists de Rekordbox no está habilitada en esta build."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _has_table(con: sqlite3.Connection, table: str) -> bool:
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
            (table,),
        )
        return cur.fetchone() is not None

    @staticmethod
    def _compose_path(data: dict[str, Any]) -> str | None:
        file_path = data.get("FilePath")
        file_name = data.get("FileName")
        original = data.get("OriginalFileName")
        components = [file_path, file_name]
        if components[0] and components[1]:
            path = Path(str(components[0])) / str(components[1])
            return str(path)
        if original:
            return str(original)
        if file_name:
            return str(file_name)
        return None
