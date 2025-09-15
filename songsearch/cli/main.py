from __future__ import annotations
from pathlib import Path
from typing import Literal
import os
import typer
from rich.table import Table
from rich.logging import RichHandler
from dotenv import load_dotenv
import logging

from ..core.db import init_db, connect
from ..core.scanner import scan_path
from ..core.organizer import simulate, export_csv, apply_plan, undo_from_log
from ..core.spectrum import generate_spectrogram, open_external
from ..core.metadata_enricher import enrich_db
from ..core.duplicates import find_duplicates, resolve_move_others

app = typer.Typer(help="SongSearch Organizer CLI")
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path.home() / ".songsearch"
UNDO_LOG = DEFAULT_DATA_DIR / "logs" / "last_ops.json"
SPECTRO_DIR = DEFAULT_DATA_DIR / "spectra"
DB_PATH = init_db(DEFAULT_DATA_DIR)


@app.command()
def scan(path: str = typer.Option(..., "--path", help="Carpeta a escanear")):
    con = connect(DB_PATH)
    scan_path(con, Path(path))
    logger.info("Escaneo completado → DB: %s", DB_PATH)


@app.command()
def organize(
    template: str = typer.Option("default", "--template"),
    mode: str = typer.Option("simulate", "--mode", help="simulate|move|copy|link"),
    dest: str = typer.Option(..., "--dest", help="Carpeta destino"),
    export: bool = typer.Option(True, "--export/--no-export", help="Exportar CSV de plan"),
    require_cover: bool = typer.Option(False, "--require-cover/--no-require-cover", help="Solo incluir pistas con cover"),
    require_year: bool = typer.Option(False, "--require-year/--no-require-year", help="Solo incluir pistas con año"),
    album_mode: Literal["tags", "mb-release"] = typer.Option("tags", "--album-mode", help="tags|mb-release"),
    fallback_tags: bool = typer.Option(False, "--fallback-tags/--no-fallback-tags", help="Si falta MB release usa tags"),
):
    tpl = _load_template(template)
    con = connect(DB_PATH)
    plan = simulate(
        con,
        Path(dest),
        tpl,
        require_cover=require_cover,
        require_year=require_year,
        album_mode=album_mode,
        fallback_to_tags=fallback_tags,
    )
    logger.info("%d elementos en el plan (%s).", len(plan), mode)
    if mode == "simulate":
        _print_plan(plan)
        if export:
            csv_path = DEFAULT_DATA_DIR / "logs" / "plan.csv"
            export_csv(plan, csv_path)
            logger.info("CSV: %s", csv_path)
    else:
        undo_log = apply_plan(plan, mode, UNDO_LOG, con=con)
        logger.info("Aplicado. Undo log: %s", undo_log)


@app.command()
def undo():
    undo_from_log(UNDO_LOG)


@app.command()
def spectrum(
    input: str = typer.Option(..., "--input", help="Archivo de audio"),
    open_external_app: bool = typer.Option(False, "--open-external", help="Abrir en app externa")
):
    p = Path(input)
    if open_external_app:
        app_path = os.getenv("SPEK_APP_PATH") or None
        open_external(p, app_path)
        logger.info("Abierto externamente")
    else:
        out = generate_spectrogram(p, SPECTRO_DIR)
        logger.info("Espectrograma: %s", out)


@app.command()
def enrich(
    limit: int = typer.Option(100, "--limit", help="Máximo de pistas a procesar"),
    min_confidence: float = typer.Option(0.6, "--min-confidence", help="Umbral de confianza (0-1)"),
    write_tags: bool = typer.Option(False, "--write-tags/--no-write-tags", help="Escribir tags al archivo además de la DB")
):
    con = connect(DB_PATH)
    rows = enrich_db(con, limit=limit, min_confidence=min_confidence, write_tags=write_tags)
    if not rows:
        logger.warning("Sin cambios o sin coincidencias por encima del umbral.")
        return
    table = Table(title=f"Enriquecidos ({len(rows)})")
    table.add_column("Path", overflow="fold")
    table.add_column("Título")
    table.add_column("Artista")
    table.add_column("Álbum")
    table.add_column("Año")
    table.add_column("Conf.")
    for r in rows:
        table.add_row(r["path"], str(r.get("title") or ""), str(r.get("artist") or ""),
                      str(r.get("album") or ""), str(r.get("year") or ""), f"{r.get('mb_confidence', 0):.2f}")
    logger.info(table)


@app.command()
def dupes(
    move_to: str = typer.Option("", "--move-to", help="Si se indica, mueve duplicados (excepto el mejor) a esta carpeta"),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Mostrar grupos por pantalla")
):
    con = connect(DB_PATH)
    rows = con.execute("SELECT * FROM tracks WHERE duration IS NOT NULL AND file_size IS NOT NULL AND missing=0").fetchall()
    groups = find_duplicates(rows)
    logger.info("%d grupos de posibles duplicados.", len(groups))
    if preview:
        for i, g in enumerate(groups[:50], start=1):
            table = Table(title=f"Grupo #{i} ({len(g)} archivos)")
            table.add_column("bitrate")
            table.add_column("size")
            table.add_column("path", overflow="fold")
            for r in g:
                table.add_row(str(r["bitrate"] or ""), str(r["file_size"] or ""), r["path"])
            logger.info(table)
        if len(groups) > 50:
            logger.info("Mostrando solo los 50 primeros grupos…")
    if move_to:
        dest = Path(move_to).expanduser()
        total = 0
        for g in groups:
            applied = resolve_move_others(con, g, dest)
            total += len(applied)
        logger.info("Movidos %d duplicados a %s", total, dest)


def _load_template(name: str) -> str:
    import yaml
    cfg_p = Path("config/templates.yml")
    try:
        data = yaml.safe_load(cfg_p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "{Genero}/{Año}/{Artista}/{Álbum}/{TrackNo - Título}.{ext}"
    if name == "default":
        return data.get("default") or "{Genero}/{Año}/{Artista}/{Álbum}/{TrackNo - Título}.{ext}"
    for alt in data.get("alternativas", []):
        if isinstance(alt, dict) and alt.get("name") == name:
            return alt["pattern"]
    return name


def _print_plan(plan):
    table = Table(title="Vista previa (simulate)")
    table.add_column("Source", overflow="fold")
    table.add_column("Target", overflow="fold")
    for s, t in plan[:200]:
        table.add_row(s, t)
    logger.info(table)
