# Changelog

Todas las novedades relevantes se documentan en este archivo siguiendo un formato inspirado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

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
