from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import os
import logging

import acoustid
import musicbrainzngs
from mutagen import File as MutagenFile

from .db import update_fields

logger = logging.getLogger(__name__)


def _init_musicbrainz():
    ua = os.getenv("MUSICBRAINZ_USER_AGENT") or "SongSearchOrganizer/0.2 (you@example.com)"
    app, ver, contact = _parse_user_agent(ua)
    musicbrainzngs.set_useragent(app, ver, contact)


def _parse_user_agent(ua: str) -> Tuple[str,str,str]:
    app = "SongSearchOrganizer"; ver = "0.2"; contact = "you@example.com"
    try:
        if "(" in ua and ")" in ua and "/" in ua:
            appver, contact_part = ua.split("(", 1)
            app, ver = appver.strip().split("/", 1)
            contact = contact_part.rstrip(")").strip()
        elif "/" in ua:
            app, ver = ua.split("/", 1)
    except Exception:
        pass
    return app, ver, contact


def needs_enrich(row) -> bool:
    return not (row["artist"] and row["title"] and row["album"] and row["year"])


def enrich_file(con, path: Path, min_confidence: float = 0.6, write_tags: bool = False) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("ACOUSTID_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ACOUSTID_API_KEY en .env")
    _init_musicbrainz()
    update_fields(con, str(path), {"fp_status": "pending"})
    best: Optional[Dict[str, Any]] = None
    try:
        for score, acoustid_id, rid, title, artist in _acoustid_match(api_key, path):
            rec = musicbrainzngs.get_recording_by_id(rid, includes=["artists","releases","release-groups"])["recording"]
            release, rel_group = _pick_best_release(rec.get("release-list", []))
            if not release:
                continue
            album = release.get("title")
            album_artist = _join_artist_credit(release.get("artist-credit") or rec.get("artist-credit"))
            date = release.get("date") or rel_group.get("first-release-date")
            year = _parse_year(date)
            track_no = release.get("medium-list", [{}])[0].get("track-list", [{}])[0].get("number")
            disc_no = release.get("medium-list", [{}])[0].get("position")
            cover_url = None
            try:
                imgs = musicbrainzngs.get_image_list(release["id"])
                for img in imgs.get("images", []):
                    if img.get("front"):
                        cover_url = img.get("image")
                        break
            except Exception:
                pass
            cand = {
                "acoustid_id": acoustid_id,
                "mb_recording_id": rid,
                "mb_release_id": release["id"],
                "mb_release_group_id": (rel_group or {}).get("id"),
                "mb_confidence": float(score),
                "title": title or rec.get("title"),
                "artist": artist or _join_artist_credit(rec.get("artist-credit")),
                "album": album,
                "album_artist": album_artist,
                "year": year,
                "track_no": _to_int(track_no),
                "disc_no": _to_int(disc_no),
                "cover_art_url": cover_url,
            }
            if best is None or cand["mb_confidence"] > best["mb_confidence"]:
                best = cand
    except Exception as e:
        update_fields(con, str(path), {"fp_status": "error"})
        logger.error("enrich error %s: %s", path, e)
        return None

    if not best or best["mb_confidence"] < min_confidence:
        update_fields(con, str(path), {"fp_status": "done"})
        return None

    updates = {
        "title": best["title"],
        "artist": best["artist"],
        "album": best["album"],
        "album_artist": best["album_artist"],
        "year": best["year"],
        "track_no": best["track_no"],
        "disc_no": best["disc_no"],
        "fp_status": "done",
        "acoustid_id": best["acoustid_id"],
        "mb_recording_id": best["mb_recording_id"],
        "mb_release_id": best["mb_release_id"],
        "mb_release_group_id": best["mb_release_group_id"],
        "mb_confidence": best["mb_confidence"],
        "cover_art_url": best["cover_art_url"],
    }
    update_fields(con, str(path), updates)

    if write_tags:
        try:
            mf = MutagenFile(str(path), easy=True)
            if mf is not None:
                if best["title"]: mf["title"] = [best["title"]]
                if best["artist"]: mf["artist"] = [best["artist"]]
                if best["album"]: mf["album"] = [best["album"]]
                if best["album_artist"]: mf["albumartist"] = [best["album_artist"]]
                if best["year"]: mf["date"] = [str(best["year"])]
                if best["track_no"]: mf["tracknumber"] = [str(best["track_no"])]
                if best["disc_no"]: mf["discnumber"] = [str(best["disc_no"])]
                mf.save()
        except Exception as e:
            logger.warning("cannot write tags for %s: %s", path, e)
    return updates


def enrich_db(con, limit: int = 100, min_confidence: float = 0.6, write_tags: bool = False) -> List[Dict[str, Any]]:
    rows = con.execute("""
        SELECT * FROM tracks
        WHERE (artist IS NULL OR title IS NULL OR album IS NULL OR year IS NULL)
        AND missing=0
        ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    results = []
    for r in rows:
        p = Path(r["path"])
        if not p.exists():
            update_fields(con, r["path"], {"missing": 1})
            continue
        upd = enrich_file(con, p, min_confidence=min_confidence, write_tags=write_tags)
        if upd:
            results.append({"path": r["path"], **upd})
    return results


def _acoustid_match(api_key: str, path: Path):
    response = acoustid.match(api_key, str(path), parse=False)
    status = response.get("status")
    if status != "ok":
        raise acoustid.WebServiceError(f"status: {status}")
    if "results" not in response:
        raise acoustid.WebServiceError("results not included")

    for result in response.get("results", []):
        recordings = result.get("recordings") or []
        if not recordings:
            continue
        score = result["score"]
        acoustid_id = result.get("id")
        for recording in recordings:
            artists = recording.get("artists")
            if artists:
                parts = []
                for artist in artists:
                    name = artist.get("name")
                    if not name:
                        continue
                    parts.append(name + (artist.get("joinphrase") or ""))
                artist_name = "".join(parts) if parts else None
            else:
                artist_name = None
            recording_id = recording.get("id")
            if not recording_id:
                continue
            yield score, acoustid_id, recording_id, recording.get("title"), artist_name


def _join_artist_credit(credit_list) -> Optional[str]:
    if not credit_list:
        return None
    parts = []
    for c in credit_list:
        name = c.get("artist", {}).get("name") or c.get("name")
        join = c.get("joinphrase", "")
        if name:
            parts.append(name + (join or ""))
    return "".join(parts) if parts else None


def _pick_best_release(releases: List[Dict[str, Any]]):
    if not releases:
        return None, None
    def rel_key(r):
        d = r.get("date") or ""
        return (d or "9999-99-99")
    best = sorted(releases, key=rel_key)[0]
    rel_group = best.get("release-group") or {}
    return best, rel_group


def _parse_year(date: Optional[str]) -> Optional[int]:
    if not date:
        return None
    try:
        return int(str(date)[:4])
    except Exception:
        return None


def _to_int(v):
    try:
        return int(v)
    except Exception:
        return None
