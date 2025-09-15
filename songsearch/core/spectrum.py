from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_spectrogram(input_path: Path, out_dir: Path) -> Path:
    input_path = input_path.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / (input_path.stem + "_spectrum.png")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg no encontrado en PATH")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-lavfi",
        "showspectrumpic=s=1200x600:legend=disabled",
        str(out_png),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg error: %s", e.stderr.decode(errors="ignore"))
        raise RuntimeError("ffmpeg failed") from e
    return out_png


def open_external(input_path: Path, app_path: str | None = None):
    p = str(input_path)
    if app_path:
        subprocess.Popen([app_path, p])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", p])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["start", "", p], shell=True)
    else:
        subprocess.Popen(["xdg-open", p])
