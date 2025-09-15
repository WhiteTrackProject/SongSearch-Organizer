from __future__ import annotations

from pathlib import Path

import pytest

from songsearch.core import metadata_enricher
from songsearch.core.db import connect, get_by_path, init_db, upsert_track


def test_enrich_file_persists_acoustid_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = init_db(tmp_path)
    con = connect(db_path)

    track_path = tmp_path / "song.mp3"
    track_path.write_bytes(b"data")
    upsert_track(con, {"path": str(track_path), "title": "Original"})

    monkeypatch.setenv("ACOUSTID_API_KEY", "token")

    acoustid_response = {
        "status": "ok",
        "results": [
            {
                "id": "acoustid-track-123",
                "score": 0.92,
                "recordings": [
                    {
                        "id": "mb-recording-1",
                        "title": "Test Title",
                        "artists": [
                            {"name": "Test Artist", "joinphrase": ""},
                        ],
                    }
                ],
            }
        ],
    }

    def fake_match(
        apikey, path, meta=metadata_enricher.acoustid.DEFAULT_META, parse=True, **kwargs
    ):
        assert apikey == "token"
        assert parse is False
        return acoustid_response

    fake_release = {
        "id": "release-1",
        "title": "Test Album",
        "artist-credit": [{"artist": {"name": "Album Artist"}}],
        "date": "2020-02-01",
        "medium-list": [{"position": "1", "track-list": [{"number": "5"}]}],
        "release-group": {
            "id": "release-group-1",
            "first-release-date": "2020-02-01",
        },
    }

    def fake_recording_by_id(rid, includes):
        assert rid == "mb-recording-1"
        return {
            "recording": {
                "id": rid,
                "title": "Test Title",
                "artist-credit": [{"artist": {"name": "Test Artist"}}],
                "release-list": [fake_release],
            }
        }

    monkeypatch.setattr(metadata_enricher.acoustid, "match", fake_match)
    monkeypatch.setattr(
        metadata_enricher.musicbrainzngs, "get_recording_by_id", fake_recording_by_id
    )
    monkeypatch.setattr(
        metadata_enricher.musicbrainzngs, "get_image_list", lambda release_id: {"images": []}
    )

    updates = metadata_enricher.enrich_file(con, track_path)

    assert updates is not None
    assert updates["acoustid_id"] == "acoustid-track-123"

    row = get_by_path(con, str(track_path))
    assert row is not None
    assert row["acoustid_id"] == "acoustid-track-123"
