from __future__ import annotations

import imghdr
import logging
from hashlib import sha1
from pathlib import Path
from typing import Iterable, Optional
from urllib import request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_KNOWN_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")


def _existing_hashed_files(base: Path) -> Iterable[Path]:
    for ext in _KNOWN_EXTENSIONS:
        candidate = base.with_suffix(ext)
        if candidate.exists():
            yield candidate


def _normalise_extension(ext: str) -> str:
    ext = ext.lower()
    if not ext:
        return ""
    if ext == ".jpeg":
        return ".jpg"
    if ext in _KNOWN_EXTENSIONS:
        return ext
    return ""


def _ext_from_imghdr(path: Path) -> str:
    kind = imghdr.what(path)
    if not kind:
        return ""
    if kind == "jpeg":
        return ".jpg"
    return "." + kind


def _download(url: str, destination: Path) -> bool:
    """Download a file from *url* into *destination*.

    Parameters
    ----------
    url:
        The URL to download.
    destination:
        Path where the content will be written.

    Returns
    -------
    bool
        ``True`` if the download succeeded, otherwise ``False``.
    """
    try:
        with request.urlopen(url) as response:
            destination.write_bytes(response.read())
            return True
    except (HTTPError, URLError) as exc:
        logger.warning("Failed to download %s: %s", url, exc)
    except Exception as exc:  # pragma: no cover - unexpected errors
        logger.error("Unexpected error downloading %s: %s", url, exc)
    return False


def ensure_cover_for_path(data_dir: Path, track_path: Path, cover_url: Optional[str]) -> Optional[Path]:
    """Ensure a local cover image exists for *track_path*.

    Parameters
    ----------
    data_dir:
        Base directory used to store cached cover art.
    track_path:
        Path to the audio file.
    cover_url:
        URL (remote or local) pointing to the cover art. Can be ``None``.

    Returns
    -------
    Optional[Path]
        Path to the local image file if available, otherwise ``None``.
    """

    track_path = Path(track_path)
    if not cover_url:
        return _find_local_cover(track_path)

    url = cover_url.strip()
    if not url:
        return _find_local_cover(track_path)

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "file" or (scheme == "" and not parsed.netloc):
        # Treat as local path. Relative paths are resolved from the track directory.
        raw_path = parsed.path if scheme == "file" else url
        local_path = Path(raw_path)
        if not local_path.is_absolute():
            local_path = (track_path.parent / local_path).resolve()
        if local_path.exists():
            return local_path
        logger.debug("Local cover path not found: %s", local_path)
        return _find_local_cover(track_path)

    if scheme in ("http", "https") or parsed.netloc:
        cache_dir = data_dir / "covers"
        cache_dir.mkdir(parents=True, exist_ok=True)
        base_name = sha1(url.encode("utf-8")).hexdigest()
        base_path = cache_dir / base_name

        existing = list(_existing_hashed_files(base_path))
        if existing:
            return existing[0]

        temp_path = base_path.with_suffix(".part")
        if _download(url, temp_path):
            ext = _normalise_extension(Path(parsed.path).suffix)
            if not ext:
                ext = _ext_from_imghdr(temp_path)
            if not ext:
                ext = ".jpg"
            final_path = base_path.with_suffix(ext)
            try:
                temp_path.replace(final_path)
                return final_path
            except Exception as exc:  # pragma: no cover - unexpected errors
                logger.error("Failed to store cover %s → %s: %s", temp_path, final_path, exc)
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:  # pragma: no cover - best effort cleanup
                    pass
                return None
        else:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:  # pragma: no cover - best effort cleanup
                pass
        return _find_local_cover(track_path)

    return _find_local_cover(track_path)


def _find_local_cover(track_path: Path) -> Optional[Path]:
    candidates = []
    stem = track_path.stem
    parent = track_path.parent
    for suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        candidates.append(parent / f"{stem}{suffix}")
    for name in ("cover", "folder", "front", "AlbumArtSmall", "AlbumArtLarge"):
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            candidates.append(parent / f"{name}{suffix}")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
