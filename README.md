# SongSearch Organizer (v0.1)

**Organiza tu biblioteca musical** de forma **rápida, segura y reversible**.  
Escanea carpetas, completa metadatos con **MusicBrainz/AcoustID**, detecta duplicados, y **recoloca** archivos en una nueva estructura por **Género/Año/Artista/Álbum**, con **modo simulación** y **deshacer**. Incluye **analizador de espectro** (integrado con `ffmpeg`) y lanzador externo (Spek).

---

## ✨ Características (MVP v0.1)

- **Organizador por plantillas**:  
  `{Genero}/{Año}/{Artista}/{Álbum}/{TrackNo - Título}.{ext}` (personalizable).
- **Modo Simulación**: vista previa `Ruta actual → Nueva ruta` antes de mover/copiar/enlazar.
- **Deshacer**: log de operaciones para revertir en 1 clic.
- **Detección de archivos perdidos** y reubicación por cambio de raíz.
- **Duplicados**: agrupación por `duración±1s+tamaño+formato` + hash parcial opcional.
- **Metadatos**: `pyacoustid + Chromaprint` → `AcoustID` → `MusicBrainz` (+ Cover Art).
- **Espectro**: generar PNG con `ffmpeg` (y abrir Spek/Audacity si lo prefieres).
- **UI rápida** (PySide6): buscador, tabla de resultados, panel de detalles, progreso.

---

## 🧱 Stack

- **Python 3.13.7**
- **SQLite + FTS5** (búsqueda full-text rápida)
- **mutagen** (tags), **watchdog** (cambios en disco)
- **pyacoustid** + `fpcalc` (Chromaprint)
- **musicbrainzngs** + Cover Art Archive
- **ffmpeg** (espectrograma)
- **PySide6** (UI)

---

## 📦 Requisitos del sistema (macOS)

1) Instala dependencias nativas:
```bash
brew install python@3.13 ffmpeg chromaprint sqlite
```

2) Crea entorno virtual + activa:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python --version   # debe mostrar 3.13.7
```

3) Instala dependencias Python (editarás `requirements.txt` con el esqueleto):

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración rápida

Crea `.env` en la raíz con tus claves (las puedes dejar vacías para pruebas locales):

```ini
ACOUSTID_API_KEY=tu_api_key_opcional
MUSICBRAINZ_USER_AGENT=SongSearchOrganizer/0.1 (tu_email@ejemplo.com)
SPEK_APP_PATH=        # opcional: ruta a Spek/Audacity
```

**Plantillas de organización** (archivo `config/templates.yml`):

```yaml
default: "{Genero}/{Año}/{Artista}/{Álbum}/{TrackNo - Título}.{ext}"
alternativas:
  - "{Artista}/{Año} - {Álbum}/{TrackNo - Título}.{ext}"
  - "{Año}/{Genero}/{Artista}/{Título}.{ext}"
reglas:
  limpiar_nombres: true
  quitar_parentesis_promos: true
  reemplazos_caracteres_prohibidos: true
  usar_albumartist_si_falta_artista: true
  compilaciones_va: "{Genero}/{Año}/{Álbum}/VA - {TrackNo - Artista - Título}.{ext}"
```

---

## 🚀 Uso (desarrollo)

1. **Escanear** carpeta y poblar DB:

```bash
python -m songsearch.cli scan --path "/ruta/a/tu/musica"
```

2. **Completar metadatos** con AcoustID/MusicBrainz (solo pistas con tags pobres):

```bash
python -m songsearch.cli enrich --min-confidence 0.6 --write-tags false
```

3. **Simulación de organización** (no mueve nada, solo vista previa y CSV):

```bash
python -m songsearch.cli organize --template default --mode simulate --dest "/ruta/destino"
```

4. **Aplicar organización** (mover/copiar/enlazar):

```bash
python -m songsearch.cli organize --template default --mode move --dest "/ruta/destino"
# o:
python -m songsearch.cli organize --template default --mode copy --dest "/ruta/destino"
python -m songsearch.cli organize --template default --mode link --dest "/ruta/destino"
```

5. **Deshacer** último lote:

```bash
python -m songsearch.cli undo
```

6. **Analizador de espectro**:

```bash
python -m songsearch.cli spectrum --input "/ruta/tema.flac"
python -m songsearch.cli spectrum --input "/ruta/tema.flac" --open-external
```

7. **Carátulas (lote)**:

```bash
python -m songsearch.cli covers --limit 200 --only-missing
```

8. **Duplicados por hash parcial** (más preciso):

```bash
python -m songsearch.cli dupes --use-hash --preview
```

9. **UI** (PySide6):

```bash
python -m songsearch.app
```

---

## 🗄️ Estructura del proyecto

```
songsearch/
  core/
    db.py
    scanner.py
    organizer.py
    duplicates.py
    metadata_enricher.py
    spectrum.py
    jobs.py
    utils.py
  ui/
    app.py
    main_window.py
  cli/
    __init__.py
    main.py
  app/
    __main__.py
config/
  templates.yml
assets/
  icons/
logs/
.env.example
requirements.txt
LICENSE
```

---

## 🔒 Seguridad y reversibilidad

- **Modo simulación** por defecto para revisar antes de mover.
- **Log de operaciones** para revertir con `undo`.
- Protección contra sobrescritura: destinos únicos y papelera opcional.

---

## 📈 Roadmap corto

- v0.1: Organización básica, duplicados, enriquecimiento y UI mínima.
- v0.2: Edición en lote, cache de carátulas, perfiles de exportación.
- v0.3: BPM/Key opcional, listas avanzadas y módulos externos.

---

## 🧪 Comandos de diagnóstico

```bash
python - <<'PY'
import sqlite3, sys
print("SQLite:", sqlite3.sqlite_version)
con = sqlite3.connect(":memory:")
cur = con.cursor()
try:
    cur.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    print("FTS5 OK")
except Exception as e:
    print("FTS5 ERROR:", e)
PY

ffmpeg -version | head -n 1
fpcalc -version
```

---

## 📜 Licencia

Este proyecto se distribuye bajo la licencia [MIT](LICENSE).

