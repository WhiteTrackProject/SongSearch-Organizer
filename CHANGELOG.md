# Changelog

Todas las novedades relevantes se documentan en este archivo siguiendo un formato inspirado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [0.3.4] - 2025-11-03
### Corregido
- Plantilla de organización de respaldo en `songsearch/core/organizer.py` para restaurar rutas por defecto sin inconsistencias.
- Mensajes de advertencia ajustados para reflejar correctamente los fallos de respaldo y sus pasos de mitigación.

## [0.3.3] - 2025-10-31
### Añadido
- Módulo `songsearch.ai` con integración del asistente inteligente en la base de código.
- Comandos `chat` y `assistant` en la CLI para conversaciones guiadas y respuestas contextuales.
- Dependencia `openai` y configuración inicial del modelo predeterminado para el asistente.
- Pruebas asociadas que cubren la interacción del módulo de IA y los comandos de la CLI.

### Cambiado
- Manejo centralizado de credenciales, incluyendo la detección y carga de claves para servicios externos.
- Advertencias de la aplicación actualizadas para guiar la configuración de claves y el uso seguro del asistente.

## [0.3.2] - 2025-09-30
### Añadido
- Interfaz principal rediseñada con cabecera estilo macOS, tarjeta de herramientas y distintivo dinámico de resultados.
- Centro de ayuda contextual que muestra atajos clave y el estado actual de dependencias/API.
- Panel de detalles con encabezado destacado y contenedor de acciones con botones tonales.

### Cambiado
- La barra de acciones pasa a ser una toolbar unificada con botones tipo píldora y atajos globales.
- Las leyendas de biblioteca e inspector se actualizan automáticamente con cada selección y búsqueda.

### Corregido
- El botón «MusicBrainz» abre ahora la ficha correspondiente en el navegador predeterminado.

## [0.3.1] - 2025-09-15
### Añadido
- Botonera superior con acciones de **Escanear**, **Enriquecer** y **Espectro**, incluyendo soporte para iconos opcionales en `assets/icons/`.
- Menú contextual en la tabla de Biblioteca con accesos directos para **Abrir**, **Mostrar en carpeta**, **Espectro**, **Enriquecer** y **Copiar ruta**.
- Workflow de GitHub Actions para publicar releases automáticamente al crear un tag `vX.Y.Z`.

### Corregido
- Inicialización del encabezado de búsqueda para evitar referencias a layouts sin construir.

## [0.3.0]
- Publicación inicial del reorganizador de bibliotecas musicales.
