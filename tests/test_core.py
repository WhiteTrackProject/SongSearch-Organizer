from pathlib import Path
import wave
from songsearch.core.db import (
    init_db,
    connect,
    query_tracks,
    upsert_track,
    fts_query_from_text,
)
from songsearch.core.scanner import scan_path
from songsearch.core.organizer import simulate


def _create_wav(p: Path):
    with wave.open(str(p), 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b'\x00\x00' * 44100)


def test_scan_and_simulate(tmp_path):
    db_path = init_db(tmp_path)
    con = connect(db_path)
    audio = tmp_path / 'test.wav'
    _create_wav(audio)
    scan_path(con, tmp_path)
    rows = query_tracks(con)
    assert len(rows) == 1
    plan = simulate(con, tmp_path / 'out', '{Artista}/{Título}.{ext}')
    assert len(plan) == 1


def test_query_tracks_full_text(tmp_path):
    db_path = init_db(tmp_path)
    con = connect(db_path)
    library = tmp_path / 'library'
    library.mkdir()
    track1 = library / 'Queen - Bohemian Rhapsody.mp3'
    track2 = library / 'Queen - Under Pressure.mp3'
    track3 = library / 'Misc' / 'demo-track.flac'
    track3.parent.mkdir(parents=True, exist_ok=True)
    for path in (track1, track2, track3):
        path.touch()

    upsert_track(
        con,
        {
            'path': str(track1),
            'title': 'Bohemian Rhapsody',
            'artist': 'Queen',
            'album': 'A Night at the Opera',
            'genre': 'Rock',
        },
    )
    upsert_track(
        con,
        {
            'path': str(track2),
            'title': 'Under Pressure',
            'artist': 'Queen',
            'album': 'Hot Space',
            'genre': 'Rock',
        },
    )
    upsert_track(
        con,
        {
            'path': str(track3),
            'title': 'Episode 1',
            'artist': 'Host',
            'album': 'Season 1',
            'genre': 'Podcast',
        },
    )

    def _search_paths(query: str):
        fts = fts_query_from_text(query)
        assert fts is not None
        return {row['path'] for row in query_tracks(con, fts_query=fts)}

    assert _search_paths('rhap') == {str(track1)}  # title
    assert _search_paths('quee') == {str(track1), str(track2)}  # artist
    assert _search_paths('oper') == {str(track1)}  # album
    assert _search_paths('roc') == {str(track1), str(track2)}  # genre
    assert _search_paths('demo') == {str(track3)}  # path
