import logging
from pathlib import Path
from urllib import request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

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
