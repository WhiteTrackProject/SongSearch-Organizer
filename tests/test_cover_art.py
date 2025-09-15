from __future__ import annotations

import base64
import logging
import socket
from pathlib import Path
from hashlib import sha1
from urllib.error import URLError

import pytest

from songsearch.core import cover_art
from songsearch.core.cover_art import ensure_cover_for_path


def _make_track(tmp_path: Path, name: str = "song.mp3") -> Path:
    track_path = tmp_path / name
    track_path.parent.mkdir(parents=True, exist_ok=True)
    track_path.write_bytes(b"")
    return track_path


def test_ensure_cover_prefers_existing_local_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "cache"
    track = _make_track(tmp_path / "music")
    cover = track.with_suffix(".jpg")
    cover.write_bytes(b"cover")

    resolved = ensure_cover_for_path(data_dir, track, None)

    assert resolved == cover


def test_ensure_cover_resolves_relative_and_file_uri(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    track = _make_track(tmp_path / "library" / "album" / "track.flac")

    # Relative reference
    relative_cover = track.parent / "images" / "art.png"
    relative_cover.parent.mkdir(parents=True, exist_ok=True)
    relative_cover.write_bytes(b"img")
    resolved_relative = ensure_cover_for_path(
        data_dir, track, "images/art.png"
    )
    assert resolved_relative == relative_cover

    # File URI reference
    file_cover = tmp_path / "external" / "folder cover.jpg"
    file_cover.parent.mkdir(parents=True, exist_ok=True)
    file_cover.write_bytes(b"file cover")
    resolved_file = ensure_cover_for_path(data_dir, track, file_cover.as_uri())
    assert resolved_file == file_cover


def test_ensure_cover_downloads_and_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "cache"
    track = _make_track(tmp_path, "downloaded.ogg")

    png_data = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )

    calls: list[str] = []

    class DummyResponse:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self) -> DummyResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - protocol
            return None

    def fake_urlopen(url: str, *, timeout: float):
        assert timeout == cover_art._DOWNLOAD_TIMEOUT
        calls.append(url)
        return DummyResponse(png_data)

    monkeypatch.setattr(cover_art.request, "urlopen", fake_urlopen)

    url = "http://example.com/cover.png"
    cached_path = ensure_cover_for_path(data_dir, track, url)

    assert cached_path is not None
    assert cached_path.exists()
    assert cached_path.suffix == ".png"
    assert cached_path.parent == data_dir / "covers"
    assert cached_path.read_bytes() == png_data

    cached_again = ensure_cover_for_path(data_dir, track, url)

    assert cached_again == cached_path
    assert len(calls) == 1


def test_ensure_cover_download_failure_returns_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "cache"
    track = _make_track(tmp_path / "collection", "track.mp3")
    fallback = track.with_suffix(".png")
    fallback.write_bytes(b"fallback")

    def failing_urlopen(url: str, *, timeout: float):
        assert timeout == cover_art._DOWNLOAD_TIMEOUT
        raise URLError("boom")

    monkeypatch.setattr(cover_art.request, "urlopen", failing_urlopen)

    resolved = ensure_cover_for_path(data_dir, track, "http://example.com/missing.png")

    assert resolved == fallback


def test_download_timeout_cleans_up_partial_file(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "cache"
    track = _make_track(tmp_path / "collection", "timeout.mp3")
    fallback = track.with_suffix(".jpg")
    fallback.write_bytes(b"fallback")

    url = "http://example.com/slow-image"

    def timeout_urlopen(urlopen_url: str, *, timeout: float):
        assert timeout == cover_art._DOWNLOAD_TIMEOUT
        raise URLError(socket.timeout("timed out"))

    monkeypatch.setattr(cover_art.request, "urlopen", timeout_urlopen)

    caplog.set_level(logging.WARNING)

    resolved = ensure_cover_for_path(data_dir, track, url)

    assert resolved == fallback

    base_name = sha1(url.encode("utf-8")).hexdigest()
    temp_path = data_dir / "covers" / f"{base_name}.part"

    assert not temp_path.exists()
    assert any("Timed out downloading" in record.message for record in caplog.records)
