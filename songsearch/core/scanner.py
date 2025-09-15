from __future__ import annotations
from pathlib import Path
from mutagen import File as MutagenFile
import logging
from .db import upsert_track
from .utils import is_audio

logger = logging.getLogger(__name__)


def scan_path(con, root: Path):
    root = root.expanduser().resolve()
    for p in root.rglob("*"):
        if not p.is_file() or not is_audio(p):
            continue
        try:
            stat = p.stat()
            info = {
                "path": str(p),
                "mtime": stat.st_mtime,
                "file_size": stat.st_size,
                "missing": 0
            }
            audio = MutagenFile(str(p), easy=True)
            if audio:
                info["title"] = _first(audio, "title")
                info["artist"] = _first(audio, "artist")
                info["album"] = _first(audio, "album")
                info["genre"] = _first(audio, "genre")
                info["year"] = _int_or_none(_first(audio, "date") or _first(audio, "year"))
                info["track_no"] = _int_or_none(_first(audio, "tracknumber"))
                info["format"] = p.suffix.lower().lstrip(".")
            audio_full = MutagenFile(str(p))
            if audio_full and getattr(audio_full.info, "length", None):
                info["duration"] = float(audio_full.info.length)
            if audio_full and getattr(audio_full.info, "bitrate", None):
                info["bitrate"] = int(audio_full.info.bitrate)
            if audio_full and getattr(audio_full.info, "sample_rate", None):
                info["samplerate"] = int(audio_full.info.sample_rate)
            if audio_full and getattr(audio_full.info, "channels", None):
                info["channels"] = int(audio_full.info.channels)
            upsert_track(con, info)
        except Exception as e:
            logger.warning("[scan] error with %s: %s", p, e)


def _first(meta, key: str):
    v = meta.get(key)
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


def _int_or_none(s):
    try:
        return int(str(s).split('/')[0][:4])
    except Exception:
        return None
