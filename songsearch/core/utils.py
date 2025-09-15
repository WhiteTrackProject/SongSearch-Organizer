from __future__ import annotations

import re
import unicodedata
from pathlib import Path

AUDIO_EXT = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg", ".opus", ".wma"}

_illegal = re.compile(r'[<>:"/\\|?*\0]')


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXT


def clean_component(s: str) -> str:
    if not s:
        return "_"
    s = unicodedata.normalize("NFKC", s).strip()
    s = s.replace("\n", " ").replace("\r", " ")
    s = _illegal.sub("_", s)
    s = s.replace("..", "_")
    s = re.sub(r"\s{2,}", " ", s)
    return s[:200]


def render_template(tpl: str, meta: dict) -> str:
    safe = {k: clean_component(str(v)) if v is not None else "_" for k, v in meta.items()}
    return tpl.format(**safe)
