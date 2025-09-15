from __future__ import annotations
from pathlib import Path
import os
import typer
from rich import print
from rich.table import Table
from dotenv import load_dotenv
import logging

from ..core.db import init_db, connect
from ..core.scanner import scan_path
from ..core.organizer import simulate, export_csv, apply_plan, undo_from_log
from ..core.spectrum import generate_spectrogram, open_external
from ..core.metadata_enricher import enrich_db
from ..core.duplicates import find_duplicates, resolve_move_others, compute_partial_hash
from ..core.cover_art import ensure_cover_for_path

app = typer.Typer(help="SongSearch Organizer CLI")
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

DEFAULT_DATA_DIR = Path.home() / ".songsearch"
UNDO_LOG = DEFAULT_DATA_DIR / "logs" / "last_ops.json"
SPECTRO_DIR = DEFAULT_DATA_DIR / "spectra"
DB_PATH = init_db(DEFAULT_DATA_DIR)


@app.command()
def scan(path: str = typer.Option(..., "--path", help="Carpeta a escanear")):
    con = connect(DB_PATH)
    scan_path(con, Path(path))
    print("[green]Escaneo completado[/green] → DB:", DB_PATH)


@app.command()
def organize(
    template: str = typer.Option("default", "--template"),
    mode: str = typer.Option("simulate", "--mode", help="simulate|move|copy|link"),
    dest: str = typer.Option(..., "--dest", help="Carpeta destino"),
    export: bool = typer.Option(True, "--export/--no-export", help="Exportar CSV de plan")
):
    tpl = _load_template(template)
    con = connect(DB_PATH)
    plan = simulate(con, Path(dest), tpl)
    print(f"[cyan]{len(plan)}[/cyan] elementos en el plan ({mode}).")
    if mode == "simulate":
        _print_plan(plan)
        if export:
            csv_path = DEFAULT_DATA_DIR / "logs" / "plan.csv"
            export_csv(plan, csv_path)
            print("CSV:", csv_path)
    else:
        undo_log = apply_plan(plan, mode, UNDO_LOG, con=con)
        print("[green]Aplicado[/green]. Undo log:", undo_log)


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
        print("[green]Abierto externamente[/green]")
    else:
        out = generate_spectrogram(p, SPECTRO_DIR)
        print("Espectrograma:", out)


@app.command()
def enrich(
    limit: int = typer.Option(100, "--limit", help="Máximo de pistas a procesar"),
    min_confidence: float = typer.Option(0.6, "--min-confidence", help="Umbral de confianza (0-1)"),
    write_tags: bool = typer.Option(False, "--write-tags/--no-write-tags", help="Escribir tags al archivo además de la DB")
):
    con = connect(DB_PATH)
    rows = enrich_db(con, limit=limit, min_confidence=min_confidence, write_tags=write_tags)
    if not rows:
        print("[yellow]Sin cambios o sin coincidencias por encima del umbral.[/yellow]")
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
    print(table)


@app.command()
def covers(
    limit: int = typer.Option(200, "--limit", help="Máximo de pistas a intentar"),
    only_missing: bool = typer.Option(True, "--only-missing/--all", help="Solo pistas sin cover_local_path")
):
    """Descarga/extrae carátulas y las cachea en ~/.songsearch/covers/."""
    con = connect(DB_PATH)
    if only_missing:
        rows = con.execute("SELECT * FROM tracks WHERE missing=0 AND (cover_local_path IS NULL OR cover_local_path='') LIMIT ?", (limit,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM tracks WHERE missing=0 LIMIT ?", (limit,)).fetchall()
    ok = 0
    for r in rows:
        p = Path(r["path"])
        if not p.exists():
            continue
        out = ensure_cover_for_path(con, p)
        if out:
            ok += 1
            print("[green]OK[/green]", p.name, "→", out.name)
    print(f"[cyan]{ok}[/cyan] carátulas cacheadas.")


@app.command()
def dupes(
    move_to: str = typer.Option("", "--move-to", help="Si se indica, mueve duplicados (excepto el mejor) a esta carpeta"),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Mostrar grupos por pantalla"),
    use_hash: bool = typer.Option(False, "--use-hash", help="Usar hash parcial (más preciso)")
):
    con = connect(DB_PATH)
    rows = con.execute("SELECT * FROM tracks WHERE duration IS NOT NULL AND file_size IS NOT NULL AND missing=0").fetchall()

    if use_hash:
        missing = [r for r in rows if not r["hash_partial"]]
        for r in missing:
            p = Path(r["path"])
            if not p.exists():
                continue
            hp = compute_partial_hash(p)
            if hp:
                con.execute("UPDATE tracks SET hash_partial=? WHERE path=?", (hp, str(p)))
        con.commit()
        rows = con.execute("SELECT * FROM tracks WHERE duration IS NOT NULL AND file_size IS NOT NULL AND missing=0").fetchall()

    groups = find_duplicates(rows, use_hash=use_hash)
    print(f"[cyan]{len(groups)}[/cyan] grupos de posibles duplicados. (use_hash={use_hash})")
    if preview:
        for i, g in enumerate(groups[:50], start=1):
            table = Table(title=f"Grupo #{i} ({len(g)} archivos)")
            if use_hash:
                table.add_column("hash")
            else:
                table.add_column("dur")
            table.add_column("bitrate")
            table.add_column("size")
            table.add_column("path", overflow="fold")
            for r in g:
                table.add_row(
                    r.get("hash_partial") if use_hash else str(int(round(r.get("duration") or 0))),
                    str(r["bitrate"] or ""),
                    str(r["file_size"] or ""),
                    r["path"]
                )
            print(table)
        if len(groups) > 50:
            print("[dim]Mostrando solo los 50 primeros grupos…[/dim]")
    if move_to:
        dest = Path(move_to).expanduser()
        total = 0
        for g in groups:
            applied = resolve_move_others(con, g, dest)
            total += len(applied)
        print(f"[green]Movidos {total} duplicados a[/green] {dest}")


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
    print(table)
