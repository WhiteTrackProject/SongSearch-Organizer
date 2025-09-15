# SongSearch Organizer (v0.2)

**Organiza tu biblioteca musical** de forma **rápida, segura y reversible**.  
Escanea carpetas, completa metadatos con **MusicBrainz/AcoustID**, detecta duplicados, y **recoloca** archivos en una nueva estructura por **Género/Año/Artista/Álbum**, con **modo simulación** y **deshacer**. Incluye **analizador de espectro** (integrado con `ffmpeg`) y lanzador externo (Spek).

---

## ✨ Características (MVP v0.2)

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

## UI – novedades

* Búsqueda y navegación
  - Filtro incremental sobre título, artista, álbum, género y ruta con ordenación por columnas.
  - Tabla principal limitada a 5000 filas visibles para mantener la respuesta inmediata.
* Carátulas integradas
  - Iconos de 64 px generados desde la caché local (`~/.songsearch`) con recuperación automática de portadas.
  - Tooltips HTML con previsualización ampliada a 256 px al pasar el ratón sobre el título.
* Menú contextual
  - Clic derecho en la tabla para acciones rápidas: **Abrir**, **Mostrar en carpeta**, **Espectrograma**, **Enriquecer**, **Obtener carátula**.
* Flujo de escaneo y progreso
  - Botón «Escanear carpeta…» que abre el selector de directorios y lanza el proceso en un hilo dedicado.
  - Barra de progreso inferior que se activa durante el escaneo para indicar el estado de la tarea.
* Barra de estado
  - Indicadores en tiempo real del número de resultados visibles y la duración de la consulta/escaneo.

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

3) Instala dependencias Python:

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración rápida

Crea `.env` en la raíz con tus claves:

```ini
ACOUSTID_API_KEY=tu_api_key_opcional
MUSICBRAINZ_USER_AGENT=SongSearchOrganizer/0.2 (tu_email@ejemplo.com)
SPEK_APP_PATH=
```

**Plantillas de organización** (`config/templates.yml`):

```yaml
default: "{Genero}/{Año}/{Artista}/{Álbum}/{TrackNo - Título}.{ext}"
alternativas:
  - name: "artista-año-album"
    pattern: "{Artista}/{Año} - {Álbum}/{TrackNo - Título}.{ext}"
  - name: "año-genero-artista"
    pattern: "{Año}/{Genero}/{Artista}/{Título}.{ext}"
  - name: "mb-release"
    pattern: "MB/{ReleaseID}/{TrackNo - Título}.{ext}"
reglas:
  limpiar_nombres: true
  quitar_parentesis_promos: true
  reemplazos_caracteres_prohibidos: true
  usar_albumartist_si_falta_artista: true
  compilaciones_va: "{Genero}/{Año}/{Álbum}/VA - {TrackNo - Artista - Título}.{ext}"
```

**Plantillas incluidas:**

- `default`: estructura clásica `Género/Año/Artista/Álbum`.
- `artista-año-album`: agrupa por artista con subcarpetas por año y álbum.
- `año-genero-artista`: ordena por año → género → artista → título.
- `mb-release`: usa el identificador de lanzamiento de MusicBrainz para crear rutas `MB/{ReleaseID}/{TrackNo - Título}.{ext}`.

**Variables especiales:**

- `{ReleaseID}`: identificador (UUID) del lanzamiento en MusicBrainz, disponible tras enriquecer metadatos.

---

## 🚀 Uso (desarrollo)

1. **Escanear** carpeta y poblar DB:

```bash
python -m songsearch.cli scan --path "/ruta/a/tu/musica"
```

2. **Completar metadatos** con AcoustID/MusicBrainz:

```bash
python -m songsearch.cli enrich --min-confidence 0.6 --write-tags false
```

3. **Simulación de organización**:

```bash
python -m songsearch.cli organize --template default --mode simulate --dest "/ruta/destino"
```

4. **Aplicar organización** (mover/copiar/enlazar):

```bash
python -m songsearch.cli organize --template default --mode move --dest "/ruta/destino"
```

5. **Deshacer** último lote:

```bash
python -m songsearch.cli undo
```

6. **Analizador de espectro**:

```bash
python -m songsearch.cli spectrum --input "/ruta/tema.flac"
```

7. **UI** (PySide6):

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

## 🧪 Comandos de diagnóstico

```bash
python - <<'PY'
import sqlite3
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
