from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple
import csv, json, shutil, os, logging
from .utils import render_template, clean_component
from .db import query_tracks, update_fields

logger = logging.getLogger(__name__)


def simulate(
    con,
    dest: Path,
    template: str,
    where: str = "",
    params=(),
    require_cover: bool = False,
    require_year: bool = False,
    album_mode: str = "",
    fallback_to_tags: bool = False,
):
    dest = dest.expanduser().resolve()
    rows = query_tracks(con, where, params)
    plan: List[Tuple[str, str]] = []
    for r in rows:
        if require_cover and not r["cover_art_url"]:
            continue
        if require_year and not r["year"]:
            continue

        mb_release_id = r["mb_release_id"]
        track_template = template
        if album_mode == "mb-release" and not mb_release_id:
            if not fallback_to_tags:
                continue
            track_template = "{Artista}/{Álbum}/{TrackNo - Título}.{ext}"

        meta = {
            "Genero": r["genre"] or "_",
            "Año": r["year"] or "_",
            "Artista": r["artist"] or "_",
            "Álbum": r["album"] or "_",
            "TrackNo": f"{int(r['track_no']):02d}" if r["track_no"] else "_",
            "Título": r["title"] or Path(r["path"]).stem,
            "ext": Path(r["path"]).suffix.lstrip(".") or "mp3",
            "ReleaseID": mb_release_id or "_",
        }
        rel = render_template(track_template, meta)
        rel = "/".join(clean_component(c) for c in rel.split("/"))
        target = dest / rel
        target = target.with_suffix("." + meta["ext"])
        plan.append((r["path"], str(target)))
    return plan


def export_csv(plan: List[Tuple[str,str]], out_csv: Path):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source","target"])
        w.writerows(plan)
    return out_csv


def _unique_path(p: Path) -> Path:
    base = p
    i = 1
    while p.exists():
        p = base.with_name(f"{base.stem} ({i}){base.suffix}")
        i += 1
    return p


def apply_plan(plan: List[Tuple[str,str]], mode: str, undo_log: Path, con=None):
    ops_done = []
    for src, dst in plan:
        src_p = Path(src)
        dst_p = _unique_path(Path(dst))
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if mode == "move":
                shutil.move(str(src_p), str(dst_p))
                ops_done.append({"op":"move","src":str(src_p),"dst":str(dst_p)})
                if con:
                    update_fields(con, str(src_p), {"path": str(dst_p)})
            elif mode == "copy":
                shutil.copy2(str(src_p), str(dst_p))
                ops_done.append({"op":"copy","src":str(src_p),"dst":str(dst_p)})
            elif mode == "link":
                try:
                    os.link(str(src_p), str(dst_p))
                except OSError:
                    try:
                        os.symlink(str(src_p), str(dst_p))
                    except OSError as e:
                        logger.error("link failed for %s: %s", src_p, e)
                        continue
                ops_done.append({"op":"link","src":str(src_p),"dst":str(dst_p)})
            else:
                raise ValueError("mode inválido")
        except Exception as e:
            logger.error("apply_plan error %s -> %s: %s", src_p, dst_p, e)
            continue
    undo_log.parent.mkdir(parents=True, exist_ok=True)
    undo_log.write_text(json.dumps(ops_done, ensure_ascii=False, indent=2))
    return undo_log


def undo_from_log(log_path: Path):
    if not log_path.exists():
        logger.info("[undo] No log at %s", log_path)
        return
    ops = json.loads(log_path.read_text())
    for entry in reversed(ops):
        op, src, dst = entry["op"], Path(entry["src"]), Path(entry["dst"])
        try:
            if op == "move":
                if dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
            elif op == "copy":
                if dst.exists():
                    dst.unlink()
            elif op == "link":
                if dst.exists():
                    dst.unlink()
        except Exception as e:
            logger.error("undo error %s: %s", entry, e)
    logger.info("[undo] Reversión completada")
