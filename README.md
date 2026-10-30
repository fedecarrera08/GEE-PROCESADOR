# GEE Procesador

![QGIS](https://img.shields.io/badge/QGIS-3.22%2B-589632?style=for-the-badge&logo=qgis) ![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python) ![Google Earth Engine](https://img.shields.io/badge/Google%20Earth%20Engine-Enabled-4285F4?style=for-the-badge&logo=googleearthengine)

Complemento local para QGIS para ejecutar análisis de teledetección y cartografía temática utilizando Google Earth Engine como motor de cálculo. Permite trabajar con índices espectrales, modelos de elevación, coberturas de suelo, composiciones de bandas y exportación de resultados para su uso en el SIG.

## Características principales

- Cálculo de índices satelitales sobre un área definida por polígono.
- Procesamiento de DEM y derivados topográficos.
- Coberturas y clasificaciones de uso de suelo.
- Composición RGB de bandas para visualización satelital.
- Exportación directa a disco o a Google Drive.
- Generación de informes con estadísticas, tablas de clasificación y resultados estructurados.
- Integración opcional con Gemini API para un resumen textual adicional.

## Requisitos del sistema

- QGIS 3.22 o superior.
- Python 3.10+ (según la instalación de QGIS).
- Una cuenta activa de Google Earth Engine.
- Acceso a Internet para consultar Earth Engine y, opcionalmente, Gemini API.
- Una capa vectorial de tipo polígono para definir el área de estudio.

## Instalación

1. Copiar la carpeta del proyecto dentro de la carpeta de plugins de QGIS:

   `C:\Users\TU_USUARIO\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`

2. Iniciar QGIS.
3. Ir a `Complementos → Administrar e instalar complementos → Instalados`.
4. Activar `GEE Procesador`.
5. Si realizaste cambios en el código y no se reflejan, desactiva y vuelve a activar el complemento.

## Estructura del proyecto

| Archivo | Función |
|---|---|
| `__init__.py` | Punto de entrada del plugin. |
| `metadata.txt` | Metadatos del complemento para QGIS. |
| `icon.png` | Ícono del plugin. |
| `gee_procesador.py` | Registro del plugin y apertura de la interfaz. |
| `gee_procesador_dialog.py` | Ventana principal, validaciones y flujo de ejecución. |
| `motor.py` | Lógica de cálculo y conexión con Earth Engine. |
| `datos.py` | Productos, rangos temporales, colores, bandas y configuraciones base. |

## Categorías de análisis

| Categoría | Qué incluye |
|---|---|
| Índices | NDVI, EBBI, NDWI, MSAVI, NDBI, NDMI, NBR, LST, CHIRPS, ERA5 viento |
| DEM | Elevación, pendiente, aspecto, curvatura, TRI, TPI |
| Coberturas | Dynamic World, ESA WorldCover |
| Bandas | Composición RGB para visualización satelital |

## Cómo se usa

1. Abrir el plugin desde QGIS.
2. Seleccionar una capa de polígono como área de estudio.
3. Elegir la categoría y el producto a calcular.
4. Definir rangos temporales y parámetros relevantes como nubosidad o EPSG para DEM.
5. Ejecutar el procesamiento.
6. Revisar el informe del resultado y exportarlo si corresponde.

## Exportación y resultados

El plugin genera resultados en varios formatos:

- ráster georreferenciado para visualizar en QGIS
- tabla de clasificación por clases
- resumen estadístico del raster
- JSON con los resultados estructurados
- salida a Google Drive cuando se selecciona ese modo de exportación

## Gemini API (opcional)

El plugin incluye una integración opcional con Gemini API para generar un resumen textual adicional de los resultados. La clave se guarda localmente en la configuración de QGIS y no viaja con la carpeta del plugin.

Esto no es obligatorio para usar el resto del complemento.

## Limitaciones conocidas

- El procesamiento puede bloquear la interfaz de QGIS mientras se ejecuta en el mismo hilo.
- El motor asume un único polígono por capa.
- No se mezclan satélites en una misma corrida cuando los rangos temporales cruzan distintas fuentes.
- Las exportaciones directas tienen un límite práctico de descarga cuando el área es muy grande.
- La integración con Gemini depende de la clave configurada por el usuario y de la conexión a Internet.

## Mejoras previstas

- Ejecución en segundo plano.
- Mejor manejo de exportación para áreas grandes.
- Extensión de referencias de color para nuevos productos.
- Conservación del resumen generado por Gemini junto con los archivos exportados.

## Historia breve

Este proyecto nació a partir de un script de consola en QGIS que fue evolucionando en módulos para separar la lógica de cálculo, la lógica de configuración y la interfaz gráfica. Con el tiempo quedó estructurado como un complemento más mantenible y fácil de operar desde el entorno de QGIS.

## Licencia

El repositorio no define una licencia explícita en esta versión. Si se desea distribuirlo públicamente o usarlo en entornos profesionales, conviene definir la licencia antes de su difusión.

## Nota final

GEE Procesador está pensado como una herramienta práctica para análisis geoespacial en QGIS con Google Earth Engine como backend. Su objetivo es combinar rapidez, trazabilidad y facilidad de uso en flujos de trabajo de teledetección y análisis territorial.
