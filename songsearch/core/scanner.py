from __future__ import annotations

import logging
from pathlib import Path

from mutagen import File as MutagenFile

from .db import get_by_path, update_fields, upsert_track
from .utils import is_audio

logger = logging.getLogger(__name__)


TAG_KEY_ALIASES = {
    "title": ("title", "TITLE", "TIT2", "\u00a9nam"),
    "artist": ("artist", "ARTIST", "TPE1", "\u00a9ART"),
    "album": ("album", "ALBUM", "TALB", "\u00a9alb"),
    "genre": ("genre", "GENRE", "TCON", "\u00a9gen"),
    "date": ("date", "DATE", "TDRC", "TDOR", "TORY", "\u00a9day"),
    "year": ("year", "YEAR", "TYER"),
    "tracknumber": ("tracknumber", "TRACKNUMBER", "TRCK", "trkn"),
}


def scan_path(con, root: Path):
    root = root.expanduser().resolve()
    for p in root.rglob("*"):
        if not p.is_file() or not is_audio(p):
            continue
        try:
            stat = p.stat()
            existing = get_by_path(con, str(p))
            if (
                existing
                and existing["mtime"] == stat.st_mtime
                and existing["file_size"] == stat.st_size
            ):
                updates = {}
                if existing["missing"]:
                    updates["missing"] = 0
                if updates:
                    update_fields(con, str(p), updates)
                continue
            info = {"path": str(p), "mtime": stat.st_mtime, "file_size": stat.st_size, "missing": 0}
            audio = MutagenFile(str(p))
            if audio:
                tags = getattr(audio, "tags", None)
                if tags:
                    info["title"] = _first(tags, TAG_KEY_ALIASES["title"])
                    info["artist"] = _first(tags, TAG_KEY_ALIASES["artist"])
                    info["album"] = _first(tags, TAG_KEY_ALIASES["album"])
                    info["genre"] = _first(tags, TAG_KEY_ALIASES["genre"])
                    info["year"] = _int_or_none(
                        _first(tags, TAG_KEY_ALIASES["date"])
                        or _first(tags, TAG_KEY_ALIASES["year"])
                    )
                    info["track_no"] = _int_or_none(_first(tags, TAG_KEY_ALIASES["tracknumber"]))
                info["format"] = p.suffix.lower().lstrip(".")
                audio_info = getattr(audio, "info", None)
                if audio_info and getattr(audio_info, "length", None) is not None:
                    info["duration"] = float(audio_info.length)
                if audio_info and getattr(audio_info, "bitrate", None) is not None:
                    info["bitrate"] = int(audio_info.bitrate)
                if audio_info and getattr(audio_info, "sample_rate", None) is not None:
                    info["samplerate"] = int(audio_info.sample_rate)
                if audio_info and getattr(audio_info, "channels", None) is not None:
                    info["channels"] = int(audio_info.channels)
            upsert_track(con, info)
        except Exception as e:
            logger.warning("[scan] error with %s: %s", p, e)


def _first(meta, key):
    if meta is None or key is None:
        return None

    if isinstance(key, (list, tuple)):
        for name in key:
            value = _first(meta, name)
            if value not in (None, ""):
                return value
        return None

    candidates = []
    getter = getattr(meta, "getall", None)
    if callable(getter):
        try:
            candidates.extend(getter(key) or [])
        except Exception:
            pass

    getter = getattr(meta, "get", None)
    if callable(getter):
        candidates.append(getter(key))
    else:
        try:
            candidates.append(meta[key])
        except Exception:
            pass

    for candidate in candidates:
        value = _coerce_first(candidate)
        if value not in (None, ""):
            return value
    return None


def _coerce_first(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="ignore")
    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = _coerce_first(item)
            if normalized not in (None, ""):
                return normalized
        return None
    if hasattr(value, "text"):
        return _coerce_first(value.text)
    if hasattr(value, "value"):
        return _coerce_first(value.value)
    return str(value)


def _int_or_none(s):
    try:
        return int(str(s).split("/")[0][:4])
    except Exception:
        return None
