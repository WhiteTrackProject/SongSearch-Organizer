# SongSearch Organizer (v0.3.3)

![Coverage](assets/coverage-badge.svg)

**Organiza tu biblioteca musical** de forma **rápida, segura y reversible**.  
Escanea carpetas, completa metadatos con **MusicBrainz/AcoustID**, detecta duplicados, y **recoloca** archivos en una nueva estructura por **Género/Año/Artista/Álbum**, con **modo simulación** y **deshacer**. Incluye **analizador de espectro** (integrado con `ffmpeg`) y lanzador externo (Spek).

## 📦 Instalación rápida

```bash
pip install songsearch-organizer
# o bien
pipx install songsearch-organizer
# y ejecuta la CLI directamente
songsearch --help
```

Para desarrollo o contribución:

```bash
python -m pip install --upgrade pip
python -m pip install .[dev]
pre-commit install
```

La raíz del repositorio incluye `requirements.lock` generado con `pip-compile`. Ejecuta `pip install -r requirements.lock` si necesitas un entorno idéntico al CI.

---

Consulta [CHANGELOG.md](CHANGELOG.md) para ver la lista completa de cambios entre versiones.

## ✨ Características (MVP v0.3.3)

- **Organizador por plantillas**:  
  `{Genero}/{Año}/{Artista}/{Álbum}/{TrackNo - Título}.{ext}` (personalizable).
- **Modo Simulación**: vista previa `Ruta actual → Nueva ruta` antes de mover/copiar/enlazar.
- **Deshacer**: log de operaciones para revertir en 1 clic.
- **Detección de archivos perdidos** y reubicación por cambio de raíz.
- **Duplicados**: agrupación por `duración±1s+tamaño+formato` + hash parcial opcional, con resolución automática que prioriza formatos sin pérdida, mayor bitrate y duración estable.
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
  - Clic derecho en la tabla para acciones rápidas: **Abrir**, **Mostrar en carpeta**, **Espectrograma**, **Enriquecer**, **Copiar ruta**.
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
pip install -r requirements.lock
# o, para un entorno editable de desarrollo
pip install .[dev]
```

---

## ⚙️ Configuración rápida

Crea `.env` en la raíz con tus claves (AcoustID, OpenAI y MusicBrainz):

```ini
ACOUSTID_API_KEY=tu_api_key_opcional
OPENAI_API_KEY=tu_api_key_de_openai
MUSICBRAINZ_USER_AGENT=SongSearchOrganizer/0.3.3 (tu_email@ejemplo.com)
SPEK_APP_PATH=
```

> ℹ️ `.env` está en `.gitignore`; guarda aquí tus claves sin riesgo de subirlas al repositorio.

## 🧠 Ayuda inteligente

La ayuda inteligente integra un asistente contextual que responde sobre SongSearch Organizer y automatiza consultas frecuentes. Una vez configurado `OPENAI_API_KEY`, puedes utilizar la CLI en modo conversación o con respuestas guiadas:

```bash
# Chat libre con contexto musical
songsearch chat "Necesito ideas para ordenar mis álbumes en FLAC"

# Preguntas directas al asistente experto de SongSearch
songsearch assistant "¿Cómo escribo etiquetas usando el modo enrich?"
```

Ambos comandos usan el modelo `gpt-4o-mini` de OpenAI por defecto. Si prefieres otro modelo compatible, define `OPENAI_MODEL` en tu `.env` (o en tu entorno de ejecución) con el identificador deseado:

```ini
OPENAI_MODEL=gpt-4.1-mini
```

Si omites la variable, el sistema mantendrá el modelo predeterminado.

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

## 🗃️ Caché y escaneo incremental

- **Escaneo inteligente**: los archivos cuyo `mtime` y tamaño no cambian se omiten en escaneos posteriores, acelerando las sincronizaciones grandes.
- **Base de datos local**: la carpeta `~/.songsearch/` almacena `songsearch.db`, registros de deshacer y las miniaturas de carátulas. Puedes respaldarla o eliminarla para empezar de cero.
- **Fingerprint cache**: los resultados de AcoustID/MusicBrainz se guardan en la tabla `fingerprint_cache`, evitando llamadas repetidas cuando vuelves a enriquecer la biblioteca.

---

## 🌐 Buenas prácticas con MusicBrainz/AcoustID

- Identifícate con un `MUSICBRAINZ_USER_AGENT` válido (`App/Versión (contacto)`).
- El cliente aplica **rate limiting** y reintentos con backoff. Si automatizas tareas largas, considera espaciar los lotes (`--limit`) para respetar las políticas de ambas APIs.
- Con la caché integrada, los reintentos solo ocurren cuando no hay resultados almacenados o la confianza es inferior al umbral definido.

---

## 🧑‍🏫 Lanzamiento de la app para principiantes

¿Nunca has lanzado una app de Python? Sigue estos pasos sencillos:

1. **Instala Python 3.13** desde [python.org](https://www.python.org/downloads/) y, durante la instalación en Windows, marca "Add Python to PATH".
2. **Descarga el proyecto**: `git clone https://github.com/tu-usuario/SongSearch-Organizer.git` o baja el ZIP y descomprímelo.
3. **Abre una terminal** (Terminal en macOS/Linux o PowerShell en Windows) y ve a la carpeta del proyecto: `cd SongSearch-Organizer`.
4. **Crea un entorno aislado**: `python -m venv .venv`.
5. **Activa el entorno**:
   - macOS/Linux: `source .venv/bin/activate`
   - Windows: `.venv\Scripts\activate`
6. **Instala la app** dentro del entorno: `pip install .` (o `pip install -r requirements.lock` si quieres replicar el entorno del CI).
7. **Lanza la interfaz gráfica**: `python -m songsearch.app`.
8. **En los próximos usos**, solo repite los pasos 3, 5 y 7 para abrir la app de nuevo.

> Consejos rápidos: Si prefieres la interfaz de línea de comandos, ejecuta `python -m songsearch.cli --help`. Para salir del entorno virtual, usa `deactivate`.

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

8. **Calidad / CI local**:

```bash
ruff format .
ruff check .
mypy songsearch/core
pytest --cov=songsearch --cov-report=xml
```

---

## 🚀 Lanzamientos automáticos

Los lanzamientos en GitHub se generan automáticamente cuando etiquetas una versión.

1. Actualiza la versión en `pyproject.toml`, `songsearch/__init__.py`, `README.md` y añade la entrada correspondiente en `CHANGELOG.md`.
2. Crea un commit con los cambios.
3. Etiqueta el commit con `git tag vX.Y.Z` y publícalo con `git push --tags`.

La acción de GitHub (`.github/workflows/release.yml`) generará la *release* usando el tag y adjuntará los artefactos publicados por el pipeline.

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

Este proyecto se distribuye bajo la licencia [MIT (2025)](LICENSE).
