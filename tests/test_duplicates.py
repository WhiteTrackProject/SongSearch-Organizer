from songsearch.core.duplicates import find_duplicates


def _row(path: str, duration, file_size: int = 1024, fmt: str = "MP3"):
    return {
        "path": path,
        "duration": duration,
        "file_size": file_size,
        "format": fmt,
        "bitrate": 192000,
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


def test_find_duplicates_allows_one_second_difference():
    rows = [
        _row("c.mp3", 199.6),
        _row("d.mp3", 200.6),
    ]
    duplicates = find_duplicates(rows)
    assert _paths(duplicates) == [["c.mp3", "d.mp3"]]


def test_find_duplicates_rejects_greater_than_one_second_gap():
    rows = [
        _row("e.mp3", 199.6),
        _row("f.mp3", 201.0),
    ]
    duplicates = find_duplicates(rows)
    assert duplicates == []
