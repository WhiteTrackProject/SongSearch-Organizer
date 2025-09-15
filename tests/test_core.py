from pathlib import Path
import wave
from songsearch.core.db import init_db, connect, query_tracks
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
