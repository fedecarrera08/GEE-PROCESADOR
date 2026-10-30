# GEE Procesador — plugin de QGIS

Complemento local de QGIS para calcular índices satelitales, modelos de elevación (DEM), coberturas de suelo y composiciones de bandas usando Google Earth Engine (GEE) como motor de cálculo. También incluye interpretación automática opcional de resultados con IA (Gemini).

Este proyecto nació a partir de un script de consola de QGIS que se fue separando en módulos para poder reutilizar la lógica y ofrecer una interfaz gráfica más clara y ordenada.

## Qué hace

El plugin permite:

- Calcular índices de vegetación, humedad, agua, urbanización, incendios, temperatura y meteorología.
- Procesar DEM y derivados como pendiente, aspecto, curvatura, TRI y TPI.
- Trabajar con coberturas ya clasificadas (Dynamic World y ESA WorldCover).
- Generar composiciones RGB de bandas crudas para visualización tipo imagen satelital.
- Exportar resultados directamente a disco o a Google Drive.
- Mostrar un informe con resumen, tabla de clasificación, JSON técnico y, si se configura, una interpretación automática generada con Gemini.

## Instalación

1. Copiar la carpeta del plugin (`GEE-PROCESADOR/`) dentro de la carpeta de plugins de QGIS, normalmente:
   `C:\Users\TU_USUARIO\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
2. Abrir QGIS.
3. Ir a: `Complementos → Administrar e instalar complementos → Instalados`.
4. Activar `GEE Procesador`.
5. Si modificaste código y no se refleja, desactivar y volver a activar el complemento para recargarlo.

## Estructura del proyecto

| Archivo | Descripción |
|---|---|
| `__init__.py` | Punto de entrada del plugin; QGIS lo usa para crear la instancia del complemento. |
| `metadata.txt` | Metadatos del plugin: nombre, versión, autor, etiquetas, etc. |
| `icon.png` | Ícono del complemento. |
| `gee_procesador.py` | Registra la acción del plugin en QGIS y abre la ventana principal. |
| `gee_procesador_dialog.py` | Interfaz gráfica principal. Aquí se cargan capas, categorías, fechas, opciones de exportación y se muestra el informe. |
| `motor.py` | Motor de cálculo. Contiene la lógica de acceso a Earth Engine y el procesamiento de cada tipo de producto. |
| `datos.py` | Base de referencia del plugin: productos, rangos temporales, umbrales, colores, presets de bandas y textos. |

Regla general del proyecto:

- `datos.py` = información fija.
- `motor.py` = cálculo real.
- `gee_procesador_dialog.py` = interfaz y validaciones.

## Categorías disponibles

### 1) Índices

Procesa fórmulas sobre bandas satelitales como:

- NDVI
- EBBI
- NDWI
- MSAVI
- NDBI
- NDMI
- NBR
- LST
- CHIRPS
- Viento ERA5

Estos productos usan fecha y, en general, considerar una máxima nubosidad. El resultado se clasifica por umbrales y se presenta en porcentajes por clase.

### 2) DEM

Procesa modelos de elevación y derivados:

- pendiente
- aspecto
- curvatura
- TRI
- TPI

No usan fecha ni nubosidad. Para DEM, el EPSG de reproyección es obligatorio.

### 3) Coberturas

Procesa coberturas ya clasificadas por terceros, por ejemplo:

- Dynamic World
- ESA WorldCover

Estas capas ya traen una clasificación predefinida y no requieren filtrar nubosidad.

### 4) Bandas

Genera composiciones RGB a partir de bandas crudas para visualización satelital, por ejemplo:

- color natural
- falso color vegetación
- agricultura
- SWIR/humedad
- urbano
- geología

Esto no es una clasificación ni un índice, sino una imagen de referencia visual.

## Pestaña “Informe”

Tras ejecutar una tarea con éxito, la pestaña `Informe` se completa con:

- resumen del producto y la capa analizada
- superficie calculada
- tabla de clasificación con color por clase
- JSON completo del resultado generado por el motor
- interpretación automática con IA si hay una clave de Gemini cargada en la pestaña `Clave API`

La clave de Gemini se guarda en la configuración local de QGIS (`QgsSettings`), no dentro del proyecto ni junto con el plugin, por lo que no se comparte con el repositorio.

## Clave API de Gemini

La opción de interpretación automática se activa desde la pestaña `Clave API`.

- La clave se guarda localmente en el perfil de QGIS del usuario.
- No viaja en la carpeta del plugin ni se versiona en Git.
- Se usa para pedir una lectura simple, explicada para usuarios no expertos, basada en estadísticas + ubicación geográfica.

## Limitaciones conocidas

Estas no son errores sino decisiones de diseño del complemento:

- Ejecución bloqueante: mientras corre Earth Engine o Gemini, QGIS puede quedar congelado.
- Un solo polígono por capa: si la capa tiene más de un polígono, el motor falla explícitamente en lugar de procesar solo el primero.
- No se mezclan satélites en una misma corrida: por ejemplo, no se puede combinar Landsat y Sentinel dentro del mismo rango de fechas.
- La referencia de colores cubre los productos clasificados principales; para nuevas incorporaciones, puede requerirse completar la tabla de referencia.
- La interpretación con IA no sustituye la observación de campo ni corregir la calibración de umbrales.
- Earth Engine tiene un límite de descarga directa aproximado de ~48 MB; en áreas grandes el plugin detecta esto y sugiere exportación a Google Drive.

## Mejoras pendientes

- Ejecutar procesos en segundo plano para que QGIS no se congele.
- Completar referencias de colores para nuevos productos o familias.
- Guardar la interpretación de IA dentro del archivo exportado, no solo en la ventana del informe.

## Historia breve

Este plugin nació a partir de un script de consola de QGIS que hacía todo el procesamiento sin interfaz. Con el tiempo, la lógica se separó en `datos.py` y `motor.py`, y después se construyó la interfaz gráfica sobre ese núcleo para dejarlo usable en la práctica.

## Recomendaciones de uso

- Trabajar siempre con una capa de polígono única.
- Elegir un rango de fechas compatible con la fuente satelital del producto.
- Para áreas grandes, usar exportación a Google Drive cuando el cálculo no pueda descargarse directamente.
- Guardar la api key de Gemini solo en la configuración local de QGIS para no compartir credenciales con terceros.

## Licencia

El repositorio no incluye un archivo de licencia explícito en esta versión; si necesitas usarlo en un entorno profesional o compartirlo públicamente, conviene definir una licencia antes de distribuirlo.

## Notas finales

GEE Procesador está pensado como una herramienta local y práctica para análisis geoespacial en QGIS con Google Earth Engine como backend. Su enfoque principal es entregar resultados interpretables y reproducibles, con una capa de control visual y de validación que ayude a evitar decisiones incorrectas por default.

---

Si querés, puedo dejarte además una versión todavía más profesional del README con:

- tabla de productos por categoría
- ejemplos de uso reales
- sección de “requerimientos del sistema”
- badges de estado del proyecto y capturas de pantalla
- una versión orientada a GitHub público

