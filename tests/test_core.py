from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from songsearch.core.db import (
    connect,
    fts_query_from_text,
    init_db,
    query_tracks,
    upsert_track,
)
from songsearch.core.metadata_enricher import enrich_file
from songsearch.core.organizer import simulate
from songsearch.core.scanner import scan_path


def _create_wav(path: Path) -> None:
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\x00\x00" * 44100)


def test_scan_and_simulate(tmp_path: Path) -> None:
    db_path = init_db(tmp_path)
    con = connect(db_path)
    audio = tmp_path / "test.wav"
    _create_wav(audio)
    scan_path(con, tmp_path)
    rows = query_tracks(con)
    assert len(rows) == 1
    plan = simulate(con, tmp_path / "out", "{Artista}/{Título}.{ext}")
    assert len(plan) == 1


def test_query_tracks_full_text(tmp_path: Path) -> None:
    db_path = init_db(tmp_path)
    con = connect(db_path)
    library = tmp_path / "library"
    library.mkdir()
    track1 = library / "Queen - Bohemian Rhapsody.mp3"
    track2 = library / "Queen - Under Pressure.mp3"
    track3 = library / "Misc" / "demo-track.flac"
    track3.parent.mkdir(parents=True, exist_ok=True)
    for candidate in (track1, track2, track3):
        candidate.touch()

    upsert_track(
        con,
        {
            "path": str(track1),
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "genre": "Rock",
        },
    )
    upsert_track(
        con,
        {
            "path": str(track2),
            "title": "Under Pressure",
            "artist": "Queen",
            "album": "Hot Space",
            "genre": "Rock",
        },
    )
    upsert_track(
        con,
        {
            "path": str(track3),
            "title": "Episode 1",
            "artist": "Host",
            "album": "Season 1",
            "genre": "Podcast",
        },
    )

    def _search_paths(query: str) -> set[str]:
        fts = fts_query_from_text(query)
        assert fts is not None
        return {row["path"] for row in query_tracks(con, fts_query=fts)}

    assert _search_paths("rhap") == {str(track1)}
    assert _search_paths("quee") == {str(track1), str(track2)}
    assert _search_paths("oper") == {str(track1)}
    assert _search_paths("roc") == {str(track1), str(track2)}
    assert _search_paths("demo") == {str(track3)}


def test_scan_skips_files_with_same_stat(monkeypatch, tmp_path: Path) -> None:
    db_path = init_db(tmp_path)
    con = connect(db_path)
    audio = tmp_path / "track.wav"
    _create_wav(audio)
    calls: dict[str, Any] = {"count": 0}

    class _FakeInfo:
        length = 123.4
        bitrate = 256000
        sample_rate = 44100
        channels = 2

    class _FakeAudio:
        def __init__(self) -> None:
            self.tags = {
                "title": ["Demo"],
                "artist": ["Unit"],
                "album": ["Test"],
                "genre": ["Rock"],
                "date": ["2024"],
                "tracknumber": ["1"],
            }
            self.info = _FakeInfo()

    def _fake_mutagen(_: str) -> _FakeAudio:
        calls["count"] += 1
        return _FakeAudio()

    monkeypatch.setattr("songsearch.core.scanner.MutagenFile", _fake_mutagen)
    scan_path(con, tmp_path)
    assert calls["count"] == 1
    scan_path(con, tmp_path)
    assert calls["count"] == 1


def test_enrich_uses_cached_payload(monkeypatch, tmp_path: Path) -> None:
    db_path = init_db(tmp_path)
    con = connect(db_path)
    track = tmp_path / "song.flac"
    track.write_bytes(b"fake-data")
    stat = track.stat()
    upsert_track(
        con,
        {
            "path": str(track),
            "mtime": stat.st_mtime,
            "file_size": stat.st_size,
            "format": "flac",
            "missing": 0,
        },
    )

    monkeypatch.setenv("ACOUSTID_API_KEY", "test-key")
    monkeypatch.setenv("MUSICBRAINZ_USER_AGENT", "SongSearchOrganizer/0.3 (tests@example.com)")

    calls = {"acoustid": 0}

    def _fake_match(api_key: str, filename: str, parse: bool = False):
        calls["acoustid"] += 1
        return {
            "status": "ok",
            "results": [
                {
                    "score": 0.91,
                    "id": "acoustid-123",
                    "recordings": [
                        {
                            "id": "rec-1",
                            "title": "Test Title",
                            "artists": [{"name": "Test Artist"}],
                        }
                    ],
                }
            ],
        }

    def _fake_recording(recording_id: str, includes=None):
        return {
            "recording": {
                "title": "Test Title",
                "artist-credit": [{"artist": {"name": "Test Artist"}}],
                "release-list": [
                    {
                        "id": "rel-1",
                        "title": "Album Name",
                        "artist-credit": [{"artist": {"name": "Album Artist"}}],
                        "date": "2024-01-15",
                        "medium-list": [
                            {
                                "track-list": [{"number": "1"}],
                                "position": "1",
                            }
                        ],
                    }
                ],
            }
        }

    monkeypatch.setattr("songsearch.core.metadata_enricher.acoustid.match", _fake_match)
    monkeypatch.setattr(
        "songsearch.core.metadata_enricher.musicbrainzngs.get_recording_by_id",
        _fake_recording,
    )
    monkeypatch.setattr(
        "songsearch.core.metadata_enricher.musicbrainzngs.get_image_list",
        lambda release_id: {"images": [{"front": True, "image": "http://img.test/cover.jpg"}]},
    )

    first = enrich_file(con, track, min_confidence=0.5, write_tags=False)
    assert first is not None
    assert first["title"] == "Test Title"
    assert calls["acoustid"] == 1

    second = enrich_file(con, track, min_confidence=0.5, write_tags=False)
    assert second is not None
    assert second["title"] == "Test Title"
    assert calls["acoustid"] == 1
