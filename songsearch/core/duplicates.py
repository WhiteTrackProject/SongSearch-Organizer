from __future__ import annotations
from collections import defaultdict
from math import isfinite
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import shutil
from .db import update_fields


def _coerce_duration(value) -> Optional[float]:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(duration) or duration <= 0:
        return None
    return duration


def _coerce_size(value) -> Optional[int]:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    return size


def find_duplicates(rows: Iterable) -> List[List[Dict]]:
    buckets: Dict[Tuple[str, int], List[Dict[str, object]]] = defaultdict(list)
    for r in rows:
        duration = _coerce_duration(r["duration"])
        fmt = (r["format"] or "").lower()
        size = _coerce_size(r["file_size"])
        if duration is None or size is None or not fmt:
            continue

        record = dict(r)
        key = (fmt, size)
        groups = buckets[key]
        added = False
        for group in groups:
            min_duration = group["min_duration"]
            max_duration = group["max_duration"]
            new_min = min(min_duration, duration)
            new_max = max(max_duration, duration)
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

    return [g["records"] for groups in buckets.values() for g in groups if len(g["records"]) > 1]


def pick_best(file_group: List[Dict]) -> Dict:
    def key(r):
        return (int(r["bitrate"] or 0), int(r["file_size"] or 0))
    return sorted(file_group, key=key, reverse=True)[0]


def resolve_move_others(con, group: List[Dict], dest: Path) -> List[Tuple[str,str]]:
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
