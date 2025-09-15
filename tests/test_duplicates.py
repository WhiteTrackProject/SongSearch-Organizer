from __future__ import annotations

from pathlib import Path

from songsearch.core.duplicates import find_duplicates, resolve_move_others


def _row(
    path: str,
    duration,
    *,
    file_size: int = 1024,
    fmt: str = "MP3",
    bitrate: int = 192000,
):
    return {
        "path": path,
        "duration": duration,
        "file_size": file_size,
        "format": fmt,
        "bitrate": bitrate,
    }


def _paths(groups):
    return [sorted(r["path"] for r in group) for group in groups]


def test_find_duplicates_accepts_subsecond_variation():
    rows = [
        _row("a.mp3", "199.6"),
        _row("b.mp3", 200.4, fmt="mp3"),
    ]
    duplicates = find_duplicates(rows)
    assert _paths(duplicates) == [["a.mp3", "b.mp3"]]


def test_find_duplicates_groups_multiple_entries_within_window():
    rows = [
        _row("c.mp3", 199.9),
        _row("d.mp3", 200.1),
        _row("e.mp3", 200.6),
    ]
    duplicates = find_duplicates(rows)
    assert _paths(duplicates) == [["c.mp3", "d.mp3", "e.mp3"]]


def test_find_duplicates_rejects_greater_than_one_second_gap():
    rows = [
        _row("f.mp3", 199.6),
        _row("g.mp3", 201.0),
    ]
    duplicates = find_duplicates(rows)
    assert duplicates == []


def test_resolve_move_others_moves_files_and_updates_database(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    keeper_file = src_dir / "keeper.mp3"
    keeper_file.write_text("keeper")
    low_file = src_dir / "low.mp3"
    low_file.write_text("low")
    mid_file = src_dir / "mid.mp3"
    mid_file.write_text("mid")

    group = [
        _row(str(keeper_file), 200.0, file_size=4096, bitrate=320000),
        _row(str(low_file), 200.2, file_size=1024, bitrate=128000),
        _row(str(mid_file), 200.3, file_size=2048, bitrate=256000),
    ]

    updates = []

    def fake_update(con, path, values):
        updates.append((con, path, values))

    monkeypatch.setattr("songsearch.core.duplicates.update_fields", fake_update)

    dest = tmp_path / "duplicates"
    sentinel_con = object()

    moved = resolve_move_others(sentinel_con, group, dest)

    assert keeper_file.exists()
    assert not low_file.exists()
    assert not mid_file.exists()

    moved_paths = {Path(src): Path(dst) for src, dst in moved}
    expected_low_dest = dest / low_file.name
    expected_mid_dest = dest / mid_file.name

    assert moved_paths == {low_file: expected_low_dest, mid_file: expected_mid_dest}
    assert expected_low_dest.read_text() == "low"
    assert expected_mid_dest.read_text() == "mid"

    assert updates == [
        (sentinel_con, str(low_file), {"path": str(expected_low_dest)}),
        (sentinel_con, str(mid_file), {"path": str(expected_mid_dest)}),
    ]
