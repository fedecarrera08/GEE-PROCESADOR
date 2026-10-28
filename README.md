# GEE Procesador — plugin de QGIS

Complemento local de QGIS para calcular índices satelitales, modelos de
elevación (DEM), coberturas de suelo y composiciones de bandas usando
Google Earth Engine (GEE) como motor de cálculo, con interpretación
automática opcional vía IA (Gemini).

Nace de un script de consola (`01_Proyecto_Base.py`) que se fue separando
en piezas para poder tener una interfaz gráfica.

## Cómo instalarlo

1. Copiar toda esta carpeta (`gee_procesador/`) a la carpeta de plugins de
   tu perfil de QGIS:
   `C:\Users\TU_USUARIO\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
2. En QGIS: **Complementos → Administrar e instalar complementos →
   Instalados**, tildar "GEE Procesador".
3. Si hiciste cambios en el código y no se reflejan: destildar y volver a
   tildar el plugin (recarga el código).

## Estructura de archivos

| Archivo | Qué hace |
|---|---|
| `__init__.py` | Punto de entrada que QGIS busca al cargar el plugin (`classFactory`). No tiene lógica propia. |
| `metadata.txt` | Nombre, versión, descripción — lo que ve QGIS en el Administrador de Complementos. |
| `icon.png` | Ícono de la barra de herramientas. |
| `gee_procesador.py` | Registra el ícono/menú en QGIS y abre la ventana (`GeeProcesadorDialog`). |
| `gee_procesador_dialog.py` | La interfaz gráfica completa: todos los campos, validaciones, y la conexión con `motor.py`. |
| `motor.py` | El cálculo real: conexión a Earth Engine, procesamiento de cada producto, exportación, estilos. Contiene la función `ejecutar(config)` (índices/DEM/coberturas) y `generar_composicion_bandas(config)` (bandas crudas, aparte). |
| `datos.py` | Diccionarios de referencia fijos: qué productos existen, sus umbrales de clasificación, colores, reglas de qué satélite corresponde a qué fecha, mensajes de texto. No cambia según lo que el usuario elija en la interfaz. |

**Regla general:** `datos.py` = información fija. `motor.py` = cálculo.
`gee_procesador_dialog.py` = interfaz. Si algo no calcula bien, el
problema está en `motor.py`. Si algo no se ve bien o no valida bien, está
en `gee_procesador_dialog.py`. Si un valor está mal (un umbral, un color,
un rango de fecha), está en `datos.py`.

## Las 4 categorías

- **Índices**: fórmulas sobre bandas (NDVI, EBBI, NDWI, MSAVI, NDBI, NDMI,
  NBR, LST, CHIRPS, viento ERA5). Usan fecha, nubosidad, y se clasifican
  en clases con porcentaje de superficie.
- **DEM**: modelos de elevación y derivados (pendiente, aspecto,
  curvatura, TRI, TPI). No usan fecha ni nubosidad. El EPSG de
  reproyección es obligatorio acá.
- **Coberturas**: mapas ya clasificados por terceros (Dynamic World, ESA
  WorldCover). No usan nubosidad (el filtrado ya viene resuelto en el
  dato). ESA WorldCover tiene fecha fija (2021), no editable.
- **Bandas**: composición RGB de bandas crudas (no un índice), para
  visualización tipo "foto satelital". Usa nubosidad, fecha, y presets
  estándar de la industria (color natural, falso color vegetación,
  agricultura, SWIR/humedad, urbano, geología). Exporta siempre en
  GeoTIFF. No tiene clasificación ni interpretación de IA (no aplica:
  es una imagen de referencia, no una medición).

## La pestaña "Informe"

Después de una ejecución exitosa se completa sola con: resumen
(producto/capa/superficie), tabla de clasificación con color por clase,
el JSON completo de lo que calculó el motor, y — si hay una clave de API
de Gemini cargada en la pestaña "Clave API" — una interpretación en texto
generada por IA, que usa las coordenadas del centro del área para tener
contexto geográfico/climático.

La clave de Gemini se guarda con `QgsSettings` (configuración local de
QGIS, en tu perfil de Windows) — **no** viaja si compartís esta carpeta.

## Limitaciones conocidas (a propósito, no son errores)

- **Ejecución bloqueante**: mientras corre Earth Engine (o Gemini), QGIS
  se congela. Es una decisión consciente, no un bug — ejecutar en segundo
  plano es una mejora posible a futuro, no implementada.
- **Un solo polígono por capa**: si la capa tiene más de un polígono, el
  motor corta con un error explícito en vez de procesar solo el primero
  en silencio.
- **No se pueden mezclar satélites en una sola corrida** (ej. Landsat +
  Sentinel en el mismo rango de fechas) — se descartó por la complejidad
  de calibrar sensores distintos entre sí. El calendario bloquea
  físicamente los rangos que mezclarían fuentes.
- **`REFERENCIAS_COLOR`** (nombre de color por clase) cubre los 11
  productos que tienen clasificación por umbrales. Los productos de
  cobertura (Dynamic World, ESA WorldCover) tienen su propia tabla de
  colores aparte, ya incluida.
- **La interpretación de IA no tiene conocimiento de terreno real** — lee
  números y coordenadas, no reemplaza una visita a campo ni corrige
  umbrales mal calibrados. Es una lectura de apoyo, no una verdad
  absoluta.
- **Earth Engine tiene un límite de ~48 MB para descarga directa** en
  áreas grandes — el plugin lo detecta y sugiere usar exportación a
  Google Drive en ese caso (sin ese límite).

## Ideas pendientes (no implementadas)

- Ejecución en segundo plano (que QGIS no se congele).
- Completar `REFERENCIAS_COLOR` si se agregan productos nuevos.
- Guardar la interpretación de IA en el `.txt`/`.json` exportado, no solo
  mostrarla en pantalla.

## Historial breve

Este plugin viene de un script de consola de QGIS que hacía todo el
procesamiento sin interfaz (`01_Proyecto_Base.py`, guardado como
referencia). Se fue separando en `datos.py` + `motor.py` primero, y
después se le construyó la interfaz gráfica encima, campo por campo,
verificando cada paso antes de sumar el siguiente.
