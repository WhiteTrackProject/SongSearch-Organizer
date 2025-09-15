from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Iterable, Optional
import shutil, hashlib
from .db import update_fields


def compute_partial_hash(path: Path, head_bytes: int = 1_048_576, tail_bytes: int = 1_048_576) -> Optional[str]:
    try:
        size = path.stat().st_size
        if size <= 0:
            return None
        h = hashlib.sha1()
        with open(path, "rb") as f:
            h.update(f.read(head_bytes))
            if size > tail_bytes:
                f.seek(max(0, size - tail_bytes))
                h.update(f.read(tail_bytes))
        return h.hexdigest()
    except Exception:
        return None

def find_duplicates(rows: Iterable, use_hash: bool = False) -> List[List[Dict]]:
    if use_hash:
        by_hash: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            hp = r["hash_partial"]
            if hp:
                by_hash[hp].append(dict(r))
        return [g for g in by_hash.values() if len(g) > 1]
    buckets: Dict[Tuple[str,int,int], List[Dict]] = defaultdict(list)
    for r in rows:
        dur = int(round((r["duration"] or 0)))
        fmt = (r["format"] or "").lower()
        size = int(r["file_size"] or 0)
        if dur == 0 or size == 0 or not fmt:
            continue
        for d in (dur-1, dur, dur+1):
            buckets[(fmt, d, size)].append(dict(r))
    return [v for v in buckets.values() if len(v) > 1]


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
