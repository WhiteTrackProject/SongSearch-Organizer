from __future__ import annotations

import logging
import socket
from hashlib import sha1
from pathlib import Path
from typing import Iterable, Optional
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = 10

_KNOWN_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
)


def _looks_like_windows_drive(value: str) -> bool:
    if len(value) < 2:
        return False
    prefix, remainder = value[0], value[1]
    if not prefix.isalpha():
        return False
    return remainder == ":"


def _normalise_candidate(
    track_path: Path, candidate: Path, *, treat_as_absolute: bool = False
) -> Path:
    """Return an absolute path for *candidate* relative to *track_path*.

    ``Path.resolve`` is used in non-strict mode to avoid raising when the
    destination does not exist yet. Any errors are ignored to favour returning
    a sensible best-effort value.
    """

    try:
        candidate = candidate.expanduser()
    except Exception:  # pragma: no cover - defensive
        pass

    if not treat_as_absolute and not candidate.is_absolute():
        candidate = track_path.parent / candidate

    try:
        candidate = candidate.resolve(strict=False)
    except Exception:  # pragma: no cover - best effort
        try:
            candidate = candidate.absolute()
        except Exception:  # pragma: no cover - nothing else we can do
            pass

    return candidate


def _local_path_from_url(url: str, track_path: Path) -> Optional[Path]:
    """Try to interpret *url* as a local file path."""

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "file":
        raw_path = request.url2pathname(parsed.path or "")
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            raw_path = f"//{parsed.netloc}{raw_path}"
        treat_as_absolute = _looks_like_windows_drive(raw_path) or raw_path.startswith("\\")
        candidate = _normalise_candidate(
            track_path, Path(raw_path), treat_as_absolute=treat_as_absolute
        )
        if candidate.exists():
            return candidate
        return None

    if _looks_like_windows_drive(url):
        candidate = _normalise_candidate(
            track_path, Path(url), treat_as_absolute=True
        )
        if candidate.exists():
            return candidate
        return None

    if url.startswith("\\"):
        candidate = _normalise_candidate(
            track_path, Path(url), treat_as_absolute=True
        )
        if candidate.exists():
            return candidate
        return None

    if not scheme and not parsed.netloc:
        candidate = _normalise_candidate(track_path, Path(url))
        if candidate.exists():
            return candidate

    return None


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
    """Best-effort image type detection.

    The project previously relied on :mod:`imghdr` which has been removed in
    Python 3.13.  To remain dependency free we implement the tiny subset of
    functionality we require.  Only a handful of common formats are supported
    and an empty string is returned if the file type cannot be determined.
    """

    try:
        header = path.read_bytes()[:12]
    except OSError:
        return ""

    # JPEG
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    # PNG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    # GIF
    if header[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    # WEBP
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    # BMP
    if header.startswith(b"BM"):
        return ".bmp"
    # TIFF (little or big endian)
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"

    return ""


def _cleanup_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - best effort cleanup
        pass


def _is_timeout_error(error: object) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    try:
        message = str(error)
    except Exception:  # pragma: no cover - defensive
        return False
    return "timed out" in message.lower()


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
        with request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:
            destination.write_bytes(response.read())
            return True
    except HTTPError as exc:
        logger.warning("Failed to download %s: %s", url, exc)
        _cleanup_partial(destination)
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        if _is_timeout_error(reason):
            logger.warning(
                "Timed out downloading %s after %ss: %s", url, _DOWNLOAD_TIMEOUT, reason
            )
        else:
            logger.warning("Failed to download %s: %s", url, exc)
        _cleanup_partial(destination)
    except TimeoutError as exc:
        logger.warning(
            "Timed out downloading %s after %ss: %s", url, _DOWNLOAD_TIMEOUT, exc
        )
        _cleanup_partial(destination)
    except Exception as exc:  # pragma: no cover - unexpected errors
        logger.error("Unexpected error downloading %s: %s", url, exc)
        _cleanup_partial(destination)
    return False


def ensure_cover_for_path(
    data_dir: Path, track_path: Path, cover_url: Optional[str]
) -> Optional[Path]:
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
    data_dir = Path(data_dir)

    if not cover_url:
        return _find_local_cover(track_path)

    url = cover_url.strip()
    if not url:
        return _find_local_cover(track_path)

    local_candidate = _local_path_from_url(url, track_path)
    if local_candidate:
        return local_candidate

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    is_remote = scheme in {"http", "https"} or (
        parsed.netloc and scheme not in {"", "file"}
    ) or (not scheme and parsed.netloc)

    if is_remote:
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
