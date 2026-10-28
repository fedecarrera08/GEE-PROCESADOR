# =====================================================
# MOTOR.PY
# Funciones y flujo de procesamiento, extraído tal cual de
# 01_Proyecto_Base_copia.py. La única lógica NUEVA es la
# función ejecutar(config): reemplaza el bloque fijo de
# CONFIGURACIÓN por lectura de un diccionario.
# =====================================================

# =====================================================
# IMPORTACIONES
# =====================================================

# PYTHON
import os
import json
import shutil
import tempfile
import processing # type: ignore
import urllib.request

import math

# ENGINE
import ee # type: ignore
from ee import batch # type: ignore

# QGIS
from qgis.core import ( # type: ignore
    Qgis,
    QgsProject,
    QgsRasterLayer,
    QgsColorRampShader,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsSingleBandGrayRenderer,
    QgsMultiBandColorRenderer,
    QgsContrastEnhancement,
    QgsRasterBandStats,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)

# PYQGt
from qgis.PyQt.QtGui import QColor # type: ignore
from qgis.PyQt.QtWidgets import QFileDialog  # type: ignore

# Utilidades Qgis
from qgis.utils import iface # type: ignore

# GDAL
from osgeo import gdal # type: ignore

import numpy as np

# FECHA
from datetime import datetime

from .datos import *

# =====================================================
# EJECUTAR
# =====================================================

def _mascara_landsat_bandas(imagen):
    """
    Copia exacta de la máscara de nubes que usa ejecutar() para
    Landsat (Fill + Cloud Shadow + alta confianza de nube). Se
    duplica acá porque esta función vive fuera de ejecutar() y no
    puede acceder a las funciones anidadas de adentro.
    """
    qa = imagen.select("QA_PIXEL")
    mascara = (
        qa.bitwiseAnd(1 << 0).eq(0)
        .And(qa.bitwiseAnd(1 << 4).eq(0))
    )
    confianza_nube = qa.rightShift(8).bitwiseAnd(3)
    mascara = mascara.And(confianza_nube.lt(3))
    return imagen.updateMask(mascara)

def _mascara_sentinel_bandas(imagen):
    """
    Copia exacta de la máscara de nubes que usa ejecutar() para
    Sentinel-2 (SCL: sombra + nube media/alta + cirros). Duplicada
    por el mismo motivo que _mascara_landsat_bandas: esta función
    vive fuera de ejecutar() y no puede acceder a las anidadas.
    """
    scl = imagen.select("SCL")
    mascara = (
        scl.neq(3)
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
    )

    return imagen.updateMask(mascara)

def _tono_copernicus(ruta_cruda, fuente):
    dataset = gdal.Open(ruta_cruda)
    crudo = dataset.ReadAsArray().astype("float64")
    invalido = np.any(~np.isfinite(crudo) | (crudo == NODATA), axis=0) | np.all(crudo == 0, axis=0)

    if fuente == "COPERNICUS_S2":
        reflectancia = crudo / 10000.0
    elif fuente in ("LANDSAT_5", "LANDSAT_8", "LANDSAT_9"):
        reflectancia = crudo * 0.0000275 - 0.2
    else:
        reflectancia = crudo / 10000.0

    max_r, mid_r, sat, gamma = 3.0, 0.13, 1.2, 1.8
    g_off = 0.01
    g_off_pow = g_off ** gamma
    g_off_range = (1.0 + g_off) ** gamma - g_off_pow

    ar = np.clip(np.clip(reflectancia, 0, None) / max_r, 0, 1)
    curva = ar * (ar * (mid_r / max_r) - 1) / (ar * (2 * mid_r / max_r - 1) - mid_r / max_r)
    curva = np.clip(curva, 0, None)
    gama = ((curva + g_off) ** gamma - g_off_pow) / g_off_range

    promedio = gama.mean(axis=0)
    gama = np.clip(promedio * (1 - sat) + gama * sat, 0, 1)
    pantalla = np.where(
        gama <= 0.0031308,
        12.92 * gama,
        1.055 * np.power(gama, 1 / 2.4) - 0.055,
    )
    byte = np.clip(np.round(pantalla * 255), 0, 255).astype(np.uint8)

    ruta = ruta_cruda.replace(".tif", "_vista.tif")
    salida = gdal.GetDriverByName("GTiff").Create(
        ruta, dataset.RasterXSize, dataset.RasterYSize, 4, gdal.GDT_Byte,
        options=["COMPRESS=DEFLATE", "PHOTOMETRIC=RGB", "ALPHA=YES"],
    )
    salida.SetGeoTransform(dataset.GetGeoTransform())
    salida.SetProjection(dataset.GetProjection())
    for indice in range(3):
        salida.GetRasterBand(indice + 1).WriteArray(byte[indice])
    salida.GetRasterBand(4).WriteArray(np.where(invalido, 0, 255).astype(np.uint8))
    salida.FlushCache()
    salida = None
    dataset = None
    return ruta


def generar_composicion_bandas(config):

    """
    Arma una composición RGB de 3 bandas crudas (no un índice) sobre
    el área de estudio, y la visualiza/exporta. Es una función aparte
    de ejecutar() a propósito: el resto del motor está pensado para
    un resultado de 1 banda (índice o DEM), y forzar un composite de
    3 bandas en ese mismo camino significaría tocar código ya probado.
    Acá se duplican algunas piezas chicas (máscara Landsat, geometría,
    fuente) para no arriesgar nada de lo existente.
    """

    for clave in ("nombre_capa", "banda_r", "banda_g", "banda_b", "fecha_inicio", "fecha_fin"):
        if not config.get(clave):
            raise Exception(f"Falta el parámetro '{clave}' para generar la composición de bandas.")

    NOMBRE_CAPA = config["nombre_capa"]
    FECHA_INICIO = config["fecha_inicio"]
    FECHA_FIN = config["fecha_fin"]
    NUBOSIDAD_MAXIMA = config.get("nubosidad_maxima", 20)
    RESOLUCION_SENTINEL = config.get("resolucion_sentinel", 10)
    VISUALIZAR = config.get("visualizar", True)
    EXPORTAR = config.get("exportar", False)
    MODO_EXPORTACION = config.get("modo_exportacion", "directo")

    # Detectamos los presets especiales
    es_tolari = config.get("preset_nombre") == "Fusión Tolari (NIR + SWIR)"
    es_green_city = config.get("preset_nombre") == "Green City (Urbano B&N + Vegetación)"

    if es_tolari:
        sufijo_bandas = "TOLARI"
    elif es_green_city:
        sufijo_bandas = "GREEN_CITY"
    else:
        sufijo_bandas = f"{config['banda_r']}_{config['banda_g']}_{config['banda_b']}"

    # --- NUEVO: SISTEMA DE CONTADOR ---
    nombre_base = f"BANDAS_{sufijo_bandas}_{NOMBRE_CAPA}_{FECHA_INICIO[:7].replace('-', '_')}"
    NOMBRE_RESULTADO = nombre_base
    contador = 1
    
    # Mientras exista un archivo con ese nombre en la carpeta temporal, le sumamos 1
    while os.path.exists(os.path.join(tempfile.gettempdir(), f"{NOMBRE_RESULTADO}{EXTENSION_RASTER}")):
        NOMBRE_RESULTADO = f"{nombre_base}_{contador}"
        contador += 1

    # =====================================================
    # CAPA Y GEOMETRÍA (mismo criterio que ejecutar())
    # =====================================================

    capas = QgsProject.instance().mapLayersByName(NOMBRE_CAPA)

    if len(capas) == 0:
        raise Exception(f"La capa '{NOMBRE_CAPA}' no existe en el proyecto.")

    capa = capas[0]

    cantidad_features = capa.featureCount()

    if cantidad_features == 0:
        raise Exception(f"La capa '{NOMBRE_CAPA}' no tiene ningún polígono cargado.")

    if cantidad_features > 1:
        raise Exception(
            f"La capa '{NOMBRE_CAPA}' tiene {cantidad_features} polígonos. "
            "Este motor está pensado para un único polígono de área de estudio."
        )

    feature = next(capa.getFeatures())
    geometria = feature.geometry()

    crs_capa = capa.crs()
    crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")

    if crs_capa != crs_4326:
        transformador = QgsCoordinateTransform(crs_capa, crs_4326, QgsProject.instance())
        geometria.transform(transformador)

    centroide = geometria.centroid().asPoint()

    geojson = json.loads(geometria.asJson())
    roi = ee.Geometry(geojson)

    # =====================================================
    # RESOLVER FUENTE SEGÚN FECHA
    # =====================================================

    fecha_ini_dt = datetime.strptime(FECHA_INICIO, "%Y-%m-%d")
    fecha_fin_dt = datetime.strptime(FECHA_FIN, "%Y-%m-%d")

    fuente_resuelta = None

    for regla in REGLAS_TEMPORALES["BANDAS"]:
        inicio = datetime.strptime(regla["inicio"], "%Y-%m-%d")
        fin = datetime.max if regla["fin"] is None else datetime.strptime(regla["fin"], "%Y-%m-%d")

        if fecha_ini_dt >= inicio and fecha_fin_dt <= fin:
            fuente_resuelta = regla["fuente"]
            break

    if fuente_resuelta is None:
        raise Exception(
            "El rango de fechas elegido no corresponde a una única fuente "
            "satelital disponible para composición de bandas."
        )

    config_fuente = FUENTES[fuente_resuelta]

    if fuente_resuelta == "COPERNICUS_S2":
        config_fuente["resolucion"] = RESOLUCION_SENTINEL

    # =====================================================
    # RESOLVER FUENTE SEGÚN FECHA
    # =====================================================
    # ... (código existente de fecha y fuente)

    bandas_disponibles = config_fuente["bandas"]

    
    # --- INICIO DEL BLOQUE DE VALIDACIÓN ---
    es_tolari = config.get("preset_nombre") == "Fusión Tolari (NIR + SWIR)"
    es_green_city = config.get("preset_nombre") == "Green City (Urbano B&N + Vegetación)"

    if es_tolari or es_green_city:
        codigo_r = codigo_g = codigo_b = "TOLARI" if es_tolari else "GREEN_CITY"
    else:
        # (tu validación normal con el for...)
        for rol, clave_config in (("banda_r", "banda_r"), ("banda_g", "banda_g"), ("banda_b", "banda_b")):
            if config[clave_config] not in bandas_disponibles:
                raise Exception(
                    f"La banda '{config[clave_config]}' no está disponible en {fuente_resuelta}. "
                    f"Disponibles: {', '.join(bandas_disponibles.keys())}"
                )

        codigo_r = bandas_disponibles[config["banda_r"]]
        codigo_g = bandas_disponibles[config["banda_g"]]
        codigo_b = bandas_disponibles[config["banda_b"]]

        # Esta validación de bandas repetidas DEBE estar acá adentro del else
        if len({codigo_r, codigo_g, codigo_b}) < 3:
            raise Exception(
                "Dos o más de las bandas elegidas (R, G, B) apuntan a la misma "
                f"banda cruda de {fuente_resuelta}..."
            )
    # --- FIN DEL BLOQUE DE VALIDACIÓN ---

    # =====================================================
    # ARMAR COLECCIÓN
    # =====================================================

    coleccion = (
        ee.ImageCollection(config_fuente["id"])
        .filterBounds(roi)
        .filterDate(FECHA_INICIO, FECHA_FIN)
        .filter(ee.Filter.lte(config_fuente["nubosidad"], NUBOSIDAD_MAXIMA))
    )

    cantidad = coleccion.size().getInfo()

    if cantidad == 0:
        raise Exception(
            "No se encontraron imágenes para los filtros elegidos.\n"
            "Revisá: rango de fechas, nubosidad máxima, o el área de estudio."
        )

    print(f"Fuente seleccionada: {fuente_resuelta}")
    print(f"Imágenes encontradas: {cantidad}")

    if fuente_resuelta in ("LANDSAT_5", "LANDSAT_8", "LANDSAT_9"):
        coleccion = coleccion.map(_mascara_landsat_bandas)
    if fuente_resuelta in ("LANDSAT_5", "LANDSAT_8", "LANDSAT_9"):
        coleccion = coleccion.map(_mascara_landsat_bandas)
    elif fuente_resuelta == "COPERNICUS_S2":
        if es_tolari:
            banda_swir = bandas_disponibles["SWIR2"]
            coleccion = coleccion.map(
                lambda img: img.addBands(
                    img.select(banda_swir).resample("bilinear"),
                    overwrite=True
                )
            )
        coleccion = coleccion.map(_mascara_sentinel_bandas)
    
    imagen = coleccion.median()

    if es_tolari:
        if fuente_resuelta == "COPERNICUS_S2":
            factor, offset = 0.0001, 0.0
        elif fuente_resuelta in ("LANDSAT_5", "LANDSAT_8", "LANDSAT_9"):
            factor, offset = 0.0000275, -0.2
        else:
            factor, offset = 0.0001, 0.0

        peso = 3.5

        def a_refl(banda):
            return banda.multiply(factor).add(offset)

        def a_dn(banda):
            return banda.subtract(offset).divide(factor)

        nir = a_refl(imagen.select(bandas_disponibles["NIR"]))
        red = a_refl(imagen.select(bandas_disponibles["RED"]))
        green = a_refl(imagen.select(bandas_disponibles["GREEN"]))
        blue = a_refl(imagen.select(bandas_disponibles["BLUE"]))
        swir = a_refl(imagen.select(bandas_disponibles["SWIR2"]))

        def fusion(visible):
            return a_dn(
                nir.multiply(0.3).add(visible.multiply(peso)).add(swir.multiply(0.3)).divide(peso)
            )

        r_calc = fusion(red).rename("R")
        g_calc = fusion(green).rename("G")
        b_calc = fusion(blue).rename("B")

        resultado = ee.Image([r_calc, g_calc, b_calc]).clip(roi).toFloat()

    elif es_green_city:
        b_nir = imagen.select(bandas_disponibles["NIR"])
        b_red = imagen.select(bandas_disponibles["RED"])
        b_green = imagen.select(bandas_disponibles["GREEN"])
        b_blue = imagen.select(bandas_disponibles["BLUE"])
        
        # --- NUEVO: Escalado para que el NDVI sea real en Landsat ---
        factor = config_fuente.get("factor_escala", 1)
        offset = config_fuente.get("offset", 0)
        
        nir_real = b_nir.multiply(factor).add(offset)
        red_real = b_red.multiply(factor).add(offset)
        
        # 1. Calculamos NDVI con valores de reflectancia reales y aplicamos la máscara
        ndvi = nir_real.subtract(red_real).divide(nir_real.add(red_real))
        mascara_veg = ndvi.gt(0.4)
        # ------------------------------------------------------------
        
        # 2. Generamos el fondo Blanco y Negro (Fórmula estándar de Luminancia)
        y = b_red.multiply(0.299).add(b_green.multiply(0.587)).add(b_blue.multiply(0.114))
        
        # 3. Aplicamos: Si es vegetación, asignamos NIR a G (brilla mucho) y apagamos R/B. 
        # Si es ciudad, los 3 canales quedan iguales a la Luminancia (gris).
        r_calc = y.where(mascara_veg, y.multiply(0.2)).rename("R")
        g_calc = y.where(mascara_veg, b_nir).rename("G")
        b_calc = y.where(mascara_veg, y.multiply(0.2)).rename("B")

        resultado = ee.Image([r_calc, g_calc, b_calc]).clip(roi).toFloat()
        
    else:
        resultado = imagen.select([codigo_r, codigo_g, codigo_b]).clip(roi).toFloat()

    # =====================================================
    # DESCARGAR
    # =====================================================

    resultado_descarga = resultado.unmask(NODATA, False)

    url = resultado_descarga.getDownloadURL({
        "scale": config_fuente["resolucion"],
        "region": roi,
        "format": "GEO_TIFF",
    })

    archivo_temporal = os.path.join(
        tempfile.gettempdir(),
        f"{NOMBRE_RESULTADO}.tif"
    )

    for ext in [".tif", ".tif.aux.xml"]:
        ruta_cache = os.path.join(tempfile.gettempdir(), f"{NOMBRE_RESULTADO}{ext}")
        if os.path.exists(ruta_cache):
            try:
                os.remove(ruta_cache)
            except Exception:
                pass

    urllib.request.urlretrieve(url, archivo_temporal)

    ds = gdal.Open(archivo_temporal, gdal.GA_Update)
    if ds is not None:
        for i in range(1, 4):
            ds.GetRasterBand(i).SetNoDataValue(NODATA)
        ds.FlushCache()
        ds = None
    # =====================================================
    # CARGAR EN QGIS + ESTILO (Idéntico a Copernicus Browser)
    # =====================================================

    capa_resultado = QgsRasterLayer(archivo_temporal, NOMBRE_RESULTADO)

    es_color_natural = (
        not es_green_city
        and not es_tolari
        and (
            config.get("banda_r") == "RED"
            and config.get("banda_g") == "GREEN"
            and config.get("banda_b") == "BLUE"
        )
    )

    archivo_vista = None
    if es_color_natural:
        archivo_vista = _tono_copernicus(archivo_temporal, fuente_resuelta)
        ruta_a_cargar = archivo_vista
    else:
        ruta_a_cargar = archivo_temporal

    capa_resultado = QgsRasterLayer(ruta_a_cargar, NOMBRE_RESULTADO)

    if not capa_resultado.isValid():
        raise Exception("No se pudo cargar el raster de bandas en QGIS.")

    QgsProject.instance().addMapLayer(capa_resultado)

    renderer = QgsMultiBandColorRenderer(
        capa_resultado.dataProvider(), 1, 2, 3
    )

    if es_color_natural and capa_resultado.dataProvider().bandCount() >= 4:
        renderer.setAlphaBand(4)

    provider = capa_resultado.dataProvider()

    if not es_color_natural:
        for i in (1, 2, 3):
            provider.setNoDataValue(i, float(NODATA))

    if es_color_natural:
        min_valor = 0.0
        max_valor = 255.0
    elif es_tolari:
        max_refl = 1.0 / 3.5   # equivale al recorte en 1 del script oficial
        if fuente_resuelta == "COPERNICUS_S2":
            min_valor = 0.0
            max_valor = max_refl / 0.0001               # ~2857
        else:
            min_valor = 0.2 / 0.0000275                 # ~7273
            max_valor = (max_refl + 0.2) / 0.0000275    # ~17662
    elif fuente_resuelta == "COPERNICUS_S2":
        min_valor = 0.0
        max_valor = 4000.0
    elif fuente_resuelta in ("LANDSAT_5", "LANDSAT_8", "LANDSAT_9"):
        min_valor = 7273.0
        max_valor = 21818.0
    else:
        min_valor = 0.0
        max_valor = 4000.0

    # Aplicamos el mismo rango fijo a los 3 cañones (R, G, B)
    for indice_banda, setter in (
        (1, renderer.setRedContrastEnhancement),
        (2, renderer.setGreenContrastEnhancement),
        (3, renderer.setBlueContrastEnhancement),
    ):
        contraste = QgsContrastEnhancement(provider.dataType(indice_banda))
        contraste.setContrastEnhancementAlgorithm(
            QgsContrastEnhancement.StretchToMinimumMaximum, True
        )
        contraste.setMinimumValue(min_valor)
        contraste.setMaximumValue(max_valor)
        setter(contraste)

    capa_resultado.setRenderer(renderer)
    capa_resultado.triggerRepaint()
    iface.layerTreeView().refreshLayerSymbology(capa_resultado.id())

    # =====================================================
    # EXPORTAR (opcional)
    # =====================================================


    if EXPORTAR and MODO_EXPORTACION == "directo":

        carpeta_destino = QFileDialog.getExistingDirectory(
            None, "Seleccione la carpeta de exportación"
        )

        if not carpeta_destino:
            raise Exception("Exportación cancelada por el usuario.")

        ruta_exportacion = os.path.join(carpeta_destino, NOMBRE_RESULTADO)
        os.makedirs(ruta_exportacion, exist_ok=True)

        # 1. Guardamos el .TIF crudo original
        ruta_raster = os.path.join(ruta_exportacion, f"{NOMBRE_RESULTADO}.tif")
        shutil.copy2(archivo_temporal, ruta_raster)

        # 2. Guardamos el archivo de estilo .QML con el mismo nombre
        # (Al arrastrar el .tif a cualquier QGIS, carga el color solo)
        ruta_estilo = os.path.join(ruta_exportacion, f"{NOMBRE_RESULTADO}.qml")
        capa_resultado.saveNamedStyle(ruta_estilo)

        # 3. Generamos la IMAGEN VISUAL directa (GeoTIFF RGB 8-bits)
        # Se abre con doble clic en Windows/Word y mantiene las coordenadas
        ruta_imagen_rgb = os.path.join(ruta_exportacion, f"{NOMBRE_RESULTADO}_visual.tif")
        if archivo_vista:
            shutil.copy2(archivo_vista, ruta_imagen_rgb)
        else:
            gdal.Translate(
                ruta_imagen_rgb,
                archivo_temporal,
                outputType=gdal.GDT_Byte,
                scaleParams=[[min_valor, max_valor, 0, 255]],
                noData=0,
                creationOptions=["COMPRESS=DEFLATE"]
            )

        # (Opcional) Si además querés un archivo .PNG común con su georreferencia:
        # ruta_png = os.path.join(ruta_exportacion, f"{NOMBRE_RESULTADO}.png")
        # gdal.Translate(
        #     ruta_png,
        #     archivo_temporal,
        #     format="PNG",
        #     outputType=gdal.GDT_Byte,
        #     scaleParams=[[min_valor, max_valor, 0, 255]]
        # )

        print(f"Exportado correctamente a: {ruta_exportacion}")

    elif EXPORTAR and MODO_EXPORTACION == "drive":

        # 1. Ráster crudo a Google Drive
        tarea_cruda = batch.Export.image.toDrive(
            image=resultado,
            description=NOMBRE_RESULTADO,
            folder="EarthEngine",
            fileNamePrefix=NOMBRE_RESULTADO,
            region=roi,
            scale=config_fuente["resolucion"],
            maxPixels=1e13
        )
        tarea_cruda.start()
        print(f"Tarea a Drive (crudo) iniciada: {NOMBRE_RESULTADO}")

        # 2. Imagen visual RGB de 8 bits a Google Drive (solo 3 bandas, sin Alfa)
        bandas_vis = ["R", "G", "B"] if (es_tolari or es_green_city) else [codigo_r, codigo_g, codigo_b]

        if es_tolari:
            if fuente_resuelta == "COPERNICUS_S2":
                vis_min, vis_max = 0, (1.0 / 3.5) / 0.0001
            else:
                vis_min, vis_max = 0.2 / 0.0000275, ((1.0 / 3.5) + 0.2) / 0.0000275
        elif fuente_resuelta == "COPERNICUS_S2":
            vis_min, vis_max = 0, 4000
        else:
            vis_min, vis_max = 7273, 21818

        resultado_visual = resultado.visualize(
            bands=bandas_vis,
            min=vis_min,
            max=vis_max,
        ).select(["vis-red", "vis-green", "vis-blue"])

        tarea_visual = batch.Export.image.toDrive(
            image=resultado_visual,
            description=f"{NOMBRE_RESULTADO}_visual",
            folder="EarthEngine",
            fileNamePrefix=f"{NOMBRE_RESULTADO}_visual",
            region=roi,
            scale=config_fuente["resolucion"],
            maxPixels=1e13
        )
        tarea_visual.start()
        print(f"Tarea a Drive (visual RGB) iniciada: {NOMBRE_RESULTADO}_visual")

        # 3. Guardar el .qml localmente (opcional)
        carpeta_local = QFileDialog.getExistingDirectory(
            None, "Seleccione carpeta local para guardar el archivo .qml (o cancele para omitir)"
        )
        if carpeta_local:
            ruta_estilo = os.path.join(carpeta_local, f"{NOMBRE_RESULTADO}.qml")
            capa_resultado.saveNamedStyle(ruta_estilo)
            print(f"Estilo .qml guardado en: {ruta_estilo}")

    print()
    print("=" * 40)
    print("Composición de bandas lista.")

    return {
        "producto": f"Bandas ({fuente_resuelta})",
        "nombre_capa": NOMBRE_CAPA,
        "centroide_lat": centroide.y(),
        "centroide_lon": centroide.x(),
        "resultados": {
            "estadisticas": {},
            "clasificacion_detallada": {},
        },
    }


def ejecutar(config):
    """
    Corre el motor completo (GEE + QGIS) con los parámetros
    indicados en 'config'. Mismo comportamiento que el script
    original, ahora parametrizado.
    """

    # =====================================================
    # CONFIGURACIÓN (viene del diccionario 'config', mismos
    # valores por defecto que tenía el script original)
    # =====================================================

    # --- Obligatorios: sin default, el usuario tiene que elegirlos ---
    if not config.get("nombre_capa"):
        raise Exception(
            "Falta elegir la capa de área de estudio (nombre_capa). "
            "No hay un valor por defecto: seleccioná una capa antes de correr el motor."
        )

    if not config.get("producto"):
        raise Exception(
            "Falta elegir el producto a calcular (producto), por ejemplo "
            "'EBBI', 'NDVI', 'DEM'. No hay un valor por defecto."
        )

    NOMBRE_CAPA = config["nombre_capa"]

    FECHA_INICIO = config.get("fecha_inicio", "2015-01-01")
    FECHA_FIN = config.get("fecha_fin", "2015-12-31")

    PRODUCTO = config["producto"]

    EPSG_DESTINO = config.get("epsg_destino", None)
    # Ejemplo:
    # EPSG_DESTINO = "EPSG:5345"

    NUBOSIDAD_MAXIMA = config.get("nubosidad_maxima", 10)

    RESOLUCION_SENTINEL = config.get("resolucion_sentinel", 10)
    # 10 = resolución nativa
    # 30 = comparar con Landsat

    VISUALIZAR = config.get("visualizar", True)

    EXPORTAR = config.get("exportar", False)
    MODO_EXPORTACION = config.get("modo_exportacion", "directo")

    MODO_DEBUG = config.get("modo_debug", True)

    CALCULAR_ESTADISTICAS = config.get("calcular_estadisticas", True)

    # --- NUEVO: SISTEMA DE CONTADOR ---
    nombre_base = f"{PRODUCTO}_{NOMBRE_CAPA}_{FECHA_INICIO[:7].replace('-', '_')}"
    NOMBRE_RESULTADO = nombre_base
    contador = 1
    
    # Mientras exista un archivo con ese nombre en la carpeta temporal, le sumamos 1
    while os.path.exists(os.path.join(tempfile.gettempdir(), f"{NOMBRE_RESULTADO}{EXTENSION_RASTER}")):
        NOMBRE_RESULTADO = f"{nombre_base}_{contador}"
        contador += 1

    # Sincronizamos la resolución elegida por el usuario con el
    # diccionario de fuentes (RESOLUCION_SENTINEL vive en datos.py
    # con un valor por defecto, acá lo pisamos con el real de la corrida)
    FUENTES["COPERNICUS_S2"]["resolucion"] = RESOLUCION_SENTINEL

    # =====================================================
    # FUNCIONES DEL MOTOR
    # =====================================================

    # =====================================================
    # UTILIDADES
    # =====================================================

    def mensaje(clave):

        print(MENSAJES[clave])

    # =====================================================
    # DEPURAR RASTER (RESCATADO)
    # =====================================================

    def depurar_raster(ruta_raster):

        ds = gdal.Open(ruta_raster, gdal.GA_Update)

        if ds is None:
            return

        banda = ds.GetRasterBand(1)
        array = banda.ReadAsArray()

        # 1. Buscar cualquier valor infinito (inf o -inf) o NaN
        mascara_invalidos = ~np.isfinite(array)

        # 2. Reemplazarlos por nuestra constante global (-9999)
        if np.any(mascara_invalidos):
            array[mascara_invalidos] = NODATA
            banda.WriteArray(array)

        # 3. Sellar el archivo con el NoData oficial
        banda.SetNoDataValue(NODATA)
        banda.FlushCache()
        ds = None

    # =====================================================
    # MÁSCARA LANDSAT COLLECTION 2 LEVEL 2 
    # =====================================================

    def aplicar_mascara_landsat(imagen):
        qa = imagen.select("QA_PIXEL")
        # Bits binarios: Fill y Cloud Shadow los sacamos siempre
        mascara = (
            qa.bitwiseAnd(1 << 0).eq(0)         # Fill
            .And(qa.bitwiseAnd(1 << 4).eq(0))   # Cloud Shadow
        )
        # Cloud Confidence: bits 8-9 (0=None, 1=Low, 2=Medium, 3=High)
        # Solo enmascaramos donde la confianza es ALTA (3), para evitar
        # falsos positivos de CFMask sobre techos/concreto/asfalto claro
        confianza_nube = qa.rightShift(8).bitwiseAnd(3)
        mascara = mascara.And(confianza_nube.lt(3))
        return imagen.updateMask(mascara)

    # =====================================================
    # [NUEVO] MÁSCARA DE NUBES SENTINEL-2 (SCL)
    # Filtra a nivel píxel, no solo a nivel escena. Antes, Sentinel
    # solo se apoyaba en CLOUDY_PIXEL_PERCENTAGE (metadato de toda
    # la escena) — una imagen con 8% de nubosidad total podía tener
    # esas nubes justo encima del área de estudio, sin filtrar nada.
    # =====================================================

    def aplicar_mascara_sentinel(imagen):
        scl = imagen.select("SCL")
        # SCL: 3 = Sombra de nube, 8 = Nube prob. media,
        # 9 = Nube prob. alta, 10 = Cirros
        mascara = (
            scl.neq(3)
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
        )
        return imagen.updateMask(mascara)

    # =====================================================
    # PROPIEDADES INFORME
    # =====================================================

    def escribir(texto):

        print(texto)

        INFORME.append(str(texto))

    # =====================================================
    # RANGO VISUAL AUTOMÁTICO
    # =====================================================

    def obtener_rango_visual(capa):

        provider = capa.dataProvider()

        stats = provider.bandStatistics(
            1,
            QgsRasterBandStats.All
        )

        media = stats.mean
        desvio = stats.stdDev

        return (
            media - (3 * desvio),
            media + (3 * desvio)
        )

    # =====================================================
    # APLICAR ESTILO
    # =====================================================

    def aplicar_estilo(capa):

        mensaje("aplicando_estilo")

        # Variables locales, ya no son globales
        minimo_visual = 0
        maximo_visual = 0
        renderer_final = None

        if TIPO_ESTILO == "pseudocolor":

            usa_rango_automatico = PRODUCTOS[PRODUCTO].get("rango_automatico", False)

            if usa_rango_automatico:
                minimo_visual, maximo_visual = obtener_rango_visual(capa)
            elif "min" in ESTILO:
                minimo_visual = ESTILO["min"]
                maximo_visual = ESTILO["max"]
            else:
                minimo_visual, maximo_visual = obtener_rango_visual(capa)

            shader = QgsColorRampShader()
            shader.setColorRampType(QgsColorRampShader.Interpolated)

            items = []
            cantidad_colores = len(COLORES)

            if cantidad_colores < 2:
                raise Exception("La rampa debe tener al menos dos colores.")

            paso = (maximo_visual - minimo_visual) / (cantidad_colores - 1)

            for i, item in enumerate(COLORES):
                if isinstance(item, tuple):
                    valor, color = item
                else:
                    color = item
                    valor = minimo_visual + (i * paso)

                items.append(
                    QgsColorRampShader.ColorRampItem(valor, QColor(color))
                )

            shader.setColorRampItemList(items)
            shader.setMinimumValue(minimo_visual)
            shader.setMaximumValue(maximo_visual)

            raster_shader = QgsRasterShader()
            raster_shader.setRasterShaderFunction(shader)

            renderer_final = QgsSingleBandPseudoColorRenderer(
                capa.dataProvider(),
                1,
                raster_shader
            )

            capa.setRenderer(renderer_final)

            # Seteamos el mínimo/máximo DESPUÉS de pegar el renderer a
            # la capa (no antes) — QGIS a veces clona el renderer al
            # asignarlo con setRenderer(), y si seteamos estos valores
            # en el objeto de antes, quedan en un clon que se descarta,
            # no en el que realmente termina guardándose. Por eso salía
            # "NaN" en el rango del panel de Capas al reabrir el
            # proyecto, aunque los colores se vieran bien (esos sí
            # viajan con la rampa, que no tiene este problema).
            capa.renderer().setClassificationMin(minimo_visual)
            capa.renderer().setClassificationMax(maximo_visual)

        elif TIPO_ESTILO == "singlebandgray":

            renderer_final = QgsSingleBandGrayRenderer(
                capa.dataProvider(),
                1
            )
            capa.setRenderer(renderer_final)

        else:
            raise Exception(f"Tipo de estilo '{TIPO_ESTILO}' no implementado.")

        # =====================================================
        # APLICAR CONTRASTE
        # =====================================================

        if CONTRASTE and renderer_final:

            provider = capa.dataProvider()

            lower, upper = provider.cumulativeCut(
                1,
                MIN_CONTRASTE / 100,
                MAX_CONTRASTE / 100
            )
            contrast = QgsContrastEnhancement(provider.dataType(1))

            contrast.setContrastEnhancementAlgorithm(
                QgsContrastEnhancement.StretchToMinimumMaximum,
                True
            )

            contrast.setMinimumValue(lower)
            contrast.setMaximumValue(upper)

            # Mismo motivo que arriba: tocamos capa.renderer() (el
            # objeto real ya pegado a la capa), no la variable local
            # renderer_final, por si setRenderer() lo clonó por dentro.
            capa.renderer().setContrastEnhancement(contrast)

        capa.triggerRepaint()
        iface.layerTreeView().refreshLayerSymbology(capa.id())

    # =====================================================
    # EXPORTAR DIRECTO
    # =====================================================

    def exportar_directo(capa_temporal, archivo_temp, nombre_base):

        # =====================================================
        # SELECCIONAR CARPETA
        # =====================================================

        carpeta_destino = QFileDialog.getExistingDirectory(
            None,
            "Seleccione la carpeta de exportación"
        )

        if not carpeta_destino:
            raise Exception("Exportación cancelada por el usuario.")

        # =====================================================
        # CREAR CARPETA DEL PROYECTO
        # =====================================================

        ruta_exportacion = os.path.join(carpeta_destino, nombre_base)
        os.makedirs(ruta_exportacion, exist_ok=True)

        # =====================================================
        # EXPORTAR RASTER
        # =====================================================

        ruta_raster = os.path.join(
            ruta_exportacion,
            f"{nombre_base}{EXTENSION_RASTER}"
        )
        shutil.copy2(archivo_temp, ruta_raster)

        # Guardamos el estilo de la capa temporal ANTES de borrarla del
        # proyecto — si lo leyéramos después de removeMapLayer(), QGIS
        # puede haber destruido ya el objeto y tirar un error.
        renderer_temporal = capa_temporal.renderer()
        renderer_ya_confirmado = renderer_temporal.clone()

        # El .clone() de QGIS no siempre copia bien classificationMin/Max
        # (son propiedades aparte del resto del estilo) — guardamos los
        # valores reales acá, para reaplicarlos después del clonado, en
        # vez de confiar en que el clon los haya traído solo. Con
        # hasattr nos cuidamos de capas sin pseudocolor (ej. DEM_RELIEVE,
        # que usa escala de grises y no tiene este concepto).
        clasificacion_min = clasificacion_max = None
        if hasattr(renderer_temporal, "classificationMin"):
            clasificacion_min = renderer_temporal.classificationMin()
            clasificacion_max = renderer_temporal.classificationMax()

        # =====================================================
        # REEMPLAZAR CAPA TEMPORAL
        # =====================================================
        QgsProject.instance().removeMapLayer(capa_temporal.id())

        nueva_capa = QgsRasterLayer(ruta_raster, nombre_base)

        if not nueva_capa.isValid():
            raise Exception("No se pudo cargar el raster exportado.")

        QgsProject.instance().addMapLayer(nueva_capa)

        # Mismo parche que se aplica a la capa de "Visualizar" — acá
        # hacía falta de nuevo, porque esta es una capa NUEVA, armada
        # desde el archivo copiado, que nunca pasó por ese parche.
        provider_nueva_capa = nueva_capa.dataProvider()
        valor_nodata_export = 0 if PRODUCTO == "DEM_RELIEVE" else NODATA
        provider_nueva_capa.setNoDataValue(1, float(valor_nodata_export))

        # En vez de recalcular el contraste de cero acá (que dio un
        # resultado distinto al de "Visualizar" — mismo archivo, mismo
        # NODATA, pero otro rango de estiramiento), copiamos DIRECTO el
        # estilo que ya sabemos que salió bien en la capa temporal.
        # Así garantizamos que se vean exactamente igual, en vez de
        # confiar en que el recálculo dé lo mismo dos veces.
        nueva_capa.setRenderer(renderer_ya_confirmado)

        # Reaplicamos acá lo que el clon pudo no haber traído (ver
        # comentario más arriba, donde se capturan estos valores).
        if clasificacion_min is not None:
            nueva_capa.renderer().setClassificationMin(clasificacion_min)
            nueva_capa.renderer().setClassificationMax(clasificacion_max)

        nueva_capa.triggerRepaint()

        if MODO_DEBUG:
            print("Raster exportado cargado.")
            print("Capa temporal eliminada.")
            print(ruta_exportacion)
            print(ruta_raster)

        return nueva_capa, ruta_exportacion

    # =====================================================
    # EXPORTAR DRIVE
    # =====================================================

    def exportar_drive():

        escribir("")
        escribir("=" * 40)
        escribir("EXPORTACIÓN DRIVE")
        escribir("=" * 40)

        escribir("Preparando tarea de exportación...")

        tarea = batch.Export.image.toDrive(
            image=resultado,
            description=NOMBRE_RESULTADO,
            folder="EarthEngine",
            fileNamePrefix=NOMBRE_RESULTADO,
            region=roi,
            scale=RESOLUCION,
            maxPixels=1e13 # Límite máximo permitido para exportaciones grandes
        )

        tarea.start()

        if MODO_DEBUG:

            estado = tarea.status()

            print()
            print("=" * 40)
            print("ESTADO DE LA TAREA")
            print("=" * 40)

            print(f"Estado : {estado['state']}")
            print(f"Nombre : {estado['description']}")
            print(f"ID     : {estado['id']}")

    # =====================================================
    # [NUEVO] ESTADÍSTICAS SERVER-SIDE (MODO DRIVE, NDVI)
    # No leen ningún archivo local — reduceRegion() corre en
    # los servidores de Earth Engine, sobre la misma imagen
    # 'resultado' que se manda a exportar.
    # =====================================================

    MAX_PIXELES_REDUCCION = 5e7  # margen amplio sobre el default de 10M

    def calcular_estadisticas_ee(resultado_ee, roi_ee, escala):

        reductor = (
            ee.Reducer.minMax()
            .combine(ee.Reducer.mean(), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True)
        )

        stats = resultado_ee.reduceRegion(
            reducer=reductor,
            geometry=roi_ee,
            scale=escala,
            maxPixels=MAX_PIXELES_REDUCCION,
            bestEffort=True,
            tileScale=4,
        ).getInfo()

        prefijo = PRODUCTO

        return {
            "minimo": stats.get(f"{prefijo}_min", 0.0),
            "maximo": stats.get(f"{prefijo}_max", 0.0),
            "media": stats.get(f"{prefijo}_mean", 0.0),
            "desvio": stats.get(f"{prefijo}_stdDev", 0.0),
            "pixeles": int(stats.get(f"{prefijo}_count", 0)),
        }

    def calcular_porcentajes_ee(resultado_ee, roi_ee, escala, superficie_m2_total):

        if PRODUCTO not in CLASIFICACIONES:
            return {}, {}

        clases = CLASIFICACIONES[PRODUCTO]

        codigo_img = ee.Image(-1)

        for i, (minimo, maximo, _nombre) in enumerate(clases):
            es_ultima = (i == len(clases) - 1)
            if es_ultima:
                mascara = resultado_ee.gte(minimo).And(resultado_ee.lte(maximo))
            else:
                mascara = resultado_ee.gte(minimo).And(resultado_ee.lt(maximo))
            codigo_img = codigo_img.where(mascara, i)

        area_por_clase = ee.Image.pixelArea().addBands(codigo_img.rename("clase"))

        agrupado = area_por_clase.reduceRegion(
            reducer=ee.Reducer.sum().group(groupField=1, groupName="clase"),
            geometry=roi_ee,
            scale=escala,
            maxPixels=MAX_PIXELES_REDUCCION,
            bestEffort=True,
            tileScale=4,
        ).getInfo()

        resultado_clases = {nombre: 0 for _, _, nombre in clases}
        porcentajes = {}
        colores_producto = REFERENCIAS_COLOR.get(PRODUCTO, {})

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN")
        escribir("=" * 40)

        for grupo in agrupado.get("groups", []):
            indice_clase = int(grupo["clase"])
            if indice_clase < 0 or indice_clase >= len(clases):
                continue

            _, _, nombre = clases[indice_clase]
            area_m2 = grupo["sum"]
            resultado_clases[nombre] = area_m2

            porcentaje = (area_m2 / superficie_m2_total) * 100 if superficie_m2_total else 0
            porcentajes[nombre] = porcentaje

            color_texto = colores_producto.get(nombre, "")
            etiqueta_color = f"  [ {color_texto} ]" if color_texto else ""

            escribir(f"{nombre:<25}{porcentaje:>6.2f} %{etiqueta_color}")

        return resultado_clases, porcentajes

    def generar_qml_independiente(ruta_qml):

        ruta_dummy = os.path.join(tempfile.gettempdir(), f"_dummy_estilo_{PRODUCTO}.tif")

        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(ruta_dummy, 1, 1, 1, gdal.GDT_Float32)
        ds.GetRasterBand(1).SetNoDataValue(float(NODATA))
        ds.GetRasterBand(1).WriteArray(np.array([[0.0]], dtype=np.float32))
        ds = None

        capa_dummy = QgsRasterLayer(ruta_dummy, "dummy_estilo")

        if not capa_dummy.isValid():
            raise Exception("No se pudo crear el raster auxiliar para el estilo.")

        aplicar_estilo(capa_dummy)
        capa_dummy.saveNamedStyle(ruta_qml)

        try:
            os.remove(ruta_dummy)
            os.remove(ruta_dummy + ".aux.xml")
        except Exception:
            pass

    def ejecutar_modo_drive(resultado_ee, roi_ee):

        estadisticas = calcular_estadisticas_ee(resultado_ee, roi_ee, RESOLUCION)
        superficie = obtener_superficie_area()

        imprimir_encabezado_estadistico(
            estadisticas,
            estadisticas["pixeles"],
            superficie["ha"],
            superficie["km2"],
            CANTIDAD_IMAGENES,
        )

        _, porcentajes = calcular_porcentajes_ee(
            resultado_ee, roi_ee, RESOLUCION, superficie["m2"]
        )

        # Igual que en modo directo: SIN el filtro de CLASIFICACIONES,
        # porque interpretar_indice() también cubre METEOROLOGIA (LST,
        # viento), que interpreta por estadísticas, no por porcentajes.
        interpretacion = interpretar_indice(
            PRODUCTO,
            porcentajes,
            estadisticas
        )

        imprimir_informe_indice(
            PRODUCTO,
            interpretacion
        )

        tarea = batch.Export.image.toDrive(
            image=resultado_ee,
            description=NOMBRE_RESULTADO,
            folder="EarthEngine",
            fileNamePrefix=NOMBRE_RESULTADO,
            region=roi_ee,
            scale=RESOLUCION,
            maxPixels=1e13,
        )
        tarea.start()
        estado_tarea = tarea.status()

        escribir("")
        escribir("=" * 40)
        escribir("ARCHIVO RÁSTER — EXPORTACIÓN A GOOGLE DRIVE")
        escribir("=" * 40)
        escribir("Este informe NO incluye el archivo GeoTIFF de resolución completa.")
        escribir("Se está generando en segundo plano y va a aparecer en tu Google")
        escribir("Drive (no en esta computadora) cuando la tarea termine.")
        escribir("Carpeta en Drive : EarthEngine")
        escribir(f"Nombre de archivo: {NOMBRE_RESULTADO}{EXTENSION_RASTER}")
        escribir(f"ID de la tarea   : {estado_tarea.get('id', '(desconocido)')}")
        escribir(f"Estado al enviar : {estado_tarea.get('state', '(desconocido)')}")

        # =====================================================
        # RESULTADOS ESTRUCTURADOS — misma forma que en modo
        # directo, para que la interfaz (y Gemini) reciban lo
        # mismo sin importar el modo de exportación.
        # =====================================================

        RESULTADOS = {

            "producto": PRODUCTO,
            "fuente": FUENTE,
            "resolucion": RESOLUCION,
            "epsg": EPSG_DESTINO.replace("EPSG:", "") if EPSG_DESTINO else "4326",
            "fecha_inicio": FECHA_INICIO,
            "fecha_fin": FECHA_FIN,
            "nombre_resultado": NOMBRE_RESULTADO,
            "cantidad_imagenes": CANTIDAD_IMAGENES,

            "metadatos_tecnicos": {
                "descripcion": f"Análisis espacial de {PRODUCTO} utilizando la fuente {FUENTE}.",
                "metodo_calculo": METODO,
                "metodo_composicion_temporal": "mediana (resistente a nubes residuales que la máscara no haya detectado)",
                "resolucion_espacial_m": RESOLUCION,
                "notas": "Generado automáticamente por el motor GEE + QGIS (modo Drive: estadísticas server-side, raster completo pendiente en Google Drive)."
            },

            "estadisticas": {
                "pixeles": estadisticas["pixeles"],
                "minimo": round(estadisticas["minimo"], 4),
                "maximo": round(estadisticas["maximo"], 4),
                "media": round(estadisticas["media"], 4),
                "desvio": round(estadisticas["desvio"], 4),
                "superficie_ha": round(superficie["ha"], 2),
                "superficie_km2": round(superficie["km2"], 4)
            },

            "clasificacion_detallada": {clave: round(valor, 2) for clave, valor in porcentajes.items()},

            "interpretacion": interpretacion["resultados"],

            "exportacion_drive": {
                "tarea_id": estado_tarea.get("id"),
                "estado_al_enviar": estado_tarea.get("state"),
                "carpeta": "EarthEngine",
                "nombre_archivo": f"{NOMBRE_RESULTADO}{EXTENSION_RASTER}",
            },

        }

        carpeta_destino = QFileDialog.getExistingDirectory(
            None, "Seleccione una carpeta local para guardar el informe y el estilo"
        )

        usa_rango_automatico = PRODUCTOS.get(PRODUCTO, {}).get("rango_automatico", False)

        if usa_rango_automatico:
            escribir("")
            escribir(
                "NOTA: este producto usa rango de color automático (calculado "
                "sobre los valores reales del raster), así que el .qml no se "
                "pudo generar de antemano. Cuando cargues el .tif desde Drive, "
                "aplicá el estilo a mano desde QGIS."
            )

        if carpeta_destino:
            generar_documentacion(
                capa=None,
                ruta_destino=carpeta_destino,
                nombre_base=NOMBRE_RESULTADO,
                informe=INFORME,
                resultados=RESULTADOS,
                guardar_estilo=False,
            )
            if not usa_rango_automatico:
                try:
                    generar_qml_independiente(
                        os.path.join(carpeta_destino, f"{NOMBRE_RESULTADO}.qml")
                    )
                except Exception as error_qml:
                    print(f"No se pudo generar el .qml: {error_qml}")

        return {
            "resultados": RESULTADOS,
            "producto": PRODUCTO,
            "modo": "drive",
            "nombre_capa": NOMBRE_CAPA,
            "centroide_lat": centroide.y(),
            "centroide_lon": centroide.x(),
            "tarea_id": estado_tarea.get("id"),
            "carpeta_local": carpeta_destino,
            "informe_texto": "\n".join(INFORME),
        }

    # =====================================================
    # GENERAR DOCUMENTACIÓN
    # =====================================================

    def generar_documentacion(capa, ruta_destino, nombre_base, informe, resultados, guardar_estilo=False):

        # =====================================================
        # EXPORTAR ESTILO
        # =====================================================
        if guardar_estilo:
            ruta_estilo = os.path.join(
                ruta_destino,
                f"{nombre_base}.qml"
            )
            capa.saveNamedStyle(ruta_estilo)

        # =====================================================
        # EXPORTAR INFORME
        # =====================================================
        ruta_txt = os.path.join(
            ruta_destino,
            f"{nombre_base}.txt"
        )

        with open(ruta_txt, "w", encoding="utf-8") as archivo:
            for linea in informe:
                archivo.write(linea + "\n")        

        # =====================================================
        # EXPORTAR JSON
        # =====================================================
        ruta_json = os.path.join(
            ruta_destino,
            f"{nombre_base}.json"
        )

        with open(ruta_json, "w", encoding="utf-8") as archivo:
            json.dump(resultados, archivo, indent=4, ensure_ascii=False)

        return ruta_json

    # =====================================================
    # LEER RASTER COMO ARRAY
    # =====================================================

    def leer_raster_array(ruta_raster):

        dataset = gdal.Open(ruta_raster)

        if dataset is None:

            raise Exception(
                f"No se pudo abrir el raster:\n{ruta_raster}"
            )

        banda = dataset.GetRasterBand(1)

        array = banda.ReadAsArray()

        dataset = None

        return array

    # =====================================================
    # IMPRIMIR ENCABEZADO ESTADÍSTICO
    # =====================================================

    def imprimir_encabezado_estadistico(estadisticas, pixeles, superficie_ha, superficie_km2, cantidad_imagenes):

        escribir("=" * 40)
        escribir("ANÁLISIS ESTADÍSTICO")
        escribir("=" * 40)

        escribir(f"Producto: {PRODUCTO}")
        escribir(f"Fuente: {FUENTE}")
        escribir(f"Capa: {NOMBRE_CAPA}")
        escribir(f"Resolución: {RESOLUCION} m")
        escribir(f"EPSG: {EPSG_DESTINO if EPSG_DESTINO else '4326 (por defecto)'}")
        escribir("Método de composición temporal: mediana")

        escribir("")
        escribir(f"Período: {FECHA_INICIO} → {FECHA_FIN}")
        escribir("")

        escribir(f"Imágenes procesadas: {cantidad_imagenes}")
        escribir(f"Cantidad de píxeles : {pixeles}")
        escribir("")

        escribir(f"Valor mínimo      : {estadisticas['minimo']}")
        escribir(f"Valor máximo      : {estadisticas['maximo']}")
        escribir(f"Media               : {estadisticas['media']}")
        escribir(f"Desvío estándar   : {estadisticas['desvio']}")

        escribir(
            f"Superficie analizada: {superficie_ha:.2f} ha ({superficie_km2:.4f} km²)"
        )

    # =====================================================
    # CLASIFICAR ÍNDICES
    # =====================================================

    def clasificar_indices(

        histograma,
        estadisticas,
        pixeles):

        if PRODUCTO not in CLASIFICACIONES:
            return {}, {}  # Sin clases definidas para este producto: devolvemos vacío

        clases = CLASIFICACIONES[PRODUCTO]

        histograma_vector = histograma["histograma"]

        limites = histograma["limites"]

        ancho_bin = histograma["ancho_bin"]

        clases = CLASIFICACIONES[PRODUCTO]

        resultado_clases = {}

        for _, _, nombre in clases:

            resultado_clases[nombre] = 0

        for i, frecuencia in enumerate(

            histograma_vector

        ):

            valor = limites[i]

            for minimo, maximo, nombre in clases:

                if minimo <= valor < maximo:

                    resultado_clases[nombre] += frecuencia

                    break

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN")
        escribir("=" * 40)

        porcentajes = {}

        # 1. Obtenemos la paleta de colores exclusiva de este producto
        colores_producto = REFERENCIAS_COLOR.get(PRODUCTO, {})

        for nombre, cantidad in resultado_clases.items():

            if cantidad == 0:
                continue

            porcentaje = (cantidad / pixeles) * 100
            porcentajes[nombre] = porcentaje

            # 2. Buscamos el color exacto para esta clase dentro de su producto
            color_texto = colores_producto.get(nombre, "")
            etiqueta_color = f"  [ {color_texto} ]" if color_texto else ""

            escribir(
                f"{nombre:<25}"
                f"{porcentaje:>6.2f} %{etiqueta_color}"
            )

        return resultado_clases, porcentajes

    # =====================================================
    # INTERPRETAR ÍNDICES
    # =====================================================

    def interpretar_indice(producto, porcentajes, estadisticas):

        if producto in FAMILIAS["VEGETACION"]:
            return interpretar_vegetacion(producto, porcentajes)

        elif producto in FAMILIAS["AGUA"]:
            return interpretar_agua(producto, porcentajes)

        elif producto in FAMILIAS["URBANIZACION"]:
            return interpretar_urbanizacion(porcentajes)

        elif producto in FAMILIAS["TEMPERATURA"]:
            return interpretar_temperatura(porcentajes)

        elif producto in FAMILIAS["HUMEDAD"]:
            return interpretar_humedad(porcentajes)

        elif producto in FAMILIAS["INCENDIOS"]:
            return interpretar_incendios(porcentajes)

        elif producto in FAMILIAS["USO_SUELO"]:
            return interpretar_uso_suelo(porcentajes)

        elif producto in FAMILIAS["METEOROLOGIA"]:
            return interpretar_meteorologia(producto, estadisticas)

        elif producto in FAMILIAS["TURBIDEZ"]:
            return interpretar_turbidez(porcentajes)

        raise ValueError(
            f"No existe intérprete para la familia del producto: {producto}"
        )

    # =====================================================
    # INFORME ÍNDICE
    # =====================================================

    def imprimir_informe_indice(producto, interpretacion):

        if producto in FAMILIAS["VEGETACION"]:
            return imprimir_informe_vegetacion(interpretacion)

        elif producto in FAMILIAS["AGUA"]:
            return imprimir_informe_agua(interpretacion)

        elif producto in FAMILIAS["URBANIZACION"]:
            return imprimir_informe_urbanizacion(interpretacion)

        elif producto in FAMILIAS["TEMPERATURA"]:
            return imprimir_informe_temperatura(interpretacion)

        elif producto in FAMILIAS["HUMEDAD"]:
            return imprimir_informe_humedad(interpretacion)

        elif producto in FAMILIAS["INCENDIOS"]:
            return imprimir_informe_incendios(interpretacion)

        elif producto in FAMILIAS["USO_SUELO"]:
            return imprimir_informe_uso_suelo(interpretacion)

        elif producto in FAMILIAS["METEOROLOGIA"]:
            return imprimir_informe_meteorologia(interpretacion)

        elif producto in FAMILIAS["TURBIDEZ"]:
            return imprimir_informe_turbidez(interpretacion)
        
        raise ValueError(
            f"No existe informe para la familia del producto: {producto}"
        )

    # =====================================================
    # INTERPRETAR VEGETACIÓN
    # =====================================================

    def interpretar_vegetacion(producto, porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        # =====================================================
        # LÓGICA NDVI (La que ya tenías)
        # =====================================================
        if producto == "NDVI":

            vegetacion_activa = (
                porcentajes.get("Vegetación moderada", 0) +
                porcentajes.get("Vegetación densa", 0) +
                porcentajes.get("Vegetación muy densa", 0)
            )

            estado_vegetacion = "muy alta" if vegetacion_activa >= 80 else "alta" if vegetacion_activa >= 60 else "moderada" if vegetacion_activa >= 40 else "baja" if vegetacion_activa >= 20 else "muy baja"

            cobertura_baja = porcentajes.get("Vegetación escasa", 0) + porcentajes.get("Vegetación baja", 0)
            superficie_no_vegetada = porcentajes.get("Agua", 0) + porcentajes.get("Suelo desnudo", 0)
            vegetacion_alta = porcentajes.get("Vegetación densa", 0) + porcentajes.get("Vegetación muy densa", 0)

            predominio_vegetacion = vegetacion_alta - cobertura_baja

            if vegetacion_alta >= 60:
                diagnostico_vegetacion = "Predominan coberturas vegetales de alta respuesta espectral."
            elif vegetacion_alta >= 30:
                diagnostico_vegetacion = "Existe una presencia significativa de coberturas vegetales desarrolladas."
            else:
                diagnostico_vegetacion = "La presencia de coberturas vegetales de alta respuesta es reducida."

        # =====================================================
        # LÓGICA MSAVI (Nueva, adaptada al ecosistema)
        # =====================================================
        elif producto == "MSAVI":

            # Para MSAVI, la vegetación "baja" y "moderada" es la salud normal del ecosistema
            vegetacion_activa = (
                porcentajes.get("Vegetación baja", 0) +
                porcentajes.get("Vegetación moderada", 0) +
                porcentajes.get("Vegetación densa", 0)
            )

            estado_vegetacion = "saludable y adaptada" if vegetacion_activa >= 70 else "moderada" if vegetacion_activa >= 40 else "escasa"

            cobertura_baja = porcentajes.get("Vegetación escasa", 0)
            superficie_no_vegetada = porcentajes.get("Suelo desnudo", 0)

            # En MSAVI, consideramos "alta" desde la moderada
            vegetacion_alta = porcentajes.get("Vegetación moderada", 0) + porcentajes.get("Vegetación densa", 0)

            predominio_vegetacion = vegetacion_activa - superficie_no_vegetada

            if vegetacion_activa >= 60:
                diagnostico_vegetacion = "Predomina un estrato herbáceo/arbustivo estable y característico de la región."
            elif vegetacion_activa >= 30:
                diagnostico_vegetacion = "Existe una transición equilibrada entre suelo desnudo y matorrales."
            else:
                diagnostico_vegetacion = "Fuerte predominio de suelo desnudo o severo estrés ecológico."

        # Retornamos el diccionario unificado para que el redactor de QGIS no explote
        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "vegetacion_activa": round(vegetacion_activa, 2),
                "vegetacion_alta": round(vegetacion_alta, 2),
                "cobertura_baja": round(cobertura_baja, 2),
                "superficie_no_vegetada": round(superficie_no_vegetada, 2),
                "estado_vegetacion": estado_vegetacion,
                "predominio_vegetacion": predominio_vegetacion,
                "diagnostico": diagnostico_vegetacion
            }
        }

    def imprimir_informe_vegetacion(interpretacion):

        resultados = interpretacion["resultados"]

        escribir("")

        escribir("=" * 40)
        escribir("INTERPRETACIÓN")
        escribir("=" * 40)

        escribir("")

        escribir(

            f"La cobertura predominante corresponde a "

            f"{resultados['clase_dominante'].lower()} "
            f"({resultados['porcentaje_dominante']:.2f} %)."

        )

        escribir("")

        escribir(

            resultados["diagnostico"]

        )

        escribir("")

        escribir(

            f"La vegetación de alta respuesta espectral "

            f"(vegetación densa + muy densa) representa "

            f"{resultados['vegetacion_alta']:.2f} % del área analizada."

        )

        escribir("")

        escribir(

            f"El predominio de coberturas vegetales de alto vigor "

            f"sobre superficies de baja cobertura alcanza "

            f"{resultados['predominio_vegetacion']:.2f} %."

        )

        escribir("")

        escribir(

            f"El área analizada presenta una cobertura vegetal "

            f"{resultados['estado_vegetacion']} "

            f"({resultados['vegetacion_activa']:.2f} % del territorio)."

        )

        escribir("")

        escribir(

            f"La cobertura vegetal baja representa "
            f"{resultados['cobertura_baja']:.2f} % del área analizada."
        )

    # =====================================================
    # INTERPRETAR AGUA
    # =====================================================

    def interpretar_agua(producto, porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        if producto == "NDWI":

            agua_muy_alta = porcentajes.get("Agua muy alta", 0)
            agua_alta = porcentajes.get("Agua alta", 0)
            agua_moderada = porcentajes.get("Agua moderada", 0)
            agua_baja = porcentajes.get("Agua baja", 0)
            agua_muy_baja = porcentajes.get("Agua muy baja", 0)

            respuesta_alta = agua_moderada + agua_alta + agua_muy_alta
            respuesta_baja = agua_baja + agua_muy_baja

            if respuesta_alta > respuesta_baja:
                diagnostico = "Predomina una alta respuesta hídrica."
            else:
                diagnostico = "Predomina una baja respuesta hídrica."

            return {
                "resultados": {
                    "clase_dominante": clase_dominante,
                    "porcentaje_dominante": round(porcentaje_dominante, 2),
                    "respuesta_alta": round(respuesta_alta, 2),
                    "respuesta_baja": round(respuesta_baja, 2),
                    "agua_muy_alta": round(agua_muy_alta, 2),
                    "agua_alta": round(agua_alta, 2),
                    "agua_moderada": round(agua_moderada, 2),
                    "agua_baja": round(agua_baja, 2),
                    "agua_muy_baja": round(agua_muy_baja, 2),
                    "diagnostico": diagnostico
                }
            }

        if producto == "MNDWI":

            agua = porcentajes.get("Agua", 0) + porcentajes.get("Agua profunda", 0)
            agua_somera = porcentajes.get("Agua somera", 0)
            agua_total = agua_somera + agua

            suelo = porcentajes.get("Suelo", 0) + porcentajes.get("Suelo muy seco", 0)
            humedad = porcentajes.get("Humedad", 0)

            if agua > suelo:
                diagnostico = "Predominan superficies cubiertas por agua."
            else:
                diagnostico = "Predominan superficies terrestres."

            return {
                "resultados": {
                    "clase_dominante": clase_dominante,
                    "porcentaje_dominante": round(porcentaje_dominante, 2),
                    "agua_total": round(agua_total, 2),
                    "agua_profunda": round(agua, 2),
                    "agua_somera": round(agua_somera, 2),
                    "humedad": round(humedad, 2),
                    "suelo_seco": round(suelo, 2),
                    "diagnostico": diagnostico
                }
            }

    def imprimir_informe_agua(interpretacion):

        resultados = interpretacion["resultados"]

        escribir("")
        escribir("=" * 40)
        escribir("INTERPRETACIÓN")
        escribir("=" * 40)
        escribir("")

        escribir(f"La clase predominante corresponde a {resultados['clase_dominante'].lower()} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir("")

        escribir(resultados["diagnostico"])
        escribir("")

        if "respuesta_alta" in resultados: # Es NDWI
            escribir(f"Las superficies con respuesta hídrica moderada a muy alta representan el {resultados['respuesta_alta']:.2f} % del área analizada.")
            escribir("")
            escribir(f"Las superficies de baja respuesta hídrica representan el {resultados['respuesta_baja']:.2f} %.")

        elif "agua_total" in resultados: # Es MNDWI
            escribir(f"Las superficies con presencia de agua (somera y profunda) representan el {resultados['agua_total']:.2f} % del área analizada.")
            escribir("")
            escribir(f"Las áreas de humedad abarcan el {resultados['humedad']:.2f} % y los suelos secos el {resultados['suelo_seco']:.2f} %.")
    
    # =====================================================
    # INTERPRETAR TURBIDEZ (NDTI)
    # =====================================================

    def interpretar_turbidez(porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        alta = porcentajes.get("Turbidez alta", 0) + porcentajes.get("Turbidez muy alta", 0)
        baja = porcentajes.get("Turbidez baja", 0) + porcentajes.get("Turbidez muy baja", 0)
        moderada = porcentajes.get("Turbidez moderada", 0)

        if alta > baja and alta > moderada:
            diagnostico = "Predomina una respuesta espectral asociada a mayor carga de sedimentos en suspensión."
        elif baja > alta and baja > moderada:
            diagnostico = "Predomina una respuesta espectral asociada a agua con baja carga de sedimentos."
        else:
            diagnostico = "El cuerpo de agua presenta una condición intermedia o heterogénea."

        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "turbidez_alta": round(alta, 2),
                "turbidez_moderada": round(moderada, 2),
                "turbidez_baja": round(baja, 2),
                "diagnostico": diagnostico
            }
        }

    def imprimir_informe_turbidez(interpretacion):

        resultados = interpretacion["resultados"]
        escribir("\n" + "=" * 40 + "\nINTERPRETACIÓN\n" + "=" * 40 + "\n")
        escribir(f"Clase predominante: {resultados['clase_dominante']} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir(resultados["diagnostico"])
        escribir(f"\nRespuesta alta o muy alta: {resultados['turbidez_alta']:.2f} %")
        escribir(f"Respuesta moderada: {resultados['turbidez_moderada']:.2f} %")
        escribir(f"Respuesta baja o muy baja: {resultados['turbidez_baja']:.2f} %")

    # =====================================================
    # INTERPRETAR URBANIZACIÓN
    # =====================================================

    def interpretar_urbanizacion(porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        urbanizacion_alta = porcentajes.get("Urbanización alta", 0)
        urbanizacion_media = porcentajes.get("Urbanización media", 0)
        urbanizacion_baja = porcentajes.get("Urbanización baja", 0)
        urbanizacion_total = urbanizacion_baja + urbanizacion_media + urbanizacion_alta

        suelo = porcentajes.get("Suelo", 0)
        vegetacion = porcentajes.get("Vegetación", 0)
        transicion = porcentajes.get("Transición", 0)

        if urbanizacion_total > vegetacion + suelo:
            diagnostico = "Predomina una alta respuesta asociada a superficies urbanizadas."
        else:
            diagnostico = "Predominan superficies naturales."

        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "urbanizacion_total": round(urbanizacion_total, 2),
                "superficies_naturales": round(vegetacion + suelo, 2),
                "transicion": round(transicion, 2),
                "diagnostico": diagnostico
            }
        }

    def imprimir_informe_urbanizacion(interpretacion):

        resultados = interpretacion["resultados"]
        escribir("\n" + "=" * 40 + "\nINTERPRETACIÓN\n" + "=" * 40 + "\n")
        escribir(f"Clase predominante: {resultados['clase_dominante']} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir(resultados["diagnostico"])
        escribir(f"\nSuperficies urbanas: {resultados['urbanizacion_total']:.2f} %")
        escribir(f"Superficies naturales: {resultados['superficies_naturales']:.2f} %")
        escribir(f"Zonas de transición: {resultados['transicion']:.2f} %")

    # =====================================================
    # INTERPRETAR TEMPERATURA (LST)
    # =====================================================

    def interpretar_temperatura(porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        calor = porcentajes.get("Cálido", 0) + porcentajes.get("Muy cálido", 0)
        frio = porcentajes.get("Frío", 0) + porcentajes.get("Muy frío", 0)
        templado = porcentajes.get("Templado", 0)

        if calor > frio and calor > templado:
            diagnostico = "Dominancia de superficies con alta absorción y emisión térmica (suelo expuesto o área urbana)."
        elif frio > calor and frio > templado:
            diagnostico = "Predominan coberturas con alta capacidad de regulación térmica (agua o vegetación densa)."
        else:
            diagnostico = "El área presenta un equilibrio térmico con mezcla heterogénea de coberturas."

        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "superficies_calidas": round(calor, 2),
                "superficies_frias": round(frio, 2),
                "superficies_templadas": round(templado, 2),
                "diagnostico": diagnostico
            }
        }

    def imprimir_informe_temperatura(interpretacion):

        resultados = interpretacion["resultados"]

        escribir("\n" + "=" * 40 + "\nINTERPRETACIÓN\n" + "=" * 40 + "\n")
        escribir(f"Condición térmica predominante: {resultados['clase_dominante']} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir(resultados["diagnostico"])
        escribir(f"\nSuperficies cálidas/muy cálidas: {resultados['superficies_calidas']:.2f} %")
        escribir(f"Superficies frías (sumideros térmicos): {resultados['superficies_frias']:.2f} %")

    # =====================================================
    # INTERPRETAR HUMEDAD (NDMI)
    # =====================================================

    def interpretar_humedad(porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        estres = porcentajes.get("Estrés hídrico severo", 0) + porcentajes.get("Estrés hídrico moderado", 0)
        humedad_optima = porcentajes.get("Humedad moderada", 0) + porcentajes.get("Humedad alta", 0)
        humedad_baja = porcentajes.get("Humedad baja", 0)

        if estres > humedad_optima:
            diagnostico = "Marcado déficit de humedad, indicativo de sequía o alto grado de exposición del suelo."
        elif humedad_optima > estres:
            diagnostico = "Niveles óptimos de contenido de agua foliar, ecosistema vigoroso."
        else:
            diagnostico = "Condiciones hídricas transicionales o estacionales."

        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "estres_hidrico": round(estres, 2),
                "humedad_optima": round(humedad_optima, 2),
                "humedad_baja": round(humedad_baja, 2),
                "diagnostico": diagnostico
            }
        }

    def imprimir_informe_humedad(interpretacion):

        resultados = interpretacion["resultados"]

        escribir("\n" + "=" * 40 + "\nINTERPRETACIÓN\n" + "=" * 40 + "\n")
        escribir(f"Condición hídrica predominante: {resultados['clase_dominante']} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir(resultados["diagnostico"])
        escribir(f"\nSuperficies con estrés hídrico: {resultados['estres_hidrico']:.2f} %")
        escribir(f"Superficies con humedad óptima: {resultados['humedad_optima']:.2f} %")

    # =====================================================
    # INTERPRETAR INCENDIOS (NBR)
    # =====================================================

    def interpretar_incendios(porcentajes):

        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        severidad_alta = porcentajes.get("Alta severidad de quema", 0) + porcentajes.get("Moderada-alta severidad", 0)
        severidad_baja = porcentajes.get("Baja severidad", 0)
        area_afectada_total = severidad_alta + severidad_baja
        area_sana = porcentajes.get("Área no quemada", 0) + porcentajes.get("Vegetación sana", 0)

        if area_afectada_total >= 1.0:
            if severidad_alta > severidad_baja:
                diagnostico = "Patrón de quema con predominancia de alta severidad (pérdida profunda de biomasa)."
            else:
                diagnostico = "Impacto del fuego mayoritariamente de baja severidad (quema superficial)."
        else:
            diagnostico = "No se detectan cicatrices de quema ni estrés por fuego significativos."

        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "area_afectada_total": round(area_afectada_total, 2),
                "severidad_alta": round(severidad_alta, 2),
                "severidad_baja": round(severidad_baja, 2),
                "area_sana": round(area_sana, 2),
                "diagnostico": diagnostico
            }
        }

    def imprimir_informe_incendios(interpretacion):

        resultados = interpretacion["resultados"]

        escribir("\n" + "=" * 40 + "\nINTERPRETACIÓN\n" + "=" * 40 + "\n")
        escribir(f"Clase predominante: {resultados['clase_dominante']} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir(resultados["diagnostico"])
        escribir(f"\nÁrea total afectada por fuego: {resultados['area_afectada_total']:.2f} %")
        escribir(f"Alta severidad: {resultados['severidad_alta']:.2f} %")
        escribir(f"Área libre de quemas: {resultados['area_sana']:.2f} %")

    # =====================================================
    # INTERPRETAR USO DE SUELO (DYNAMIC WORLD)
    # =====================================================

    def interpretar_uso_suelo(porcentajes):
        clase_dominante = max(porcentajes, key=porcentajes.get)
        porcentaje_dominante = porcentajes[clase_dominante]

        urbano = porcentajes.get("Área construida (Urbana)", 0)
        cultivos = porcentajes.get("Cultivos", 0)
        arboles = porcentajes.get("Árboles", 0)
        agua = porcentajes.get("Agua", 0)

        # Agrupamos toda la naturaleza en una sola variable para el diagnóstico general
        natural = arboles + porcentajes.get("Pasto / Vegetación baja", 0) + porcentajes.get("Arbustos / Matorrales", 0)

        diagnostico = f"La matriz territorial se encuentra dominada por la categoría '{clase_dominante}'."

        return {
            "resultados": {
                "clase_dominante": clase_dominante,
                "porcentaje_dominante": round(porcentaje_dominante, 2),
                "area_urbana": round(urbano, 2),
                "area_cultivos": round(cultivos, 2),
                "area_forestal": round(arboles, 2),
                "area_agua": round(agua, 2),
                "area_natural_total": round(natural, 2),
                "diagnostico": diagnostico
            }
        }

    def imprimir_informe_uso_suelo(interpretacion):
        resultados = interpretacion["resultados"]
        escribir("\n" + "=" * 40 + "\nINTERPRETACIÓN DE USO DE SUELO\n" + "=" * 40 + "\n")
        escribir(f"Clase predominante: {resultados['clase_dominante']} ({resultados['porcentaje_dominante']:.2f} %).")
        escribir(resultados["diagnostico"])
        escribir(f"\nÁrea urbana / construida: {resultados['area_urbana']:.2f} %")
        escribir(f"Superficie agrícola (cultivos): {resultados['area_cultivos']:.2f} %")
        escribir(f"Cobertura forestal (árboles): {resultados['area_forestal']:.2f} %")

    # =====================================================
    # INTERPRETAR METEOROLOGÍA (CHIRPS Y TERRACLIMATE)
    # =====================================================

    def interpretar_meteorologia(producto, estadisticas):
        media = estadisticas["media"]
        maximo = estadisticas["maximo"]

        if producto == "CHIRPS":
            diagnostico = f"El acumulado promedio de precipitación en el área fue de {media:.1f} mm."
            return {
                "resultados": {
                    "precipitacion_acumulada_mm": round(media, 1),
                    "precipitacion_maxima_mm": round(maximo, 1),
                    "diagnostico": diagnostico
                }
            }

        elif producto == "VIENTO_ERA5":
            # El raster ya nos dio la velocidad pura en m/s. Solo la pasamos a km/h.
            viento_kmh = media * 3.6
            viento_max_kmh = maximo * 3.6

            diagnostico = f"La velocidad media del viento fue de {viento_kmh:.1f} km/h, con predominancia desde el sector {ROSA_VIENTOS}."

            return {
                "resultados": {
                    "viento_promedio_kmh": round(viento_kmh, 1),
                    "viento_maximo_kmh": round(viento_max_kmh, 1),
                    "direccion_predominante": ROSA_VIENTOS,
                    "diagnostico": diagnostico
                }
            }

    def imprimir_informe_meteorologia(interpretacion):

        resultados = interpretacion["resultados"]
        escribir("\n" + "=" * 40 + "\nREPORTE METEOROLÓGICO\n" + "=" * 40 + "\n")
        escribir(resultados["diagnostico"])

        # Imprimimos el dato secundario dependiendo de si es lluvia o viento
        if "precipitacion_maxima_mm" in resultados:
            escribir(f"Pico máximo acumulado (zona más lluviosa): {resultados['precipitacion_maxima_mm']:.1f} mm.")
        elif "viento_maximo_kmh" in resultados:
            escribir(f"Ráfaga promedio máxima registrada: {resultados['viento_maximo_kmh']:.1f} km/h.")

    # =====================================================
    # CALCULAR ESTADÍSTICAS
    # =====================================================

    INFORME = []

    def calcular_estadisticas():

        if PRODUCTO in [
            "DEM", "DEM_RELIEVE", "PENDIENTE", "ASPECT", 
            "CURVATURA", "TRI", "TPI", "IRREGULARIDAD"
        ]:
            return calcular_estadisticas_dem()

        # 1. BORRAMOS EL "global INFORME"
        INFORME.clear()

        estadisticas = obtener_estadisticas_raster(archivo_temporal)

        array = leer_raster_array(archivo_temporal)

        array = array[np.isfinite(array)]
        array = array[array != NODATA]

        pixeles = estadisticas["pixeles"]

        # =====================================================
        # SUPERFICIE DEL ÁREA DE ESTUDIO
        # =====================================================

        superficie = obtener_superficie_area()

        superficie_m2 = superficie["m2"]
        superficie_ha = superficie["ha"]
        superficie_km2 = superficie["km2"]


        imprimir_encabezado_estadistico(
            estadisticas,
            pixeles, 
            superficie_ha,
            superficie_km2,
            CANTIDAD_IMAGENES
        )

        array = leer_raster_array(
            archivo_temporal
        )

        histograma = obtener_histograma(
            array,
            pixeles
        )

        resultado_clases, porcentajes = clasificar_indices(

            histograma,

            estadisticas,

            pixeles

        )

        interpretacion = interpretar_indice(
            PRODUCTO,
            porcentajes,
            estadisticas
        )

        imprimir_informe_indice(
            PRODUCTO,
            interpretacion
        )

        # =====================================================
        # RESULTADOS ESTRUCTURADOS
        # =====================================================

        RESULTADOS = {

            "producto": PRODUCTO,
            "fuente": FUENTE,
            "resolucion": RESOLUCION,
            "epsg": EPSG_DESTINO.replace("EPSG:", "") if EPSG_DESTINO else "4326",
            "fecha_inicio": FECHA_INICIO,
            "fecha_fin": FECHA_FIN,
            "nombre_resultado": NOMBRE_RESULTADO,
            "cantidad_imagenes": CANTIDAD_IMAGENES,

            # Nuevo bloque de contexto técnico
            "metadatos_tecnicos": {
                "descripcion": f"Análisis espacial de {PRODUCTO} utilizando la fuente {FUENTE}.",
                "metodo_calculo": METODO,
                "metodo_composicion_temporal": "mediana (resistente a nubes residuales que la máscara no haya detectado)",
                "resolucion_espacial_m": RESOLUCION,
                "notas": "Generado automáticamente por el motor GEE + QGIS."
            },

            "estadisticas": {
                "pixeles": pixeles,
                "minimo": round(estadisticas["minimo"], 4),
                "maximo": round(estadisticas["maximo"], 4),
                "media": round(estadisticas["media"], 4),
                "desvio": round(estadisticas["desvio"], 4),
                "superficie_ha": round(superficie_ha, 2),
                "superficie_km2": round(superficie_km2, 4)
            },

            # El JSON recibe solo los números limpios, sin los colores
            "clasificacion_detallada": {clave: round(valor, 2) for clave, valor in porcentajes.items()},

            "interpretacion": interpretacion["resultados"]

        }

        return RESULTADOS, list(INFORME)

    # =====================================================
    # OBTENER ESTADÍSTICAS DEL RASTER (GDAL)
    # =====================================================

    def obtener_estadisticas_raster(raster):

        ds = gdal.Open(raster)

        banda = ds.GetRasterBand(1)

        array = banda.ReadAsArray()

        nodata = banda.GetNoDataValue()

        array = array[np.isfinite(array)]

        if nodata is not None:
            array = array[~np.isclose(array, nodata)]

        array = array[~np.isclose(array, NODATA)]

        pixeles_validos = array.size

        # --- NUEVO ESCUDO: Si no hay píxeles, devolver 0 en todo ---
        if pixeles_validos == 0:
            print("ADVERTENCIA: Raster vacío o compuesto 100% por NoData.")
            return {
                "minimo": 0.0,
                "maximo": 0.0,
                "media": 0.0,
                "desvio": 0.0,
                "pixeles": 0
            }

        return {

            "minimo": float(np.min(array)),
            "maximo": float(np.max(array)),
            "media": float(np.mean(array)),
            "desvio": float(np.std(array)),
            "pixeles": int(pixeles_validos)

        }

    # =====================================================
    # OBTENER SUPERFICIE DEL ÁREA DE ESTUDIO
    # =====================================================

    def obtener_superficie_area():

        pixel_area = ee.Image.pixelArea()

        area = pixel_area.reduceRegion(

            reducer=ee.Reducer.sum(),

            geometry=roi,

            scale=RESOLUCION,

            maxPixels=1e13

        )

        superficie_m2 = area.getInfo()["area"]

        return {

            "m2": superficie_m2,
            "ha": superficie_m2 / 10000,
            "km2": superficie_m2 / 1000000

        }

    # =====================================================
    # IMPRIMIR ESTADÍSTICAS
    # =====================================================

    def imprimir_estadisticas(
        minimo,
        maximo,
        media,
        desvio,
        cantidad_pixeles,
        superficie_ha,
        superficie_km2):

        escribir("=" * 40)
        escribir("ANÁLISIS ESTADÍSTICO")
        escribir("=" * 40)

        escribir(f"Producto: {PRODUCTO}")
        escribir(f"Fuente: {FUENTE}")
        escribir(f"Capa: {NOMBRE_CAPA}")

        escribir(f"Cantidad de píxeles : {cantidad_pixeles}")
        escribir(f"Valor mínimo      : {minimo}")
        escribir(f"Valor máximo      : {maximo}")
        escribir(f"Media               : {media}")
        escribir(f"Desvío estándar   : {desvio}")

        escribir(
            f"Superficie analizada: {superficie_ha:.2f} ha ({superficie_km2:.2f} km²)"
        )

    # =====================================================
    # OBTENER HISTOGRAMA
    # =====================================================

    def obtener_histograma(array, cantidad_pixeles):

        array = array[np.isfinite(array)]

        array = array[array != NODATA]

        cantidad_pixeles = array.size    

        if cantidad_pixeles == 0:
            raise Exception(
                "El raster no contiene píxeles válidos."
            )

        # 1. Calculamos el rango dinámico real de los datos
        min_val = float(np.min(array))
        max_val = float(np.max(array))

        # (Escudo por si la imagen es de un solo color sólido)
        if min_val == max_val:
            max_val += 0.001

        # 2. Armamos el histograma con los límites reales
        histograma_vector, limites = np.histogram(
            array,
            bins=100,
            range=(min_val, max_val)
        )

        ancho_bin = limites[1] - limites[0]

        frecuencia_maxima = histograma_vector.max()

        indice_maximo = np.argmax(histograma_vector)

        inicio_intervalo = limites[indice_maximo]

        fin_intervalo = limites[indice_maximo + 1]

        porcentaje_predominante = (
            frecuencia_maxima /
            cantidad_pixeles
        ) * 100

        return {
            "histograma": histograma_vector,
            "limites": limites,
            "ancho_bin": ancho_bin,
            "frecuencia_maxima": frecuencia_maxima,
            "inicio": inicio_intervalo,
            "fin": fin_intervalo,
            "porcentaje": porcentaje_predominante
        }

    # =====================================================
    # IMPRIMIR INTERVALOS DEL HISTOGRAMA
    # =====================================================

    def imprimir_intervalos_histograma(
        histograma_info,
        cantidad_pixeles,
        unidad,
        titulo):

        escribir("")
        escribir("=" * 40)
        escribir(titulo.upper())
        escribir("=" * 40)

        # Extraemos los datos de Numpy desde el diccionario
        frecuencias = histograma_info["histograma"]
        limites = histograma_info["limites"]
        ancho_bin = histograma_info["ancho_bin"]

        bins = []

        for i, frecuencia in enumerate(frecuencias):
            inicio = limites[i]
            fin = inicio + ancho_bin
            bins.append((frecuencia, inicio, fin))

        # Ordenamos de mayor a menor frecuencia
        bins.sort(reverse=True, key=lambda x: x[0])

        for frecuencia, inicio, fin in bins[:5]:

            # Nuestro viejo y confiable escudo contra divisiones por cero
            if cantidad_pixeles > 0:
                porcentaje = (frecuencia / cantidad_pixeles) * 100
            else:
                porcentaje = 0.0

            escribir(
                f"{inicio:.2f}"
                " - "
                f"{fin:.2f} {unidad}"
                " | "
                f"{frecuencia} píxeles"
                " | "
                f"{porcentaje:.2f} %"
            )

    # =====================================================
    # CONSTRUIR RESULTADOS DEM
    # =====================================================

    def construir_resultados_dem(minimo, maximo, media, desvio, cantidad_pixeles, superficie_ha, superficie_km2, amplitud):

        return {

            "producto": PRODUCTO,

            "fuente": FUENTE,

            "estadisticas": {

                "minimo": minimo,
                "maximo": maximo,
                "media": media,
                "desvio": desvio,
                "cantidad_pixeles": cantidad_pixeles,
                "superficie_ha": superficie_ha,
                "superficie_km2": superficie_km2,
                "amplitud": amplitud

            }

        }

    # =====================================================
    # CALCULAR ESTADÍSTICAS DEM
    # =====================================================

    def calcular_estadisticas_dem():

        # =====================================================
        # NOMBRE DEL PARÁMETRO ANALIZADO
        # =====================================================

        PARAMETRO = {

            "DEM": "Altitud",

            "DEM_RELIEVE": "Altitud",

            "PENDIENTE": "Pendiente",

            "ASPECT": "Orientación",

            "CURVATURA": "Curvatura",

            "TRI": "Índice de Rugosidad",

            "TPI": "Posición Topográfica",

            "IRREGULARIDAD": "Irregularidad"

        }[PRODUCTO]

        UNIDAD = {

            "DEM": "m",

            "DEM_RELIEVE": "m",

            "PENDIENTE": "°",

            "ASPECT": "°",

            "CURVATURA": "",

            "TRI": "",

            "TPI": "m",

            "IRREGULARIDAD": "m"

        }[PRODUCTO]

        DESCRIPTOR = {

            "DEM": "Concentración altimétrica",

            "DEM_RELIEVE": "Concentración altimétrica",

            "PENDIENTE": "Distribución de pendiente",

            "ASPECT": "Distribución de orientaciones",

            "CURVATURA": "Distribución de curvaturas",

            "TRI": "Distribución de rugosidad",

            "TPI": "Distribución topográfica",

            "IRREGULARIDAD": "Distribución de irregularidad"

        }[PRODUCTO]

        INTERVALO = {

            "DEM": "Intervalos altimétricos",

            "DEM_RELIEVE": "Intervalos altimétricos",

            "PENDIENTE": "Intervalos de pendiente",

            "ASPECT": "Intervalos de orientación",

            "CURVATURA": "Intervalos de curvatura",

            "TRI": "Intervalos de rugosidad",

            "TPI": "Intervalos topográficos",

            "IRREGULARIDAD": "Intervalos de irregularidad"

        }[PRODUCTO]

        INFORME.clear()

        provider = capa_resultado.dataProvider()

        estadisticas = obtener_estadisticas_raster(archivo_temporal)

        minimo = estadisticas["minimo"]
        maximo = estadisticas["maximo"]
        media = estadisticas["media"]
        desvio = estadisticas["desvio"]
        cantidad_pixeles = estadisticas["pixeles"]

        # =====================================================
        # SUPERFICIE DEL ÁREA DE ESTUDIO
        # =====================================================

        superficie = obtener_superficie_area()

        superficie_m2 = superficie["m2"]
        superficie_ha = superficie["ha"]
        superficie_km2 = superficie["km2"]

        imprimir_estadisticas(

            minimo,
            maximo,
            media,
            desvio,
            cantidad_pixeles,
            superficie_ha,
            superficie_km2

        )

        # 1. Extraemos el array matemático del raster
        array_dem = leer_raster_array(archivo_temporal)

        # 2. Le pasamos el array (no el provider) al histograma
        histograma_info = obtener_histograma(
            array_dem,
            cantidad_pixeles
        )

        histograma = histograma_info["histograma"]

        ancho_bin = histograma_info["ancho_bin"]

        frecuencia_maxima = histograma_info["frecuencia_maxima"]

        inicio_intervalo = histograma_info["inicio"]

        fin_intervalo = histograma_info["fin"]

        porcentaje_predominante = histograma_info["porcentaje"]

        # =====================================================
        # RESULTADO: INTERVALO PREDOMINANTE
        # =====================================================

        ruta_raster = capa_resultado.source()

        derivado = interpretar_derivado_dem(ruta_raster)

        clases = derivado.get("clases", [])
        clase_predominante = derivado.get("clase_predominante", {})
        diagnostico = derivado.get("diagnostico", {})
        interpretacion = derivado.get("interpretacion", {})

        escribir("")
        escribir("=" * 40)
        escribir(f"{PARAMETRO.upper()} PREDOMINANTE")
        escribir("=" * 40)

        if PRODUCTO in ["CURVATURA", "TPI", "IRREGULARIDAD"]:

            escribir(clase_predominante["nombre"])

            escribir(
                f"Representa: {clase_predominante['porcentaje']:.2f} % del área"
            )

            escribir("")

        else:

            escribir(
                f"{inicio_intervalo:.2f} - "
                f"{fin_intervalo:.2f} {UNIDAD}"
            )

            escribir(
                f"Píxeles: {frecuencia_maxima}"
            )

            escribir(
                f"Representa: {porcentaje_predominante:.2f} % del área"
            )

        if PRODUCTO not in ["CURVATURA", "TPI", "IRREGULARIDAD"]:

            escribir("")
            escribir("=" * 40)
            escribir(DESCRIPTOR.upper())
            escribir("=" * 40)

            escribir(
                f"El intervalo predominante representa "
                f"{porcentaje_predominante:.2f} % del área."
            )

        amplitud_altimetrica = maximo - minimo

        escribir("")
        escribir("=" * 40)
        escribir(f"AMPLITUD DE {PARAMETRO.upper()}")
        escribir("=" * 40)

        escribir(
            f"{amplitud_altimetrica:.2f} {UNIDAD}"
        )

        if PRODUCTO not in ["TPI", "CURVATURA", "IRREGULARIDAD"]:

            imprimir_intervalos_histograma(
                histograma_info,
                cantidad_pixeles,
                UNIDAD,
                INTERVALO
            )

        RESULTADOS = construir_resultados_dem(
            minimo, maximo, media, desvio, 
            cantidad_pixeles, superficie_ha, 
            superficie_km2, amplitud_altimetrica
        )

        # 2. DEVOLVEMOS UNA COPIA CONGELADA
        return RESULTADOS, list(INFORME)

    # =====================================================
    # INTERPRETACIÓN DERIVADOS DEM
    # =====================================================

    def interpretar_derivado_dem(ruta_raster):

        if PRODUCTO == "PENDIENTE":

            return interpretar_pendiente(ruta_raster)

        elif PRODUCTO == "ASPECT":

            return interpretar_aspect(ruta_raster)

        elif PRODUCTO == "TRI":

            return interpretar_tri(ruta_raster)

        elif PRODUCTO == "TPI":

            return interpretar_tpi(ruta_raster)

        elif PRODUCTO == "CURVATURA":

            return interpretar_curvatura(ruta_raster)

        elif PRODUCTO == "IRREGULARIDAD":

            return interpretar_irregularidad(ruta_raster)

        return {

            "clases": [],

            "clase_predominante": {},

            "diagnostico": {},

            "interpretacion": {}

        }

    # =====================================================
    # INTERPRETAR PENDIENTE
    # =====================================================

    def interpretar_pendiente(ruta_raster):

        array = leer_raster_array(ruta_raster)

        # --- 1. LIMPIEZA EXTREMA ---
        array = array[np.isfinite(array)]
        array = array[~np.isclose(array, -9999)]

        total = array.size

        # 2. Como ya no hay NaNs, podemos usar mean y std normales
        media = np.mean(array)
        desvio = np.std(array)


        clases = [

            ("Plano", 0, 2),

            ("Suavemente inclinado", 2, 5),

            ("Moderadamente inclinado", 5, 15),

            ("Fuertemente inclinado", 15, 30),

            ("Escarpado", 30, np.inf)

        ]

        resultados = []

        for nombre, minimo, maximo in clases:

            cantidad = np.sum(
                (array >= minimo) &
                (array < maximo)
            )

            porcentaje = cantidad / total * 100

            resultados.append({

                "nombre": nombre,

                "cantidad": int(cantidad),

                "porcentaje": porcentaje

            })
        clase_predominante = max(

            resultados,

            key=lambda x: x["porcentaje"]

        )

        if clase_predominante["nombre"] == "Plano":

            diagnostico = {

                "aptitud": "Muy alta",
                "limitacion": "Muy baja",
                "riesgo_erosion": "Muy bajo"

                }

        elif clase_predominante["nombre"] == "Suavemente inclinado":

            diagnostico = {

                "aptitud": "Alta",
                "limitacion": "Baja",
                "riesgo_erosion": "Bajo"

            }

        elif clase_predominante["nombre"] == "Moderadamente inclinado":

            diagnostico = {

                "aptitud": "Media",
                "limitacion": "Moderada",
                "riesgo_erosion": "Moderado"

            }

        elif clase_predominante["nombre"] == "Fuertemente inclinado":

            diagnostico = {

                "aptitud": "Baja",
                "limitacion": "Alta",
                "riesgo_erosion": "Alto"

            }

        else:

            diagnostico = {

                "aptitud": "Muy baja",
                "limitacion": "Muy alta",
                "riesgo_erosion": "Muy alto"

            }

        escribir("")
        escribir("=" * 40)
        escribir("DIAGNÓSTICO")
        escribir("=" * 40)

        escribir(f"Aptitud: {diagnostico['aptitud']}")
        escribir(f"Limitación: {diagnostico['limitacion']}")
        escribir(f"Riesgo de erosión: {diagnostico['riesgo_erosion']}")

        return {

            "clases": resultados,

            "clase_predominante": clase_predominante,

            "diagnostico": diagnostico,

            "interpretacion": {}

        }

    # =====================================================
    # CALCULAR ESTADÍSTICAS ASPECT
    # =====================================================

    def interpretar_aspect(ruta_raster):

        array = leer_raster_array(ruta_raster)

        # --- 1. LIMPIEZA EXTREMA ---
        array = array[np.isfinite(array)]
        array = array[~np.isclose(array, -9999)]

        # 2. El total de píxeles reales es simplemente el tamaño del array limpio
        total = array.size

        clases = [

            ("Norte",      (337.5, 360.0)),
            ("Norte",      (0.0,   22.5)),
            ("Noreste",    (22.5,  67.5)),
            ("Este",       (67.5, 112.5)),
            ("Sureste",   (112.5, 157.5)),
            ("Sur",       (157.5, 202.5)),
            ("Suroeste",  (202.5, 247.5)),
            ("Oeste",     (247.5, 292.5)),
            ("Noroeste",  (292.5, 337.5))

        ]

        resultados = []

        for nombre, (inicio, fin) in clases:

            mascara = (

                (array >= inicio)

                &

                (array < fin)

            )

            cantidad = np.count_nonzero(

                mascara

            )

            porcentaje = (

                cantidad /

                total

            ) * 100

            existe = next(

                (

                    item

                    for item in resultados

                    if item["nombre"] == nombre

                ),

                None

            )

            if existe:

                existe["cantidad"] += cantidad

                existe["porcentaje"] += porcentaje

            else:

                resultados.append(

                    {

                        "nombre": nombre,

                        "cantidad": cantidad,

                        "porcentaje": porcentaje

                    }

                )


        clase_predominante = max(

            resultados,

            key=lambda x: x["porcentaje"]

        )

        orientacion = clase_predominante["nombre"]

        if orientacion == "Norte":

            diagnostico = {

                "orientacion": "Norte",
                "insolacion": "Muy alta",
                "condicion_termica": "Mayor exposición solar",
                "aplicacion": "Mayor disponibilidad de radiación solar."

            }

        elif orientacion == "Noreste":

            diagnostico = {

                "orientacion": "Noreste",
                "insolacion": "Alta",
                "condicion_termica": "Buena exposición solar",
                "aplicacion": "Ambientes bien iluminados."

            }

        elif orientacion == "Este":

            diagnostico = {

                "orientacion": "Este",
                "insolacion": "Media-Alta",
                "condicion_termica": "Predominio de sol matutino",
                "aplicacion": "Mayor calentamiento durante la mañana."

            }

        elif orientacion == "Sureste":

            diagnostico = {

                "orientacion": "Sureste",
                "insolacion": "Media",
                "condicion_termica": "Exposición moderada",
                "aplicacion": "Condiciones térmicas intermedias."

            }

        elif orientacion == "Sur":

            diagnostico = {

                "orientacion": "Sur",
                "insolacion": "Baja",
                "condicion_termica": "Menor radiación solar",
                "aplicacion": "Sectores relativamente frescos."

            }

        elif orientacion == "Suroeste":

            diagnostico = {

                "orientacion": "Suroeste",
                "insolacion": "Media-Baja",
                "condicion_termica": "Radiación reducida",
                "aplicacion": "Ambientes con menor insolación."

            }

        elif orientacion == "Oeste":

            diagnostico = {

                "orientacion": "Oeste",
                "insolacion": "Alta",
                "condicion_termica": "Mayor radiación vespertina",
                "aplicacion": "Calentamiento durante la tarde."

            }

        elif orientacion == "Noroeste":

            diagnostico = {

                "orientacion": "Noroeste",
                "insolacion": "Alta",
                "condicion_termica": "Elevada radiación vespertina",
                "aplicacion": "Sectores cálidos durante la tarde."

            }

        else:

            diagnostico = {

                "orientacion": "Plano",
                "insolacion": "Sin orientación dominante",
                "condicion_termica": "No aplicable",
                "aplicacion": "Superficies prácticamente horizontales."

            }

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN DE ORIENTACIONES")
        escribir("=" * 40)

        for clase in resultados:

            escribir(

                f"{clase['nombre']:<20}"

                f"{clase['porcentaje']:>6.2f} %"

            )

        escribir("")
        escribir("=" * 40)
        escribir("DIAGNÓSTICO")
        escribir("=" * 40)

        escribir(f"Orientación: {diagnostico['orientacion']}")
        escribir(f"Insolación: {diagnostico['insolacion']}")
        escribir(f"Condición térmica: {diagnostico['condicion_termica']}")
        escribir(f"Aplicación: {diagnostico['aplicacion']}")

        return {

            "clases": resultados,

            "clase_predominante": clase_predominante,

            "diagnostico": diagnostico,

            "interpretacion": {}

        }

    # =====================================================
    # INTERPRETAR TRI
    # =====================================================

    def interpretar_tri(ruta_raster):

        array = leer_raster_array(ruta_raster)

        # --- 1. LIMPIEZA EXTREMA ---
        array = array[np.isfinite(array)]
        array = array[~np.isclose(array, -9999)]

        total = array.size

        # 2. Como ya no hay NaNs, podemos usar mean y std normales
        media = np.mean(array)
        desvio = np.std(array)

        clases = [

            ("Muy bajo", 0, 2),

            ("Bajo", 2, 5),

            ("Moderado", 5, 10),

            ("Alto", 10, 20),

            ("Muy alto", 20, np.inf)

        ]

        resultados = []

        for nombre, inicio, fin in clases:

            mascara = (

                (array >= inicio)

                &

                (array < fin)

            )

            cantidad = np.count_nonzero(mascara)

            porcentaje = (

                cantidad /

                total

            ) * 100

            resultados.append({

                "nombre": nombre,

                "cantidad": cantidad,

                "porcentaje": porcentaje

            })
        clase_predominante = max(

            resultados,

            key=lambda x: x["porcentaje"]

        )

        if clase_predominante["nombre"] == "Muy bajo":

            diagnostico = {

                "rugosidad": "Muy baja",

                "estabilidad": "Muy alta",

                "aptitud": "Excelente para urbanización y agricultura"

            }

        elif clase_predominante["nombre"] == "Bajo":

            diagnostico = {

                "rugosidad": "Baja",

                "estabilidad": "Alta",

                "aptitud": "Muy favorable para usos antrópicos"

            }

        elif clase_predominante["nombre"] == "Moderado":

            diagnostico = {

                "rugosidad": "Media",

                "estabilidad": "Media",

                "aptitud": "Requiere planificación del uso del suelo"

            }

        elif clase_predominante["nombre"] == "Alto":

            diagnostico = {

                "rugosidad": "Alta",

                "estabilidad": "Baja",

                "aptitud": "Limitaciones para infraestructura"

            }

        else:

            diagnostico = {

                "rugosidad": "Muy alta",

                "estabilidad": "Muy baja",

                "aptitud": "Área de conservación o uso restringido"

            }

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN TRI")
        escribir("=" * 40)

        for clase in resultados:

            escribir(

                f"{clase['nombre']:<20}"

                f"{clase['porcentaje']:>6.2f} %"

            )

        escribir("")
        escribir("=" * 40)
        escribir("DIAGNÓSTICO")
        escribir("=" * 40)

        escribir(f"Rugosidad: {diagnostico['rugosidad']}")
        escribir(f"Estabilidad: {diagnostico['estabilidad']}")
        escribir(f"Aptitud: {diagnostico['aptitud']}")

        return {

            "clases": resultados,

            "clase_predominante": clase_predominante,

            "diagnostico": diagnostico,

            "interpretacion": {}

        }

    # =====================================================
    # INTERPRETAR TPI
    # =====================================================

    def interpretar_tpi(ruta_raster):

        array = leer_raster_array(ruta_raster)

        # --- 1. LIMPIEZA EXTREMA (Igual que en estadísticas) ---
        array = array[np.isfinite(array)]
        array = array[~np.isclose(array, -9999)]

        total = array.size

        # 2. Como ya no hay NaNs, podemos usar mean y std normales
        media = np.mean(array)
        desvio = np.std(array)

        clases = [

            ("Valle",
            -np.inf,
            media - desvio),

            ("Ladera baja",
            media - desvio,
            media - (desvio * 0.5)),

            ("Plano",
            media - (desvio * 0.5),
            media + (desvio * 0.5)),

            ("Ladera alta",
            media + (desvio * 0.5),
            media + desvio),

            ("Cumbre",
            media + desvio,
            np.inf)

        ]

        resultados = []

        for nombre, inicio, fin in clases:

            mascara = (

                (array >= inicio)

                &

                (array < fin)

            )

            cantidad = np.count_nonzero(

                mascara

            )

            porcentaje = (

                cantidad /

                total

            ) * 100

            resultados.append(

                {

                    "nombre": nombre,

                    "cantidad": cantidad,

                    "porcentaje": porcentaje

                }

            )

        clase_predominante = max(

            resultados,

            key=lambda x: x["porcentaje"]

        )

        if clase_predominante["nombre"] == "Valle":

            diagnostico = {

                "posicion": "Depresión",

                "drenaje": "Muy alto",

                "aptitud": "Acumulación de humedad y sedimentos"

            }

        elif clase_predominante["nombre"] == "Ladera baja":

            diagnostico = {

                "posicion": "Pie de ladera",

                "drenaje": "Alto",

                "aptitud": "Zona de transición y escurrimiento"

            }

        elif clase_predominante["nombre"] == "Plano":

            diagnostico = {

                "posicion": "Superficie estable",

                "drenaje": "Moderado",

                "aptitud": "Condiciones favorables para usos antrópicos"

            }

        elif clase_predominante["nombre"] == "Ladera alta":

            diagnostico = {

                "posicion": "Ladera superior",

                "drenaje": "Bueno",

                "aptitud": "Mayor exposición y susceptibilidad a erosión"

            }

        else:

            diagnostico = {

                "posicion": "Cumbre",

                "drenaje": "Muy bueno",

                "aptitud": "Máxima exposición al viento y erosión"

            }

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN TPI")
        escribir("=" * 40)

        for clase in resultados:

            escribir(

                f"{clase['nombre']:<20}"

                f"{clase['porcentaje']:>6.2f} %"

            )

        escribir("")
        escribir("=" * 40)
        escribir("DIAGNÓSTICO")
        escribir("=" * 40)

        escribir(f"Posición: {diagnostico['posicion']}")
        escribir(f"Drenaje: {diagnostico['drenaje']}")
        escribir(f"Aptitud: {diagnostico['aptitud']}")

        return {

            "clases": resultados,

            "clase_predominante": clase_predominante,

            "diagnostico": diagnostico,

            "interpretacion": {}

        }

    # =====================================================
    # INTERPRETAR CURVATURA
    # =====================================================

    def interpretar_curvatura(ruta_raster):

        array = leer_raster_array(ruta_raster)

        # --- 1. LIMPIEZA EXTREMA ---
        array = array[np.isfinite(array)]
        array = array[~np.isclose(array, -9999)]

        total = array.size

        # 2. Como ya no hay NaNs, podemos usar mean y std normales
        media = np.mean(array)
        desvio = np.std(array)

        limite1 = desvio
        limite2 = desvio * 2

        clases = [

            ("Muy cóncava", -9999, media - limite2),

            ("Cóncava", media - limite2, media - limite1),

            ("Plana", media - limite1, media + limite1),

            ("Convexa", media + limite1, media + limite2),

            ("Muy convexa", media + limite2, 9999)

        ]

        resultados = []

        for nombre, minimo, maximo in clases:

            mascara = (

                (array >= minimo)

                &

                (array < maximo)

            )

            cantidad = np.count_nonzero(mascara)

            porcentaje = (

                cantidad /

                total

            ) * 100

            resultados.append(

                {

                    "nombre": nombre,

                    "cantidad": cantidad,

                    "porcentaje": porcentaje

                }

            )

        clase_predominante = max(

            resultados,

            key=lambda x: x["porcentaje"]

        )

        # =====================================================
        # DIAGNÓSTICO
        # =====================================================

        if clase_predominante["nombre"] == "Muy cóncava":

            diagnostico = {

                "drenaje": "Concentración intensa del escurrimiento",
                "estabilidad": "Baja",
                "aptitud": "Sectores propensos a acumulación de agua y sedimentos"

            }

        elif clase_predominante["nombre"] == "Cóncava":

            diagnostico = {

                "drenaje": "Concentración moderada del escurrimiento",
                "estabilidad": "Media",
                "aptitud": "Áreas favorables para acumulación de humedad"

            }

        elif clase_predominante["nombre"] == "Plana":

            diagnostico = {

                "drenaje": "Equilibrado",
                "estabilidad": "Alta",
                "aptitud": "Condiciones favorables para usos antrópicos"

            }

        elif clase_predominante["nombre"] == "Convexa":

            diagnostico = {

                "drenaje": "Dispersión moderada del escurrimiento",
                "estabilidad": "Media",
                "aptitud": "Sectores bien drenados"

            }

        else:

            diagnostico = {

                "drenaje": "Dispersión intensa del escurrimiento",
                "estabilidad": "Media-Alta",
                "aptitud": "Mayor susceptibilidad a procesos erosivos"

            }

        # =====================================================
        # INTERPRETACIÓN
        # =====================================================

        interpretacion = {

            "titulo": "CURVATURA",

            "predominante": clase_predominante["nombre"]

        }

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN CURVATURA")
        escribir("=" * 40)

        for clase in resultados:

            escribir(

                f"{clase['nombre']:<20}"

                f"{clase['porcentaje']:>6.2f} %"

            )

        escribir("")
        escribir("=" * 40)
        escribir("DIAGNÓSTICO")
        escribir("=" * 40)

        escribir(f"Drenaje: {diagnostico['drenaje']}")
        escribir(f"Estabilidad: {diagnostico['estabilidad']}")
        escribir(f"Aptitud: {diagnostico['aptitud']}")

        return {

            "clases": resultados,

            "clase_predominante": clase_predominante,

            "diagnostico": diagnostico,

            "interpretacion": {}

        }

    # =====================================================
    # INTERPRETAR IRREGULARIDAD
    # =====================================================

    def interpretar_irregularidad(ruta_raster):

        array = leer_raster_array(ruta_raster)

        # --- 1. LIMPIEZA EXTREMA ---
        array = array[np.isfinite(array)]
        array = array[~np.isclose(array, -9999)]

        total = array.size

        # 2. Como ya no hay NaNs, podemos usar mean y std normales
        media = np.mean(array)
        desvio = np.std(array)


        limite1 = desvio
        limite2 = desvio * 2

        clases = [

            ("Muy baja", -9999, media - limite2),

            ("Baja", media - limite2, media - limite1),

            ("Media", media - limite1, media + limite1),

            ("Alta", media + limite1, media + limite2),

            ("Muy alta", media + limite2, 9999)

        ]

        resultados = []

        for nombre, minimo, maximo in clases:

            mascara = (

                (array >= minimo)

                &

                (array < maximo)

            )

            cantidad = np.count_nonzero(mascara)

            porcentaje = (

                cantidad /

                total

            ) * 100

            resultados.append(

                {

                    "nombre": nombre,

                    "cantidad": cantidad,

                    "porcentaje": porcentaje

                }

            )

        clase_predominante = max(

            resultados,

            key=lambda x: x["porcentaje"]

        )

        # =====================================================
        # DIAGNÓSTICO
        # =====================================================

        if clase_predominante["nombre"] == "Muy baja":

            diagnostico = {

                "relieve": "Muy homogéneo",
                "estabilidad": "Muy alta",
                "aptitud": "Condiciones muy favorables para usos antrópicos"

            }

        elif clase_predominante["nombre"] == "Baja":

            diagnostico = {

                "relieve": "Suavemente irregular",
                "estabilidad": "Alta",
                "aptitud": "Buenas condiciones para ocupación y circulación"

            }

        elif clase_predominante["nombre"] == "Media":

            diagnostico = {

                "relieve": "Moderadamente irregular",
                "estabilidad": "Media",
                "aptitud": "Condiciones intermedias"

            }

        elif clase_predominante["nombre"] == "Alta":

            diagnostico = {

                "relieve": "Accidentado",
                "estabilidad": "Media-Baja",
                "aptitud": "Mayor susceptibilidad a procesos erosivos"

            }

        else:

            diagnostico = {

                "relieve": "Muy accidentado",
                "estabilidad": "Baja",
                "aptitud": "Limitaciones importantes para usos antrópicos"

            }

        # =====================================================
        # INTERPRETACIÓN
        # =====================================================

        interpretacion = {

            "titulo": "IRREGULARIDAD",

            "predominante": clase_predominante["nombre"]

        }

        escribir("")
        escribir("=" * 40)
        escribir("CLASIFICACIÓN IRREGULARIDAD")
        escribir("=" * 40)

        for clase in resultados:

            escribir(

                f"{clase['nombre']:<20}"

                f"{clase['porcentaje']:>6.2f} %"

            )

        escribir("")
        escribir("=" * 40)
        escribir("DIAGNÓSTICO")
        escribir("=" * 40)

        escribir(f"Relieve: {diagnostico['relieve']}")
        escribir(f"Estabilidad: {diagnostico['estabilidad']}")
        escribir(f"Aptitud: {diagnostico['aptitud']}")

        return {

            "clases": resultados,

            "clase_predominante": clase_predominante,

            "diagnostico": diagnostico,

            "interpretacion": {}

        }

    # =====================================================
    # REPROYECCIÓN
    # =====================================================

    def reproyectar_dem(archivo_entrada):

        archivo_salida = archivo_entrada

        if EPSG_DESTINO:

            archivo_reproyectado = os.path.join(
                tempfile.gettempdir(),
                f"{NOMBRE_RESULTADO}_EPSG{EPSG_DESTINO.split(':')[1]}{EXTENSION_RASTER}"
            )

            gdal.Warp(
                archivo_reproyectado,
                archivo_entrada,
                dstSRS=EPSG_DESTINO,
                resampleAlg="bilinear",
                srcNodata=NODATA,
                dstNodata=NODATA,
                xRes=RESOLUCION,
                yRes=RESOLUCION,
                targetAlignedPixels=True
            )

            archivo_salida = archivo_reproyectado

        return archivo_salida

    # =====================================================
    # PRODUCTOS DERIVADOS DEM
    # =====================================================

    def generar_derivados_dem(archivo_raster):

        if PRODUCTO == "DEM":
            return archivo_raster

        # =====================================================
        # CASOS ESPECIALES (Parámetros únicos)
        # =====================================================

        elif PRODUCTO == "DEM_RELIEVE":
            if HILLSHADE:
                archivo_hillshade = os.path.join(
                    tempfile.gettempdir(),
                    f"{NOMBRE_RESULTADO}_Hillshade{EXTENSION_RASTER}"
                )
                processing.run(
                    "gdal:hillshade",
                    {
                        "INPUT": archivo_raster,
                        "BAND": 1,
                        "Z_FACTOR": 1,
                        "SCALE": 1,
                        "AZIMUTH": 315,
                        "ALTITUDE": 45,
                        "COMBINED": False,
                        "MULTIDIRECTIONAL": True,
                        "COMPUTE_EDGES": True,
                        "ZEVENBERGEN": False,
                        "OUTPUT": archivo_hillshade
                    }
                )
                return archivo_hillshade
            return archivo_raster

        elif PRODUCTO == "CURVATURA":
            archivo_curvatura = os.path.join(
                tempfile.gettempdir(),
                f"Curvatura_{NOMBRE_CAPA}_{FECHA_INICIO[:7].replace('-', '_')}{EXTENSION_RASTER}"
            )
            processing.run(
                "grass:r.slope.aspect",
                {
                    "elevation": archivo_raster,
                    "format": 0,
                    "precision": 2,
                    "-a": False, "-e": False, "-n": False,
                    "zscale": 1,
                    "min_slope": 0,
                    "slope": "TEMPORARY_OUTPUT",
                    "aspect": "TEMPORARY_OUTPUT",
                    "pcurvature": archivo_curvatura,
                    "tcurvature": "TEMPORARY_OUTPUT",
                    "dx": "TEMPORARY_OUTPUT",
                    "dy": "TEMPORARY_OUTPUT",
                    "dxx": "TEMPORARY_OUTPUT",
                    "dyy": "TEMPORARY_OUTPUT",
                    "dxy": "TEMPORARY_OUTPUT",
                    "GRASS_REGION_PARAMETER": None,
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0,
                    "GRASS_RASTER_FORMAT_OPT": "",
                    "GRASS_RASTER_FORMAT_META": ""
                }
            )
            return archivo_curvatura

        # =====================================================
        # CASOS ESTANDARIZADOS (GDAL)
        # =====================================================

        else:

            # Diccionario que enlaza el producto con su algoritmo en QGIS
            ALGORITMOS_GDAL = {
                "PENDIENTE": "gdal:slope",
                "ASPECT": "gdal:aspect",
                "TRI": "gdal:triterrainruggednessindex",
                "TPI": "gdal:tpitopographicpositionindex",
                "IRREGULARIDAD": "gdal:roughness"
            }

            if PRODUCTO in ALGORITMOS_GDAL:

                algoritmo = ALGORITMOS_GDAL[PRODUCTO]

                # Ajustamos el prefijo para que respete tu nomenclatura (ej: "Pendiente" o "TRI")
                if PRODUCTO in ["TRI", "TPI"]:
                    prefijo = PRODUCTO
                else:
                    prefijo = PRODUCTO.capitalize()

                archivo_salida = os.path.join(
                    tempfile.gettempdir(),
                    f"{prefijo}_{NOMBRE_CAPA}_{FECHA_INICIO[:7].replace('-', '_')}{EXTENSION_RASTER}"
                )

                processing.run(
                    algoritmo,
                    {
                        "INPUT": archivo_raster,
                        "BAND": 1,
                        "OUTPUT": archivo_salida
                    }
                )

                return archivo_salida

        return archivo_raster

    # =====================================================
    # VALIDAR REGLAS TEMPORALES
    # =====================================================

    fecha_inicio_dt = datetime.strptime(
        FECHA_INICIO,
        "%Y-%m-%d"
    )

    fecha_fin_dt = datetime.strptime(
        FECHA_FIN,
        "%Y-%m-%d"
    )

    fuentes_validas = []

    if PRODUCTO in REGLAS_TEMPORALES:
        for regla in REGLAS_TEMPORALES[PRODUCTO]:

            inicio = datetime.strptime(
                regla["inicio"],
                "%Y-%m-%d"
            )

            if regla["fin"] is None:

                fin = datetime.max

            else:

                fin = datetime.strptime(
                    regla["fin"],
                    "%Y-%m-%d"
                )

            if (

                fecha_inicio_dt >= inicio

                and

                fecha_fin_dt <= fin

            ):

                fuentes_validas.append(
                    regla["fuente"]
                )

    if PRODUCTO in REGLAS_TEMPORALES and len(fuentes_validas) == 0:

        texto_error = (

            "El período seleccionado no pertenece "
            "completamente a una única fuente satelital.\n\n"

            "Períodos disponibles para "

            f"{PRODUCTO}:\n\n"

        )

        for regla in REGLAS_TEMPORALES[PRODUCTO]:

            fin = regla["fin"]

            if fin is None:

                fin = "Actualidad"

            texto_error += (

                f"• {regla['fuente']}: "

                f"{regla['inicio']} → {fin}\n"

            )

        raise Exception(

            texto_error

        )

    # =====================================================
    # CONEXIÓN
    # =====================================================

    ee.Initialize()

    # =====================================================
    # OBTENER CAPA
    # =====================================================

    capas = QgsProject.instance().mapLayersByName(NOMBRE_CAPA)

    if not capas:
        raise Exception(f"La capa '{NOMBRE_CAPA}' no existe en el proyecto.")

    capa = capas[0]

    # =====================================================
    # VALIDAR CONFIGURACIÓN
    # =====================================================

    if PRODUCTO not in PRODUCTOS:
        raise Exception(
            f"El producto '{PRODUCTO}' no existe.\n"
            f"Productos disponibles: {', '.join(PRODUCTOS.keys())}"
        )

    # =====================================================
    # OBTENER GEOMETRÍA
    # =====================================================

    cantidad_features = capa.featureCount()

    if cantidad_features == 0:
        raise Exception(f"La capa '{NOMBRE_CAPA}' no tiene ningún polígono cargado.")

    if cantidad_features > 1:
        raise Exception(
            f"La capa '{NOMBRE_CAPA}' tiene {cantidad_features} polígonos. "
            "Este motor está pensado para un único polígono de área de estudio. "
            "Unificá los polígonos (Vector > Herramientas de geoproceso > Unir) "
            "o elegí una capa con un solo polígono antes de ejecutar."
        )

    feature = next(capa.getFeatures())

    geometria = feature.geometry()

    # Reproyectamos a EPSG:4326 (grados) antes de mandar a Earth Engine,
    # que siempre interpreta las coordenadas del GeoJSON como si fueran
    # lat/lon en WGS84. Si la capa ya está en 4326, esto no cambia nada;
    # si está en una proyección métrica (ej. POSGAR/Gauss-Krüger), evita
    # que se manden metros donde se esperan grados.
    crs_capa = capa.crs()
    crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")

    if crs_capa != crs_4326:
        transformador = QgsCoordinateTransform(
            crs_capa, crs_4326, QgsProject.instance()
        )
        geometria.transform(transformador)

    centroide = geometria.centroid().asPoint()

    # =====================================================
    # CREAR ROI (EARTH ENGINE)
    # =====================================================

    geojson = json.loads(geometria.asJson())

    roi = ee.Geometry(geojson)

    # =====================================================
    # RESOLVER REGLAS TEMPORALES
    # =====================================================

    fecha = datetime.strptime(FECHA_INICIO, "%Y-%m-%d")

    reglas = REGLAS_TEMPORALES.get(PRODUCTO)

    # =====================================================
    # RESOLVER PRODUCTO
    # ===================================================== 

    config = PRODUCTOS[PRODUCTO]

    GUARDAR_ESTILO = config.get("guardar_estilo", False)

    # ==========================================
    # RESOLVER FUENTE
    # ==========================================

    if reglas:

        FUENTE = None

        for regla in reglas:

            inicio = datetime.strptime(regla["inicio"], "%Y-%m-%d")

            fin = (
                datetime.max
                if regla["fin"] is None
                else datetime.strptime(regla["fin"], "%Y-%m-%d")
            )

            if inicio <= fecha <= fin:

                FUENTE = regla["fuente"]
                break

        if FUENTE is None:

            raise Exception(
                "No existe una fuente válida para la fecha seleccionada."
            )

    else:

        FUENTE = config["fuente"]


    if "banda" in config:

        BANDA = config["banda"]

    TIPO = config["tipo"]

    METODO = config["metodo"]

    ESTILO = ESTILOS[config["estilo"]]

    # =====================================================
    # CONFIGURAR CONTRASTE
    # =====================================================

    CONTRASTE = ESTILO.get("contraste", None)

    if CONTRASTE:

        MODO_CONTRASTE = CONTRASTE["modo"]

        if MODO_CONTRASTE == "cumulative":

            MIN_CONTRASTE = CONTRASTE["min"]
            MAX_CONTRASTE = CONTRASTE["max"]

    # =====================================================
    # CONFIGURAR HILLSHADE
    # =====================================================

    HILLSHADE = config.get("hillshade", False)

    TIPO_ESTILO = ESTILO["tipo"]

    # Parámetros exclusivos para pseudocolor
    if TIPO_ESTILO == "pseudocolor":

        COLORES = ESTILO["colores"]

    # =====================================================
    # OBTENER FUENTE
    # =====================================================

    config_fuente = FUENTES[FUENTE]

    ID_FUENTE = config_fuente["id"]
    TIPO_FUENTE = config_fuente["tipo"]
    RESOLUCION = config_fuente["resolucion"]

    # =====================================================
    # BANDAS ESPECTRALES
    # =====================================================

    BANDAS = config_fuente.get("bandas", {})

    BANDA_ROJA = BANDAS.get("RED")
    BANDA_VERDE = BANDAS.get("GREEN")
    BANDA_AZUL = BANDAS.get("BLUE")
    BANDA_NIR = BANDAS.get("NIR")
    BANDA_SWIR1 = BANDAS.get("SWIR1")
    BANDA_SWIR2 = BANDAS.get("SWIR2")

    FACTOR_ESCALA = config_fuente.get("factor_escala", 1)
    OFFSET = config_fuente.get("offset", 0)

    # =====================================================
    # PROCESAR FUENTE
    # =====================================================

    if TIPO_FUENTE == "coleccion":

        coleccion = ee.ImageCollection(ID_FUENTE)


    else:

        raise Exception("Tipo de fuente no implementado.")

    # =====================================================
    # PROCESAR COLECCIONES
    # =====================================================

    if TIPO_FUENTE == "coleccion":

        # -----------------------------------------
        # PRODUCTOS TEMPORALES (Sentinel, Landsat)
        # -----------------------------------------

        if METODO == "normalizedDifference":

            coleccion = coleccion.filterBounds(roi)

            coleccion = coleccion.filterDate(
                FECHA_INICIO,
                FECHA_FIN
            )

            ATRIBUTO_NUBOSIDAD = config_fuente["nubosidad"]

            coleccion = coleccion.filter(
                ee.Filter.lte(
                    ATRIBUTO_NUBOSIDAD,
                    NUBOSIDAD_MAXIMA
                )
            )

            print(f"Fuente seleccionada: {FUENTE}")
            print(f"Colección: {ID_FUENTE}")

            cantidad = coleccion.size().getInfo()

            if cantidad == 0:

                raise Exception(
                    "No se encontraron imágenes para los filtros seleccionados.\n"
                    "Revise:\n"
                    "- rango de fechas\n"
                    "- nubosidad máxima\n"
                    "- área de estudio"
                )

            # ==========================================
            # MÁSCARA LANDSAT
            # ==========================================

            if FUENTE in [
                "LANDSAT_5",
                "LANDSAT_8",
                "LANDSAT_9"
            ]:

                coleccion = coleccion.map(
                    aplicar_mascara_landsat
                )

            elif FUENTE == "COPERNICUS_S2":

                coleccion = coleccion.map(
                    aplicar_mascara_sentinel
                )

            imagen = coleccion.median()

            # =====================================================
            # BANDAS DEL PRODUCTO
            # =====================================================

            BANDA_A, BANDA_B = PRODUCTOS[PRODUCTO]["bandas"]

            banda_a = (
                imagen
                .select(BANDAS[BANDA_A])
                .multiply(FACTOR_ESCALA)
                .add(OFFSET)
            )

            banda_b = (
                imagen
                .select(BANDAS[BANDA_B])
                .multiply(FACTOR_ESCALA)
                .add(OFFSET)
            )

            denominador = banda_a.add(banda_b)

            # 1. Calcular el índice
            resultado = banda_a.subtract(banda_b).divide(denominador)

            # 2. Enmascarar de forma estricta TODO lo que salga del rango físico
            resultado = resultado.updateMask(
                resultado.gte(-1.0).And(resultado.lte(1.0))
            )

            # 3. Asignar explícitamente NODATA a los píxeles problemáticos antes de exportar
            resultado = resultado.unmask(NODATA)

            resultado = resultado.toFloat()

            # 4. Recuperar la cantidad de imágenes procesadas
            CANTIDAD_IMAGENES = coleccion.size().getInfo()

        elif METODO == "EBBI":

            coleccion = coleccion.filterBounds(roi)

            coleccion = coleccion.filterDate(
                FECHA_INICIO,
                FECHA_FIN
            )

            ATRIBUTO_NUBOSIDAD = config_fuente["nubosidad"]

            coleccion = coleccion.filter(
                ee.Filter.lte(
                    ATRIBUTO_NUBOSIDAD,
                    NUBOSIDAD_MAXIMA
                )
            )

            cantidad = coleccion.size().getInfo()

            if cantidad == 0:
                raise Exception("No se encontraron imágenes térmicas para el EBBI en este período. Revisá la nubosidad o probá con otro año.")

            if FUENTE in [
                "LANDSAT_5",
                "LANDSAT_8",
                "LANDSAT_9"
            ]:
                coleccion = coleccion.map(
                    aplicar_mascara_landsat
                )

            elif FUENTE == "COPERNICUS_S2":
                coleccion = coleccion.map(
                    aplicar_mascara_sentinel
                )

            imagen = coleccion.median()

            # 1. Ópticas en porcentaje (0-100) para estabilizar la fórmula
            nir = (
                imagen
                .select(BANDAS["NIR"])
                .multiply(FACTOR_ESCALA)
                .add(OFFSET)
                .multiply(100)
            )

            swir1 = (
                imagen
                .select(BANDAS["SWIR1"])
                .multiply(FACTOR_ESCALA)
                .add(OFFSET)
                .multiply(100)
            )

            # 2. Térmica en Celsius reales
            termica = (
                imagen
                .select(BANDAS["THERMAL"])
                .multiply(0.00341802)
                .add(149.0)
                .subtract(273.15)
            )

            # =====================================================
            # CÁLCULO DEL EBBI
            # =====================================================

            numerador = swir1.subtract(nir)
            denominador = swir1.add(termica).sqrt().multiply(10)

            # Escudo contra divisiones por cero
            denominador_seguro = denominador.where(denominador.eq(0), 0.00001)

            resultado = numerador.divide(denominador_seguro)

            # Forzamos el rango lógico para evitar píxeles fugados
            resultado = resultado.clamp(-1.0, 1.0)

            # Relleno de huecos chicos: CFMask a veces confunde techos y
            # asfalto claro con nube (falso positivo), y como EBBI resalta
            # justo zonas urbanas, es el índice más afectado por esos
            # agujeros puntuales. Rellenamos con el promedio de los
            # píxeles vecinos válidos — esto NO tapa nubes reales (esas
            # cubren áreas mucho más grandes que el radio del relleno),
            # solo parcha agujeros de unos pocos píxeles sueltos.
            relleno_vecinos = resultado.focalMean(
                radius=1.5,
                kernelType="circle",
                units="pixels"
            )
            resultado = resultado.unmask(relleno_vecinos)

            resultado = resultado.unmask(NODATA).toFloat()

            # 4. Recuperar la cantidad de imágenes procesadas
            CANTIDAD_IMAGENES = coleccion.size().getInfo()

        elif METODO == "MSAVI":

            coleccion = coleccion.filterBounds(roi).filterDate(FECHA_INICIO, FECHA_FIN)
            coleccion = coleccion.filter(ee.Filter.lte(config_fuente["nubosidad"], NUBOSIDAD_MAXIMA))
            cantidad = coleccion.size().getInfo()

            if cantidad == 0:
                raise Exception("No se encontraron imágenes para el MSAVI.")

            if FUENTE in ["LANDSAT_5", "LANDSAT_8", "LANDSAT_9"]:
                coleccion = coleccion.map(aplicar_mascara_landsat)
            elif FUENTE == "COPERNICUS_S2":
                coleccion = coleccion.map(aplicar_mascara_sentinel)

            imagen = coleccion.median()

            nir = imagen.select(BANDAS["NIR"]).multiply(FACTOR_ESCALA).add(OFFSET)
            red = imagen.select(BANDAS["RED"]).multiply(FACTOR_ESCALA).add(OFFSET)

            # Fórmula MSAVI: (2 * NIR + 1 - sqrt((2 * NIR + 1)^2 - 8 * (NIR - RED))) / 2
            nir_x2_mas_1 = nir.multiply(2).add(1)
            termino1 = nir_x2_mas_1.pow(2)
            termino2 = nir.subtract(red).multiply(8)

            resultado = (
                nir_x2_mas_1.subtract(
                    termino1.subtract(termino2).sqrt()
                )
            ).divide(2)

            resultado = resultado.updateMask(resultado.gte(-1.0).And(resultado.lte(1.0)))
            resultado = resultado.unmask(NODATA).toFloat()
            CANTIDAD_IMAGENES = cantidad

        elif METODO == "LST":

            coleccion = coleccion.filterBounds(roi).filterDate(FECHA_INICIO, FECHA_FIN)
            coleccion = coleccion.filter(ee.Filter.lte(config_fuente["nubosidad"], NUBOSIDAD_MAXIMA))
            cantidad = coleccion.size().getInfo()

            if cantidad == 0:
                raise Exception("No se encontraron imágenes térmicas para el LST.")

            if FUENTE in ["LANDSAT_5", "LANDSAT_8", "LANDSAT_9"]:
                coleccion = coleccion.map(aplicar_mascara_landsat)

            imagen = coleccion.median()
            termica = imagen.select(BANDAS["THERMAL"])

            # Fórmula Landsat Collection 2: (Banda_Termica * 0.00341802) + 149.0 - 273.15
            resultado = termica.multiply(0.00341802).add(149.0).subtract(273.15)

            resultado = resultado.unmask(NODATA).toFloat()
            CANTIDAD_IMAGENES = cantidad

        elif METODO == "clasificacion_ia":

            coleccion = coleccion.filterBounds(roi).filterDate(FECHA_INICIO, FECHA_FIN)
            cantidad = coleccion.size().getInfo()

            if cantidad == 0:
                raise Exception("No se encontraron clasificaciones de uso de suelo para este período.")

            # Extraemos el valor más frecuente (la moda) para estabilizar la clasificación en el tiempo
            imagen = coleccion.select(BANDA).mode()

            resultado = imagen.unmask(NODATA).toFloat()
            CANTIDAD_IMAGENES = cantidad

        elif METODO == "suma_temporal":

            coleccion = coleccion.filterBounds(roi).filterDate(FECHA_INICIO, FECHA_FIN)
            cantidad = coleccion.size().getInfo()

            if cantidad == 0:
                raise Exception("No se encontraron datos climáticos para este período.")

            # ATENCIÓN ACÁ: Usamos .sum() para acumular todos los milímetros del período
            imagen = coleccion.select(BANDA).sum()

            resultado = imagen.clip(roi).unmask(NODATA).toFloat()
            CANTIDAD_IMAGENES = cantidad

        elif METODO == "viento_vectorial":

            coleccion = coleccion.filterBounds(roi).filterDate(FECHA_INICIO, FECHA_FIN)
            cantidad = coleccion.size().getInfo()

            if cantidad == 0:
                raise Exception("No se encontraron datos de viento (ERA5) para este período.")

            # 1. Promediamos las componentes U y V
            u_mean = coleccion.select('u_component_of_wind_10m').mean()
            v_mean = coleccion.select('v_component_of_wind_10m').mean()

            # 2. Calculamos la velocidad real para dibujar el Raster (Teorema de Pitágoras)
            velocidad = u_mean.pow(2).add(v_mean.pow(2)).sqrt().rename('velocidad')
            resultado = velocidad.clip(roi).unmask(NODATA).toFloat()
            CANTIDAD_IMAGENES = cantidad

            # 3. Extraemos los vectores del polígono para la Rosa de los Vientos
            stats_vector = u_mean.addBands(v_mean).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=11132
            ).getInfo()

            u_val = stats_vector.get('u_component_of_wind_10m')
            v_val = stats_vector.get('v_component_of_wind_10m')

            # 4. Calculamos la dirección meteorológica en grados
            angulo_math = math.degrees(math.atan2(v_val, u_val))
            dir_meteo = (270 - angulo_math) % 360

            sectores = ["Norte", "Noreste", "Este", "Sureste", "Sur", "Suroeste", "Oeste", "Noroeste", "Norte"]
            indice = int(round(dir_meteo / 45))

            # Guardamos el dato en una variable global para el JSON
            global ROSA_VIENTOS
            ROSA_VIENTOS = f"{sectores[indice]} ({dir_meteo:.1f}°)"

        # -----------------------------------------
        # COLECCIONES ESPACIALES (Copernicus DEM)
        # -----------------------------------------

        elif METODO == "banda":

            coleccion = coleccion.filterBounds(roi)

            cantidad = coleccion.size().getInfo()

            if cantidad == 0:

                raise Exception(
                    "No se encontraron teselas del DEM."
                )

            imagen = coleccion.mosaic()

            resultado = imagen.select(BANDA)

        else:

            raise Exception(
                f"Método '{METODO}' no implementado."
            )


        resultado = resultado.rename(PRODUCTO)

    # =====================================================
    # RECORTAR AL ÁREA DE ESTUDIO
    # =====================================================

    resultado = resultado.clip(roi)

    resultado = resultado.rename(PRODUCTO)

    resultado = resultado.toFloat()

    # =====================================================
    # [NUEVO] BIFURCACIÓN MODO DRIVE
    # Se corta ACÁ, antes de getDownloadURL — que es lo que
    # rompía con áreas grandes tipo Singapur. "Directo" no
    # pasa por acá, sigue exactamente como estaba.
    #
    # Cubre TODOS los índices, ambas coberturas, lluvia (CHIRPS)
    # y viento (ERA5) — todos llegan a este punto con CANTIDAD_
    # IMAGENES y FUENTE ya resueltos, y su cálculo es 100% server-
    # side en Earth Engine.
    #
    # DEM queda afuera A PROPÓSITO, no por descuido: sus 7 deri-
    # vados (Pendiente, Aspecto, TRI, TPI, Curvatura, Irregulari-
    # dad, Relieve) se calculan con GDAL/GRASS LOCALMENTE sobre
    # el archivo ya descargado — no existen del lado de Earth
    # Engine. Meterlos acá los rompería en silencio. Sigue
    # funcionando exactamente como antes, sin cambios.
    # =====================================================

    PRODUCTOS_DEM = [
        "DEM", "DEM_RELIEVE", "PENDIENTE", "ASPECT",
        "TRI", "TPI", "CURVATURA", "IRREGULARIDAD",
    ]

    if EXPORTAR and MODO_EXPORTACION == "drive" and PRODUCTO not in PRODUCTOS_DEM:
        return ejecutar_modo_drive(resultado, roi)

    # =====================================================
    # OBTENER URL DE DESCARGA
    # =====================================================

    url = resultado.getDownloadURL({
        "scale": RESOLUCION,
        "region": roi,
        "format": FORMATO_RASTER,
    })

    # =====================================================
    # DESCARGAR RASTER TEMPORAL
    # =====================================================

    archivo_temporal = os.path.join(
        tempfile.gettempdir(),
        f"{NOMBRE_RESULTADO}{EXTENSION_RASTER}"
    )

    # --- NUEVO BLOQUE: ELIMINAR CACHÉ PREVIA ---
    for ext in [EXTENSION_RASTER, f"{EXTENSION_RASTER}.aux.xml"]:
        ruta_cache = os.path.join(tempfile.gettempdir(), f"{NOMBRE_RESULTADO}{ext}")
        if os.path.exists(ruta_cache):
            try:
                os.remove(ruta_cache)
            except Exception:
                pass

    # =====================================================
    # DESCARGAR RASTER
    # =====================================================

    urllib.request.urlretrieve(
        url,
        archivo_temporal
    )

    # --- EL TRUCO DE MAGIA: ETIQUETAR EL NODATA OFICIALMENTE ---
    ds = gdal.Open(archivo_temporal, gdal.GA_Update)
    if ds is not None:
        banda = ds.GetRasterBand(1)
        banda.SetNoDataValue(NODATA)
        banda.FlushCache()
        ds = None

    # =====================================================
    # REPROYECCIÓN DEM
    # =====================================================

    archivo_temporal = reproyectar_dem(archivo_temporal)

    # =====================================================
    # DERIVADOS DEM
    # =====================================================

    archivo_temporal = generar_derivados_dem(archivo_temporal)

    # --- LIMPIEZA FINAL ANTES DE QGIS ---
    depurar_raster(archivo_temporal)

    # =====================================================
    # =====================================================
    # CARGAR RASTER EN QGIS
    # =====================================================

    capa_resultado = QgsRasterLayer(
        archivo_temporal,
        NOMBRE_RESULTADO
    )

    if not capa_resultado.isValid():
        raise Exception("No se pudo cargar el raster en QGIS.")

    # --- NUEVO: FORZAR LA TRANSPARENCIA EN QGIS ---
    provider = capa_resultado.dataProvider()

    # GDAL usa 0 como fondo para el Hillshade, y -9999 para el resto
    valor_nodata = 0 if PRODUCTO == "DEM_RELIEVE" else NODATA

    # Aplicamos el valor transparente directamente a la capa
    provider.setNoDataValue(1, float(valor_nodata))
    # ----------------------------------------------

    provider = capa_resultado.dataProvider() # Puedes borrar tu 'provider = ...' original que estaba más abajo para no repetirlo

    stats = provider.bandStatistics(
        1,
        QgsRasterBandStats.All
    )

    QgsProject.instance().addMapLayer(capa_resultado)

    aplicar_estilo(capa_resultado)

    # =====================================================
    # ANÁLISIS ESTADÍSTICO
    # =====================================================

    # Ahora capturamos el informe explícitamente sin depender de la global
    if CALCULAR_ESTADISTICAS:
        RESULTADOS, INFORME_FINAL = calcular_estadisticas()
    else:
        RESULTADOS = {"mensaje": "Cálculo de estadísticas desactivado"}
        INFORME_FINAL = []

    # =====================================================
    # PREPARAR EXPORTACIÓN
    # =====================================================

    ruta_json_generado = None

    if EXPORTAR:
        carpeta_exportacion = None

        if MODO_EXPORTACION == "directo":
            capa_resultado, carpeta_exportacion = exportar_directo(
                capa_resultado, 
                archivo_temporal, 
                NOMBRE_RESULTADO
            )

        elif MODO_EXPORTACION == "drive":
            exportar_drive()
            # En Drive, como no hay carpeta local de raster, pedimos dónde guardar la doc
            carpeta_exportacion = QFileDialog.getExistingDirectory(
                None,
                "Seleccione una carpeta local para guardar la documentación"
            )

        # Si tenemos una carpeta, generamos los archivos QML, TXT y JSON
        if carpeta_exportacion:
            ruta_json_generado = generar_documentacion(
                capa=capa_resultado,
                ruta_destino=carpeta_exportacion,
                nombre_base=NOMBRE_RESULTADO,
                informe=INFORME_FINAL,
                resultados=RESULTADOS,
                guardar_estilo=GUARDAR_ESTILO
            )

    # =====================================================
    # LEER RESULTADOS ESTRUCTURADOS (DEBUG)
    # =====================================================

    if EXPORTAR and MODO_DEBUG and ruta_json_generado:
        with open(ruta_json_generado, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)

        print()
        print("=" * 40)
        print("JSON CARGADO")
        print("=" * 40)
        for clave, valor in datos.items():
            print(f"{clave}: {valor}")

    print()
    print("=" * 40)
    mensaje("final")

    # Devolvemos lo que necesita la interfaz para armar el informe
    # (estadísticas crudas + ubicación + el texto ya armado del .txt,
    # en vez de que la interfaz reconstruya su propia versión aparte).
    return {
        "resultados": RESULTADOS,
        "producto": PRODUCTO,
        "nombre_capa": NOMBRE_CAPA,
        "centroide_lat": centroide.y(),
        "centroide_lon": centroide.x(),
        "informe_texto": "\n".join(INFORME_FINAL),
    }