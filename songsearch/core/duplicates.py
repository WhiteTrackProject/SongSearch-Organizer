from __future__ import annotations

import math
import shutil
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypedDict

from .db import update_fields

_FORMAT_SCORES = {
    "flac": 400,
    "alac": 390,
    "wav": 380,
    "aiff": 370,
    "aif": 360,
    "ape": 350,
    "wv": 340,
    "m4a": 260,  # AAC/ALAC container
    "aac": 250,
    "ogg": 220,
    "opus": 210,
    "mp3": 200,
    "wma": 180,
}


def _coerce_duration(value) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


def _coerce_size(value) -> int | None:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    return size


class _DuplicateGroup(TypedDict):
    records: list[dict[str, Any]]
    min_duration: float
    max_duration: float


def find_duplicates(rows: Iterable) -> list[list[dict[str, Any]]]:
    buckets: dict[tuple[str, int], list[_DuplicateGroup]] = defaultdict(list)
    for r in rows:
        duration = _coerce_duration(r["duration"])
        fmt = (r["format"] or "").lower()
        size = _coerce_size(r["file_size"])
        if duration is None or size is None or not fmt:
            continue

        record: dict[str, Any] = dict(r)
        key = (fmt, size)
        groups = buckets[key]
        added = False
        for group in groups:
            min_duration = group["min_duration"]
            max_duration = group["max_duration"]
            new_min = min(float(min_duration), duration)
            new_max = max(float(max_duration), duration)
            if new_max - new_min <= 1.0:
                group["records"].append(record)
                group["min_duration"] = new_min
                group["max_duration"] = new_max
                added = True
                break
        if not added:
            groups.append(
                {
                    "records": [record],
                    "min_duration": duration,
                    "max_duration": duration,
                }
            )

    return [
        group["records"]
        for groups in buckets.values()
        for group in groups
        if len(group["records"]) > 1
    ]


def pick_best(file_group: list[dict[str, Any]]) -> dict[str, Any]:
    def quality_key(record: dict[str, Any]) -> tuple[int, int, int, float]:
        fmt = (record.get("format") or "").lower()
        fmt_score = _FORMAT_SCORES.get(fmt, 0)
        bitrate = int(record.get("bitrate") or 0)
        file_size = int(record.get("file_size") or 0)
        duration = float(record.get("duration") or 0.0)
        return (fmt_score, bitrate, file_size, duration)

    return sorted(file_group, key=quality_key, reverse=True)[0]


def resolve_move_others(con, group: list[dict[str, Any]], dest: Path) -> list[tuple[str, str]]:
    dest.mkdir(parents=True, exist_ok=True)
    keeper = pick_best(group)
    applied = []
    for r in group:
        if r["path"] == keeper["path"]:
            continue
        src = Path(r["path"])
        if not src.exists():
            continue
        dst = dest / src.name
        i = 1
        while dst.exists():
            dst = dest / f"{src.stem} ({i}){src.suffix}"
            i += 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        update_fields(con, str(src), {"path": str(dst)})
        applied.append((str(src), str(dst)))
    return applied
