from __future__ import annotations
from pathlib import Path
from typing import Optional
import httpx
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
from mutagen.flac import Picture
from mutagen.mp4 import MP4
from .db import get_by_path, update_fields

COVERS_DIR = Path.home() / ".songsearch" / "covers"

def _ensure_dir():
    COVERS_DIR.mkdir(parents=True, exist_ok=True)

def _save_bytes(img: bytes, name_hint: str) -> Path:
    _ensure_dir()
    out = COVERS_DIR / f"{name_hint}.jpg"
    out.write_bytes(img)
    return out

def _extract_embedded(path: Path) -> Optional[bytes]:
    mf = MutagenFile(str(path))
    if mf is None:
        return None
    try:
        id3 = mf if isinstance(mf, ID3) else getattr(mf, "tags", None)
        if isinstance(id3, ID3):
            for apic in id3.getall("APIC"):
                if isinstance(apic, APIC) and apic.data:
                    return bytes(apic.data)
    except Exception:
        pass
    try:
        pics = getattr(mf, "pictures", None)
        if pics:
            pic: Picture = pics[0]
            return bytes(pic.data)
    except Exception:
        pass
    try:
        if isinstance(mf, MP4):
            covr = mf.tags.get("covr")
            if covr:
                data = covr[0]
                if hasattr(data, "data"):
                    return bytes(data.data)
                return bytes(data)
    except Exception:
        pass
    return None

def _download(url: str) -> Optional[bytes]:
    try:
        headers = {"User-Agent": "SongSearchOrganizer/0.1 (+cover-downloader)"}
        with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            if r.status_code == 200 and r.content:
                return r.content
    except Exception:
        return None
    return None

def ensure_cover_for_path(con, path: Path) -> Optional[Path]:
    row = get_by_path(con, str(path))
    hint = (row["mb_release_id"] or row["mb_recording_id"] or path.stem) if row else path.stem
    if row and row["cover_local_path"]:
        p = Path(row["cover_local_path"])
        if p.exists():
            return p
    emb = _extract_embedded(path)
    if emb:
        out = _save_bytes(emb, f"emb_{hint}")
        update_fields(con, str(path), {"cover_local_path": str(out), "cover_fetched": 1})
        return out
    url = row["cover_art_url"] if row else None
    if url:
        data = _download(url)
        if data:
            out = _save_bytes(data, f"mb_{hint}")
            update_fields(con, str(path), {"cover_local_path": str(out), "cover_fetched": 1})
            return out
    return None
