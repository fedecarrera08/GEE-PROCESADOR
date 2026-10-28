# =====================================================
# GEE_PROCESADOR_DIALOG.PY
# Ventana del plugin. Se va armando de a un campo por vez.
# Campos actuales: capa, nubosidad, categoría/producto, EPSG
# (solo DEM), y ahora fechas con calendario bloqueado.
# =====================================================

import json
import urllib.request
import urllib.error
from datetime import date, datetime

from qgis.core import QgsProject, QgsWkbTypes, QgsMapLayer, QgsSettings # type: ignore
from qgis.PyQt.QtCore import QDate, Qt # type: ignore
from qgis.PyQt.QtGui import QTextCharFormat, QColor # type: ignore
from qgis.PyQt.QtWidgets import ( # type: ignore
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QPushButton, QButtonGroup, QLineEdit, QDateEdit, QCalendarWidget,
    QRadioButton, QGroupBox, QMessageBox, QApplication, QTabWidget,
    QWidget, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView
)

from .datos import FAMILIAS, PRODUCTOS, REGLAS_TEMPORALES, REFERENCIAS_COLOR, FUENTES, PRESETS_BANDAS
from . import motor

# Clave donde se guarda la API key de Gemini en la configuración local
# de QGIS (QgsSettings). NO viaja con la carpeta del plugin si la
# compartís: vive en el perfil de Windows del usuario que la cargó.
CLAVE_SETTINGS_API_GEMINI = "gee_procesador/gemini_api_key"

MODELO_GEMINI = "gemini-3.5-flash-lite"

# Qué familias de datos.py entran en cada botón de categoría.
CATEGORIAS = {

    "Índices": [
        "VEGETACION", "AGUA", "URBANIZACION",
        "HUMEDAD", "INCENDIOS", "TEMPERATURA", "METEOROLOGIA",
        "TURBIDEZ"
    ],

    "DEM": [
        "RELIEVE"
    ],

    "Coberturas": [
        "USO_SUELO"
    ],

    # Se maneja aparte de FAMILIAS: no es un producto clasificado,
    # es una composición RGB de bandas crudas (ver PRESETS_BANDAS).
    "Bandas": [],
}


def rangos_validos_para(producto):
    """
    Devuelve los rangos de fecha válidos (lista de (date, date_o_None))
    para un producto, según REGLAS_TEMPORALES. Si el producto no está
    ahí por su propio nombre (caso VIENTO_ERA5, que está guardado bajo
    el nombre de su fuente "ERA5_LAND"), busca por la fuente como
    respaldo. Si no hay reglas (ej. productos DEM), devuelve [].
    """

    reglas = REGLAS_TEMPORALES.get(producto)

    if reglas is None:
        fuente = PRODUCTOS.get(producto, {}).get("fuente")
        reglas = REGLAS_TEMPORALES.get(fuente, [])

    rangos = []

    for regla in reglas:
        inicio = datetime.strptime(regla["inicio"], "%Y-%m-%d").date()
        fin = (
            None if regla["fin"] is None
            else datetime.strptime(regla["fin"], "%Y-%m-%d").date()
        )
        rangos.append((inicio, fin))

    return rangos


def formatear_detalle_tecnico(resultados):
    """
    Arma un texto legible (sin llaves, comillas ni comas de JSON) con
    la info técnica del resultado que NO se muestra ya en el resumen
    ni en la tabla de clasificación (para no repetir lo mismo 3 veces).
    Tolera resultados incompletos (ej. la categoría 'Bandas' no tiene
    estadísticas ni interpretación, porque no es una clasificación).
    """

    estadisticas = resultados.get("estadisticas", {})
    interpretacion = resultados.get("interpretacion", {})
    diagnostico = interpretacion.get("diagnostico")

    lineas = []

    fuente = resultados.get("fuente")
    if fuente:
        lineas.append(f"Fuente satelital: {fuente}")

    resolucion = resultados.get("resolucion")
    if resolucion:
        lineas.append(f"Resolución: {resolucion} m")

    epsg = resultados.get("epsg")
    if epsg:
        lineas.append(f"EPSG: {epsg}")

    cantidad_imagenes = resultados.get("cantidad_imagenes")
    if cantidad_imagenes is not None:
        lineas.append(f"Imágenes satelitales procesadas: {cantidad_imagenes}")

    if estadisticas:
        if lineas:
            lineas.append("")
        lineas.append("Estadísticas del ráster:")
        lineas.append(f"  Píxeles analizados: {estadisticas.get('pixeles', '—')}")
        lineas.append(f"  Mínimo: {estadisticas.get('minimo', '—')}")
        lineas.append(f"  Máximo: {estadisticas.get('maximo', '—')}")
        lineas.append(f"  Media: {estadisticas.get('media', '—')}")
        lineas.append(f"  Desvío estándar: {estadisticas.get('desvio', '—')}")

    if diagnostico:
        lineas.append("")
        lineas.append("Lectura automática (umbral fijo, sin IA):")
        lineas.append(f"  {diagnostico}")

    if not lineas:
        return "No hay detalle técnico adicional para este resultado."

    return "\n".join(lineas)


def quitar_diagnosticos(valor):
    """
    Recorre (recursivamente) un dict/list y devuelve una copia sin
    ninguna clave llamada 'diagnostico' — así la IA arma su propia
    lectura a partir de los números crudos, sin ver la interpretación
    heurística vieja calibrada a mano.
    """

    if isinstance(valor, dict):
        return {
            clave: quitar_diagnosticos(subvalor)
            for clave, subvalor in valor.items()
            if clave != "diagnostico"
        }

    if isinstance(valor, list):
        return [quitar_diagnosticos(item) for item in valor]

    return valor


def pedir_interpretacion_gemini(api_key, producto, nombre_capa, lat, lon, resultados, colores=None):
    """
    Llama a la API de Gemini (modelo Flash-Lite, nivel gratuito) con
    las estadísticas crudas + la ubicación, y devuelve el texto de
    interpretación. Tira una excepción con un mensaje claro si algo
    sale mal (sin API key, sin internet, error del servidor, etc.).
    """

    datos_limpios = quitar_diagnosticos(resultados)

    bloque_colores = ""
    if colores:
        lineas_colores = "\n".join(
            f"- {clase}: {color}" for clase, color in colores.items()
        )
        bloque_colores = (
            "\n\nCada clase se ve en el mapa con este color (mencionalo "
            "al hablar de cada clase, para que quien lea sepa qué buscar "
            f"visualmente en el ráster):\n{lineas_colores}\n"
        )

    prompt = (
        "Sos un asistente de teledetección. Te paso el resultado de un "
        "análisis satelital y necesito que lo interpretes para alguien "
        "que no es especialista.\n\n"
        "IMPORTANTE: respondé en texto plano, sin markdown — nada de "
        "asteriscos, numerales, guiones ni ningún otro símbolo de formato.\n\n"
        "Organizá la respuesta en 3 partes cortas, cada una de 1 a 2 "
        "oraciones, sin títulos ni etiquetas, solo un salto de línea "
        "entre cada una:\n"
        "1) Qué predomina en el área (la clase con mayor porcentaje).\n"
        "2) Qué patrón o contraste llama la atención en los datos (por "
        "ejemplo una clase muy chica pero relevante, algo desparejo, o "
        "algo esperable/inesperado dado el contexto geográfico).\n"
        "3) Una lectura breve atada al contexto climático/geográfico de "
        "la zona, según las coordenadas.\n\n"
        f"Producto analizado: {producto}\n"
        f"Capa / área de estudio: {nombre_capa}\n"
        f"Coordenadas del centro del área (lat, lon): {lat}, {lon}\n"
        f"{bloque_colores}\n"
        "No inventes datos que no estén en el JSON.\n\n"
        f"Estadísticas (JSON):\n{json.dumps(datos_limpios, ensure_ascii=False, indent=2)}"
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODELO_GEMINI}:generateContent"
    )

    cuerpo = json.dumps({
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }).encode("utf-8")

    peticion = urllib.request.Request(
        url,
        data=cuerpo,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
    )

    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            cuerpo_respuesta = json.loads(respuesta.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", errors="ignore")
        raise Exception(
            f"Gemini devolvió un error ({error.code}). "
            f"Revisá que la clave de API sea correcta.\nDetalle: {detalle}"
        )

    except urllib.error.URLError as error:
        raise Exception(
            f"No se pudo conectar con Gemini. Revisá tu conexión a "
            f"internet.\nDetalle: {error.reason}"
        )

    try:
        texto = cuerpo_respuesta["candidates"][0]["content"]["parts"][0]["text"]
        return texto.replace("**", "").replace("*", "")
    except (KeyError, IndexError):
        raise Exception(
            "Gemini respondió, pero en un formato inesperado:\n"
            f"{cuerpo_respuesta}"
        )


def texto_rangos_disponibles(producto):
    """
    Arma un texto tipo 'LANDSAT_5: 1984-01-01 → 2012-05-05 | LANDSAT_8: ...'
    con los rangos válidos de cada fuente para el producto, para mostrarlo
    cuando el rango elegido no resuelve a una sola fuente.
    """

    reglas = REGLAS_TEMPORALES.get(producto)

    if reglas is None:
        fuente_directa = PRODUCTOS.get(producto, {}).get("fuente")
        reglas = REGLAS_TEMPORALES.get(fuente_directa, [])

    if not reglas:
        return ""

    partes = []
    for regla in reglas:
        fin_texto = regla["fin"] if regla["fin"] is not None else "hoy"
        partes.append(f"{regla['fuente']}: {regla['inicio']} → {fin_texto}")

    return "  |  ".join(partes)


def fuente_resuelta_para(producto, fecha_inicio_str, fecha_fin_str):
    """
    Replica la misma lógica que usa motor.py para decidir qué fuente
    satelital corresponde a un rango de fechas: busca la ÚNICA regla
    cuyo rango cubre completo el (fecha_inicio, fecha_fin) elegido.
    Devuelve el nombre de la fuente, o None si no resuelve a una sola
    (rango mezclado, o sin fecha porque es DEM).
    """

    if fecha_inicio_str is None or fecha_fin_str is None:
        return None

    fecha_ini = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
    fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d").date()

    if fecha_ini > fecha_fin:
        return None  # rango invertido: nunca es válido, sea cual sea la fuente

    reglas = REGLAS_TEMPORALES.get(producto)

    if reglas is None:
        fuente_directa = PRODUCTOS.get(producto, {}).get("fuente")
        reglas = REGLAS_TEMPORALES.get(fuente_directa, [])

    for regla in reglas:
        inicio = datetime.strptime(regla["inicio"], "%Y-%m-%d").date()
        fin = (
            None if regla["fin"] is None
            else datetime.strptime(regla["fin"], "%Y-%m-%d").date()
        )
        fin_efectivo = fin if fin is not None else date.today()

        if fecha_ini >= inicio and fecha_fin <= fin_efectivo:
            return regla["fuente"]

    return None


def fecha_es_valida(fecha_qt, rangos):
    """fecha_qt: QDate. rangos: lista de (date, date_o_None)."""

    if not rangos:
        return True  # sin reglas para este producto: no bloqueamos nada

    fecha_py = date(fecha_qt.year(), fecha_qt.month(), fecha_qt.day())

    for inicio, fin in rangos:
        fin_efectivo = fin if fin is not None else date.today()
        if inicio <= fecha_py <= fin_efectivo:
            return True

    return False


class CalendarioBloqueado(QCalendarWidget):
    """
    QCalendarWidget que pinta en gris y NO deja seleccionar los días
    que caen fuera de los rangos válidos del producto elegido.
    """

    FORMATO_INVALIDO = QTextCharFormat()
    FORMATO_INVALIDO.setForeground(QColor("#c0c0c0"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rangos_validos = []
        self._ultima_fecha_valida = self.selectedDate()

        self.currentPageChanged.connect(self._repintar_mes_visible)
        self.selectionChanged.connect(self._al_cambiar_seleccion)

    def actualizar_rangos(self, rangos):
        self.rangos_validos = rangos
        self._repintar_mes_visible()

        # Si la fecha seleccionada quedó inválida con el nuevo
        # producto, la movemos a la fecha válida más cercana.
        if not fecha_es_valida(self.selectedDate(), self.rangos_validos):
            self._ir_a_fecha_valida_mas_cercana()

    def _repintar_mes_visible(self):
        anio = self.yearShown()
        mes = self.monthShown()

        formato_normal = QTextCharFormat()  # formato por defecto (vacío = reset)

        fecha = QDate(anio, mes, 1)
        while fecha.month() == mes:
            if fecha_es_valida(fecha, self.rangos_validos):
                self.setDateTextFormat(fecha, formato_normal)
            else:
                self.setDateTextFormat(fecha, self.FORMATO_INVALIDO)
            fecha = fecha.addDays(1)

    def _al_cambiar_seleccion(self):
        if fecha_es_valida(self.selectedDate(), self.rangos_validos):
            self._ultima_fecha_valida = self.selectedDate()
        else:
            # Bloqueamos el click: volvemos a la última fecha válida
            self.blockSignals(True)
            self.setSelectedDate(self._ultima_fecha_valida)
            self.blockSignals(False)

    def _ir_a_fecha_valida_mas_cercana(self):
        if not self.rangos_validos:
            return

        inicio_mas_reciente = max(inicio for inicio, _ in self.rangos_validos)
        nueva_fecha = QDate(
            inicio_mas_reciente.year,
            inicio_mas_reciente.month,
            inicio_mas_reciente.day
        )
        self._ultima_fecha_valida = nueva_fecha
        self.setSelectedDate(nueva_fecha)
        self._repintar_mes_visible()


class GeeProcesadorDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)


        # Habilita el botón de minimizar (por defecto QDialog solo trae
        # el de cerrar)
        self.setWindowFlags(
            Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )

        self.setWindowTitle("GEE Procesador")
        self.resize(460, 340)

        self.layout_principal = QVBoxLayout()

        # --- CAPA (solo polígonos) ---
        self.layout_principal.addWidget(QLabel("Capa de área de estudio:"))

        self.combo_capa = QComboBox()
        self.layout_principal.addWidget(self.combo_capa)

        self.aviso_sin_capas = QLabel(
            "No tenés polígonos en tu panel de capas. "
            "Cargá una capa de polígono y volvé a abrir esta ventana."
        )
        self.aviso_sin_capas.setStyleSheet("color: #b00020;")
        self.aviso_sin_capas.setVisible(False)
        self.layout_principal.addWidget(self.aviso_sin_capas)

        # --- CATEGORÍA (Índices / DEM / Coberturas) ---
        self.layout_principal.addWidget(QLabel("Categoría:"))

        fila_categorias = QHBoxLayout()
        self.grupo_categorias = QButtonGroup(self)
        self.grupo_categorias.setExclusive(True)

        self.botones_categoria = {}

        for nombre_categoria in CATEGORIAS.keys():
            boton = QPushButton(nombre_categoria)
            boton.setCheckable(True)
            boton.setFocusPolicy(Qt.NoFocus)  # saca el anillo azul de foco
            self.grupo_categorias.addButton(boton)
            self.botones_categoria[nombre_categoria] = boton
            fila_categorias.addWidget(boton)

        self.layout_principal.addLayout(fila_categorias)

        self.botones_categoria["Índices"].setChecked(True)
        self.grupo_categorias.buttonClicked.connect(self.al_cambiar_categoria)

        # --- PRODUCTO ---
        self.etiqueta_producto = QLabel("Producto:")
        self.layout_principal.addWidget(self.etiqueta_producto)

        self.combo_producto = QComboBox()
        self.layout_principal.addWidget(self.combo_producto)
        self.combo_producto.currentTextChanged.connect(
            self.al_cambiar_producto
        )

        # --- BANDAS (solo visible en la categoría "Bandas") ---
        self.etiqueta_combinacion = QLabel("Combinación:")
        self.layout_principal.addWidget(self.etiqueta_combinacion)

        self.combo_combinacion = QComboBox()
        for nombre_preset in PRESETS_BANDAS.keys():
            self.combo_combinacion.addItem(nombre_preset)
        self.combo_combinacion.addItem("Personalizada")
        self.combo_combinacion.currentTextChanged.connect(
            self.al_cambiar_combinacion
        )
        self.layout_principal.addWidget(self.combo_combinacion)

        fila_bandas_rgb = QHBoxLayout()

        fila_bandas_rgb.addWidget(QLabel("R:"))
        self.combo_banda_r = QComboBox()
        fila_bandas_rgb.addWidget(self.combo_banda_r)

        fila_bandas_rgb.addWidget(QLabel("G:"))
        self.combo_banda_g = QComboBox()
        fila_bandas_rgb.addWidget(self.combo_banda_g)

        fila_bandas_rgb.addWidget(QLabel("B:"))
        self.combo_banda_b = QComboBox()
        fila_bandas_rgb.addWidget(self.combo_banda_b)

        self.layout_principal.addLayout(fila_bandas_rgb)
        self.fila_bandas_rgb = fila_bandas_rgb

        # --- EPSG DE REPROYECCIÓN (solo visible para DEM) ---
        fila_epsg = QHBoxLayout()

        self.etiqueta_epsg = QLabel("EPSG de reproyección (OBLIGATORIO para DEM):")
        fila_epsg.addWidget(self.etiqueta_epsg)

        self.campo_epsg = QLineEdit()
        self.campo_epsg.setPlaceholderText("Ej: EPSG:5345")
        fila_epsg.addWidget(self.campo_epsg)

        self.layout_principal.addLayout(fila_epsg)

        # --- NUBOSIDAD MÁXIMA ---
        fila_nubosidad = QHBoxLayout()

        self.etiqueta_nubosidad = QLabel("Nubosidad máxima permitida (%):")
        fila_nubosidad.addWidget(self.etiqueta_nubosidad)

        self.spin_nubosidad = QSpinBox()
        self.spin_nubosidad.setRange(0, 100)
        self.spin_nubosidad.setValue(20)
        self.spin_nubosidad.setSuffix(" %")
        fila_nubosidad.addWidget(self.spin_nubosidad)

        fila_nubosidad.addStretch()

        self.layout_principal.addLayout(fila_nubosidad)

        # --- FECHAS (ocultas para DEM, que no usa fecha) ---
        self.bloque_fechas = QVBoxLayout()
        self.bloque_fechas.addWidget(QLabel("Rango de fechas:"))

        fila_fechas = QHBoxLayout()

        fila_fechas.addWidget(QLabel("Desde:"))
        self.fecha_inicio = self._crear_campo_fecha()
        fila_fechas.addWidget(self.fecha_inicio)

        fila_fechas.addWidget(QLabel("Hasta:"))
        self.fecha_fin = self._crear_campo_fecha()
        fila_fechas.addWidget(self.fecha_fin)

        self.bloque_fechas.addLayout(fila_fechas)
        self.layout_principal.addLayout(self.bloque_fechas)

        # --- FUENTE RESUELTA + RESOLUCIÓN SENTINEL-2 ---
        self.fila_resolucion = QHBoxLayout()

        self.etiqueta_fuente = QLabel("")
        self.etiqueta_fuente.setStyleSheet("color: #444444;")
        self.fila_resolucion.addWidget(self.etiqueta_fuente)

        self.etiqueta_resolucion = QLabel("Resolución Sentinel-2:")
        self.fila_resolucion.addWidget(self.etiqueta_resolucion)

        self.combo_resolucion = QComboBox()
        self.combo_resolucion.addItem("10 m (nativa)", 10)
        self.combo_resolucion.addItem("30 m (comparar con Landsat)", 30)
        self.fila_resolucion.addWidget(self.combo_resolucion)

        self.fila_resolucion.addStretch()

        self.layout_principal.addLayout(self.fila_resolucion)

        self.fecha_inicio.dateChanged.connect(self.actualizar_visibilidad_resolucion)
        self.fecha_fin.dateChanged.connect(self.actualizar_visibilidad_resolucion)
        self.fecha_inicio.dateChanged.connect(self.actualizar_opciones_bandas)
        self.fecha_fin.dateChanged.connect(self.actualizar_opciones_bandas)

        # --- SALIDA (visualizar / exportar directo / exportar a Drive) ---
        grupo_salida = QGroupBox("¿Qué hacer con el resultado?")
        layout_salida = QVBoxLayout()

        self.radio_visualizar = QRadioButton("Solo visualizar en QGIS")
        self.radio_directo = QRadioButton("Exportar directo a disco")
        self.radio_drive = QRadioButton("Exportar a Google Drive")

        self.radio_visualizar.setChecked(True)  # opción por defecto

        layout_salida.addWidget(self.radio_visualizar)
        layout_salida.addWidget(self.radio_directo)
        layout_salida.addWidget(self.radio_drive)

        grupo_salida.setLayout(layout_salida)
        self.layout_principal.addWidget(grupo_salida)

        # --- BOTONES ---
        fila_botones = QHBoxLayout()
        fila_botones.addStretch()

        self.boton_ejecutar = QPushButton("Ejecutar")
        self.boton_ejecutar.clicked.connect(self.al_hacer_click_ejecutar)
        fila_botones.addWidget(self.boton_ejecutar)

        self.layout_principal.addLayout(fila_botones)

        # =====================================================
        # ARMADO DE PESTAÑAS
        # =====================================================

        tab_configuracion = QWidget()
        tab_configuracion.setLayout(self.layout_principal)

        tab_clave_api = self._crear_pestana_clave_api()
        tab_informe = self._crear_pestana_informe()

        self.pestanas = QTabWidget()
        self.pestanas.addTab(tab_configuracion, "Geo Procesador")
        self.pestanas.addTab(tab_informe, "Informe")
        self.pestanas.addTab(tab_clave_api, "Clave API")

        layout_ventana = QVBoxLayout()
        layout_ventana.addWidget(self.pestanas)
        self.setLayout(layout_ventana)

        self.cargar_capas_poligono()
        self.actualizar_lista_productos()

    def _crear_pestana_clave_api(self):
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Clave de API de Gemini:"))

        self.campo_api_key = QLineEdit()
        self.campo_api_key.setEchoMode(QLineEdit.Password)
        self.campo_api_key.setPlaceholderText("Pegá acá tu clave de aistudio.google.com")
        self.campo_api_key.setText(
            QgsSettings().value(CLAVE_SETTINGS_API_GEMINI, "")
        )
        layout.addWidget(self.campo_api_key)

        boton_guardar_clave = QPushButton("Guardar clave")
        boton_guardar_clave.clicked.connect(self.guardar_api_key)
        layout.addWidget(boton_guardar_clave)

        aviso_clave = QLabel(
            "La clave se guarda solo en tu perfil de QGIS, en esta computadora. "
            "No viaja si compartís la carpeta del plugin.\n\n"
            "La conseguís gratis en aistudio.google.com → 'Get API key'."
        )
        aviso_clave.setWordWrap(True)
        aviso_clave.setStyleSheet("color: #666666; font-size: 10px;")
        layout.addWidget(aviso_clave)

        layout.addStretch()

        widget.setLayout(layout)
        return widget

    def _crear_pestana_informe(self):
        widget = QWidget()
        layout = QVBoxLayout()

        # --- Cuadro "Resultado": resumen + tabla, siempre visible ---
        grupo_resultado = QGroupBox("Resultado")
        layout_resultado = QVBoxLayout()

        self.etiqueta_resumen = QLabel("")
        self.etiqueta_resumen.setWordWrap(True)
        layout_resultado.addWidget(self.etiqueta_resumen)

        self.tabla_clasificacion = QTableWidget(0, 3)
        self.tabla_clasificacion.setHorizontalHeaderLabels(["Clase", "%", "Color"])
        self.tabla_clasificacion.horizontalHeader().setStretchLastSection(True)
        self.tabla_clasificacion.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.tabla_clasificacion.setMaximumHeight(160)
        self.tabla_clasificacion.setEditTriggers(QTableWidget.NoEditTriggers)
        layout_resultado.addWidget(self.tabla_clasificacion)

        grupo_resultado.setLayout(layout_resultado)
        layout.addWidget(grupo_resultado)

        # --- Sub-pestañas: Informe completo / Interpretación IA ---
        self.sub_pestanas_informe = QTabWidget()

        tab_informe_completo = QWidget()
        layout_informe_completo = QVBoxLayout()
        self.texto_json = QTextEdit()
        self.texto_json.setReadOnly(True)
        self.texto_json.setPlainText("Todavía no hay datos — ejecutá un análisis primero.")
        layout_informe_completo.addWidget(self.texto_json)
        tab_informe_completo.setLayout(layout_informe_completo)

        tab_interpretacion_ia = QWidget()
        layout_interpretacion_ia = QVBoxLayout()
        self.texto_informe = QTextEdit()
        self.texto_informe.setReadOnly(True)
        self.texto_informe.setPlainText(
            "Todavía no ejecutaste nada. Corré un análisis en la pestaña "
            "'Geo Procesador' y, si tenés tu clave de Gemini cargada en la "
            "pestaña 'Clave API', acá va a aparecer la interpretación."
        )
        layout_interpretacion_ia.addWidget(self.texto_informe)
        tab_interpretacion_ia.setLayout(layout_interpretacion_ia)

        self.sub_pestanas_informe.addTab(tab_informe_completo, "Informe completo")
        self.sub_pestanas_informe.addTab(tab_interpretacion_ia, "Interpretación IA")

        layout.addWidget(self.sub_pestanas_informe)

        widget.setLayout(layout)
        return widget

    def guardar_api_key(self):
        QgsSettings().setValue(
            CLAVE_SETTINGS_API_GEMINI, self.campo_api_key.text().strip()
        )
        QMessageBox.information(self, "Guardado", "Clave de API guardada.")

    def _crear_campo_fecha(self):
        campo = QDateEdit()
        campo.setCalendarPopup(True)
        campo.setDisplayFormat("yyyy-MM-dd")
        campo.setDate(QDate.currentDate())

        calendario = CalendarioBloqueado()
        campo.setCalendarWidget(calendario)

        return campo

    def al_cambiar_categoria(self, boton_clickeado):
        self.actualizar_lista_productos()

    def al_cambiar_producto(self, producto):
        if not producto:
            return

        rangos = rangos_validos_para(producto)

        self.fecha_inicio.calendarWidget().actualizar_rangos(rangos)
        self.fecha_fin.calendarWidget().actualizar_rangos(rangos)

        # Si el rango elegido (inicio/fin) quedó inválido o colapsado en
        # un solo día (por ejemplo al pasar a un producto de ventana muy
        # angosta como ESA WorldCover), reseteamos a un rango completo y
        # útil: el período más reciente disponible, de punta a punta.
        fecha_ini_actual = self.fecha_inicio.date()
        fecha_fin_actual = self.fecha_fin.date()

        rango_valido = (
            not rangos or (
                fecha_es_valida(fecha_ini_actual, rangos)
                and fecha_es_valida(fecha_fin_actual, rangos)
                and fecha_ini_actual < fecha_fin_actual
            )
        )

        if not rango_valido and rangos:
            inicio, fin = max(rangos, key=lambda r: r[0])
            fin_efectivo = fin if fin is not None else date.today()

            self.fecha_inicio.setDate(QDate(inicio.year, inicio.month, inicio.day))
            self.fecha_fin.setDate(
                QDate(fin_efectivo.year, fin_efectivo.month, fin_efectivo.day)
            )

        # ESA WorldCover es una sola foto anual (2021): no tiene sentido
        # dejar elegir fecha ahí, la fijamos y la bloqueamos.
        es_rango_fijo = (producto == "ESA_WORLDCOVER")
        self.fecha_inicio.setEnabled(not es_rango_fijo)
        self.fecha_fin.setEnabled(not es_rango_fijo)

        self.actualizar_visibilidad_resolucion()

    def actualizar_visibilidad_resolucion(self):
        es_bandas = (self.categoria_actual() == "Bandas")
        clave_busqueda = "BANDAS" if es_bandas else self.obtener_producto_seleccionado()

        fecha_inicio, fecha_fin = self.obtener_fechas()

        fuente = fuente_resuelta_para(clave_busqueda, fecha_inicio, fecha_fin)

        # DEM no tiene fecha, así que no hay "fuente satelital" que mostrar.
        if self.categoria_actual() == "DEM":
            self.etiqueta_fuente.setVisible(False)
        elif fecha_inicio is not None and fecha_inicio > fecha_fin:
            self.etiqueta_fuente.setText(
                f"La fecha 'Desde' ({fecha_inicio}) es posterior a "
                f"'Hasta' ({fecha_fin}) — corregí el orden."
            )
            self.etiqueta_fuente.setVisible(True)
        elif fuente:
            self.etiqueta_fuente.setText(f"Satélite o fuente a utilizar: {fuente}")
            self.etiqueta_fuente.setVisible(True)
        else:
            self.etiqueta_fuente.setText(
                "El rango elegido mezcla más de una fuente. Fuentes "
                f"disponibles:  {texto_rangos_disponibles(clave_busqueda)}"
            )
            self.etiqueta_fuente.setVisible(True)

        mostrar_resolucion = (fuente == "COPERNICUS_S2")
        self.etiqueta_resolucion.setVisible(mostrar_resolucion)
        self.combo_resolucion.setVisible(mostrar_resolucion)

    def obtener_resolucion_sentinel(self):
        return self.combo_resolucion.currentData()

    def categoria_actual(self):
        for nombre, boton in self.botones_categoria.items():
            if boton.isChecked():
                return nombre
        return "Índices"

    def actualizar_lista_productos(self):
        categoria = self.categoria_actual()
        es_bandas = (categoria == "Bandas")

        self.combo_producto.clear()

        if not es_bandas:
            for clave_familia in CATEGORIAS[categoria]:
                for producto in FAMILIAS[clave_familia]:
                    self.combo_producto.addItem(producto)

        self.etiqueta_producto.setVisible(not es_bandas)
        self.combo_producto.setVisible(not es_bandas)

        self.etiqueta_combinacion.setVisible(es_bandas)
        self.combo_combinacion.setVisible(es_bandas)
        for i in range(self.fila_bandas_rgb.count()):
            item = self.fila_bandas_rgb.itemAt(i)
            if item.widget():
                item.widget().setVisible(es_bandas)

        es_dem = (categoria == "DEM")
        es_cobertura = (categoria == "Coberturas")

        self.etiqueta_epsg.setVisible(es_dem)
        self.campo_epsg.setVisible(es_dem)

        # Nubosidad aplica a Índices y Bandas (ambas trabajan con imagen
        # óptica cruda). En DEM no hay imagen óptica, y en Coberturas el
        # filtrado de nube ya viene resuelto en el dato clasificado.
        mostrar_nubosidad = not es_dem and not es_cobertura
        self.etiqueta_nubosidad.setVisible(mostrar_nubosidad)
        self.spin_nubosidad.setVisible(mostrar_nubosidad)

        # DEM no usa fechas: ocultamos todo el bloque. Bandas sí usa fecha.
        for i in range(self.bloque_fechas.count()):
            item = self.bloque_fechas.itemAt(i)
            if item.widget():
                item.widget().setVisible(not es_dem)
            if item.layout():
                for j in range(item.layout().count()):
                    sub = item.layout().itemAt(j)
                    if sub.widget():
                        sub.widget().setVisible(not es_dem)

        if es_bandas:
            # Bandas no dispara al_cambiar_producto (el combo de
            # producto queda vacío), así que actualizamos el
            # calendario y la fuente/resolución a mano acá.
            rangos = rangos_validos_para("BANDAS")
            self.fecha_inicio.calendarWidget().actualizar_rangos(rangos)
            self.fecha_fin.calendarWidget().actualizar_rangos(rangos)
            self.actualizar_visibilidad_resolucion()
            self.al_cambiar_combinacion(self.combo_combinacion.currentText())

    def al_cambiar_combinacion(self, nombre_preset):
        if not self.categoria_actual() == "Bandas":
            return

        es_personalizada = (nombre_preset == "Personalizada")

        self.combo_banda_r.setEnabled(es_personalizada)
        self.combo_banda_g.setEnabled(es_personalizada)
        self.combo_banda_b.setEnabled(es_personalizada)

        # actualizar_opciones_bandas() repuebla los roles Y reaplica el
        # preset activo (si corresponde) en un solo lugar — evita tener
        # la misma lógica de "aplicar preset" duplicada en dos métodos.
        self.actualizar_opciones_bandas()

    def actualizar_opciones_bandas(self):
        """Puebla los 3 combos R/G/B con los roles disponibles según la
        fuente que resuelve la fecha elegida (Landsat no tiene los mismos
        roles que Sentinel-2, por ejemplo THERMAL)."""

        fecha_inicio, fecha_fin = self.obtener_fechas()
        fuente = fuente_resuelta_para("BANDAS", fecha_inicio, fecha_fin)

        roles = list(FUENTES[fuente]["bandas"].keys()) if fuente else []

        nombre_preset = self.combo_combinacion.currentText()
        es_personalizada = (nombre_preset == "Personalizada")

        # Mapeo por defecto si venimos de un preset especial ("Fórmula calculada")
        roles_defecto = ("RED", "GREEN", "BLUE")

        for combo, rol_defecto in zip(
            (self.combo_banda_r, self.combo_banda_g, self.combo_banda_b),
            roles_defecto
        ):
            actual = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(roles)
            
            if actual in roles:
                combo.setCurrentText(actual)
            elif rol_defecto in roles:
                combo.setCurrentText(rol_defecto)

            combo.blockSignals(False)

        # Si hay un preset activo...
        if not es_personalizada and nombre_preset in PRESETS_BANDAS:
            preset_val = PRESETS_BANDAS[nombre_preset]
            
            if preset_val in ("TOLARI", "GREEN_CITY"):
                for combo in (self.combo_banda_r, self.combo_banda_g, self.combo_banda_b):
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItem("Fórmula calculada")
                    combo.setCurrentText("Fórmula calculada")
                    combo.blockSignals(False)
            else:
                rol_r, rol_g, rol_b = preset_val
                if rol_r in roles and rol_g in roles and rol_b in roles:
                    self.combo_banda_r.setCurrentText(rol_r)
                    self.combo_banda_g.setCurrentText(rol_g)
                    self.combo_banda_b.setCurrentText(rol_b)

    def obtener_producto_seleccionado(self):
        return self.combo_producto.currentText()

    def obtener_bandas_rgb(self):
        return (
            self.combo_banda_r.currentText(),
            self.combo_banda_g.currentText(),
            self.combo_banda_b.currentText(),
        )

    def obtener_epsg_destino(self):
        if self.categoria_actual() != "DEM":
            return None

        texto = self.campo_epsg.text().strip()
        return texto if texto else None

    def obtener_nubosidad_maxima(self):
        return self.spin_nubosidad.value()

    def obtener_fechas(self):
        """Devuelve (fecha_inicio_str, fecha_fin_str) en 'YYYY-MM-DD', o (None, None) si no aplica (DEM)."""

        if self.categoria_actual() == "DEM":
            return None, None

        return (
            self.fecha_inicio.date().toString("yyyy-MM-dd"),
            self.fecha_fin.date().toString("yyyy-MM-dd")
        )

    def cargar_capas_poligono(self):
        self.combo_capa.clear()

        capas_poligono = []

        for capa in QgsProject.instance().mapLayers().values():
            if capa.type() != QgsMapLayer.VectorLayer:
                continue
            if capa.geometryType() == QgsWkbTypes.PolygonGeometry:
                capas_poligono.append(capa)

        if len(capas_poligono) == 0:
            self.combo_capa.setVisible(False)
            self.aviso_sin_capas.setVisible(True)
            return

        self.combo_capa.setVisible(True)
        self.aviso_sin_capas.setVisible(False)

        for capa in capas_poligono:
            self.combo_capa.addItem(capa.name(), userData=capa)

    def obtener_configuracion_salida(self):
        """
        Devuelve (visualizar: bool, exportar: bool, modo_exportacion: str)
        según el radio button elegido. Las 3 opciones son mutuamente
        excluyentes por naturaleza del widget (no hace falta validar).
        """

        if self.radio_visualizar.isChecked():
            return True, False, "directo"  # modo_exportacion no se usa si exportar=False

        if self.radio_directo.isChecked():
            return False, True, "directo"

        # self.radio_drive.isChecked()
        return False, True, "drive"

    def al_hacer_click_ejecutar(self):
        capa = self.obtener_capa_seleccionada()

        if capa is None:
            QMessageBox.warning(
                self, "Falta la capa",
                "No hay ninguna capa de polígono seleccionada. "
                "Cargá una capa de polígono en QGIS antes de ejecutar."
            )
            return

        if self.categoria_actual() == "Bandas":
            self._ejecutar_composicion_bandas(capa)
            return

        producto = self.obtener_producto_seleccionado()

        if not producto:
            QMessageBox.warning(
                self, "Falta el producto",
                "No hay ningún producto seleccionado."
            )
            return

        if self.categoria_actual() == "DEM" and not self.obtener_epsg_destino():
            QMessageBox.warning(
                self, "Falta el EPSG",
                "Para productos DEM el EPSG de reproyección es obligatorio. "
                "Completá el campo (ej: EPSG:5345) antes de ejecutar."
            )
            return

        fecha_inicio, fecha_fin = self.obtener_fechas()

        if self.categoria_actual() != "DEM":

            if fecha_inicio is not None and fecha_inicio > fecha_fin:
                QMessageBox.warning(
                    self, "Rango de fechas invertido",
                    f"La fecha 'Desde' ({fecha_inicio}) es posterior a la "
                    f"fecha 'Hasta' ({fecha_fin}). Corregí el orden antes "
                    "de ejecutar."
                )
                return

            fuente = fuente_resuelta_para(producto, fecha_inicio, fecha_fin)
            if fuente is None:
                QMessageBox.warning(
                    self, "Rango de fechas mezcla fuentes",
                    "El rango de fechas elegido no corresponde a una única "
                    "fuente satelital. Fuentes disponibles para "
                    f"{producto}:\n\n{texto_rangos_disponibles(producto)}"
                )
                return

        visualizar, exportar, modo_exportacion = self.obtener_configuracion_salida()

        config = {
            "nombre_capa": capa.name(),
            "producto": producto,
            "epsg_destino": self.obtener_epsg_destino(),
            "nubosidad_maxima": self.obtener_nubosidad_maxima(),
            "resolucion_sentinel": self.obtener_resolucion_sentinel(),
            "visualizar": visualizar,
            "exportar": exportar,
            "modo_exportacion": modo_exportacion,
            "modo_debug": True,
            "calcular_estadisticas": True,
        }

        # DEM no usa fechas; para el resto, si por algún motivo
        # obtener_fechas() no devolvió nada, dejamos que motor.py
        # aplique sus propios valores por defecto.
        if fecha_inicio is not None:
            config["fecha_inicio"] = fecha_inicio
            config["fecha_fin"] = fecha_fin

        self.boton_ejecutar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            resultado_corrida = motor.ejecutar(config)

        except Exception as error:
            mensaje_error = str(error)

            si_es_error_de_tamano = (
                "Total request size" in mensaje_error
                and "must be less than or equal to" in mensaje_error
            )

            if si_es_error_de_tamano:
                QMessageBox.critical(
                    self, "Área demasiado grande para descarga directa",
                    "Earth Engine no permite bajar directamente un resultado tan "
                    "pesado (el límite es de aproximadamente 48 MB por pedido "
                    "síncrono). Esto pasa cuando el área de estudio es grande "
                    "y/o la resolución es fina.\n\n"
                    "Solución: elegí 'Exportar a Google Drive' en vez de "
                    "'Exportar directo a disco'. Las exportaciones a Drive "
                    "corren en un proceso en segundo plano de Earth Engine, "
                    "sin ese límite tan chico — están pensadas justo para "
                    "áreas grandes como esta."
                )
            else:
                QMessageBox.critical(
                    self, "Error al ejecutar",
                    mensaje_error
                )

        else:
            QMessageBox.information(
                self, "Listo",
                "El proceso terminó correctamente."
            )
            self._mostrar_resumen_resultado(resultado_corrida)
            self._generar_informe_si_corresponde(resultado_corrida)

        finally:
            QApplication.restoreOverrideCursor()
            self.boton_ejecutar.setEnabled(True)

    def _ejecutar_composicion_bandas(self, capa):
        banda_r, banda_g, banda_b = self.obtener_bandas_rgb()

        if not (banda_r and banda_g and banda_b):
            QMessageBox.warning(
                self, "Faltan bandas",
                "Elegí una combinación o completá las 3 bandas "
                "(R, G, B) antes de ejecutar."
            )
            return

        fecha_inicio, fecha_fin = self.obtener_fechas()

        fuente = fuente_resuelta_para("BANDAS", fecha_inicio, fecha_fin)
        if fuente is None:
            QMessageBox.warning(
                self, "Rango de fechas mezcla fuentes",
                "El rango de fechas elegido no corresponde a una única "
                "fuente satelital. Fuentes disponibles:\n\n"
                f"{texto_rangos_disponibles('BANDAS')}"
            )
            return

        visualizar, exportar, modo_exportacion = self.obtener_configuracion_salida()

        config = {
            "nombre_capa": capa.name(),
            "preset_nombre": self.combo_combinacion.currentText(),
            "banda_r": banda_r,
            "banda_g": banda_g,
            "banda_b": banda_b,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "nubosidad_maxima": self.obtener_nubosidad_maxima(),
            "resolucion_sentinel": self.obtener_resolucion_sentinel(),
            "visualizar": visualizar,
            "exportar": exportar,
            "modo_exportacion": modo_exportacion,
        }

        self.boton_ejecutar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            resultado_corrida = motor.generar_composicion_bandas(config)

        except Exception as error:
            mensaje_error = str(error)

            si_es_error_de_tamano = (
                "Total request size" in mensaje_error
                and "must be less than or equal to" in mensaje_error
            )

            if si_es_error_de_tamano:
                QMessageBox.critical(
                    self, "Área demasiado grande para descarga directa",
                    "Earth Engine no permite bajar directamente un resultado "
                    "tan pesado (el límite es de aproximadamente 48 MB por "
                    "pedido síncrono).\n\nSolución: elegí 'Exportar a Google "
                    "Drive' en vez de 'Exportar directo a disco'."
                )
            else:
                QMessageBox.critical(self, "Error al ejecutar", mensaje_error)

        else:
            QMessageBox.information(
                self, "Listo", "La composición de bandas terminó correctamente."
            )
            self._mostrar_resumen_resultado(resultado_corrida)
            # No hay interpretación de IA para bandas crudas: no es una
            # clasificación, es una imagen de referencia visual.
            self.texto_informe.setPlainText(
                "La categoría 'Bandas' genera una imagen de referencia "
                "visual (composición RGB), no una clasificación — no aplica "
                "interpretación automática acá."
            )
            self.pestanas.setCurrentIndex(1)
            self.sub_pestanas_informe.setCurrentIndex(1)

        finally:
            QApplication.restoreOverrideCursor()
            self.boton_ejecutar.setEnabled(True)

    def _mostrar_resumen_resultado(self, resultado_corrida):
        resultados = resultado_corrida.get("resultados", {})
        clasificacion = resultados.get("clasificacion_detallada", {})
        estadisticas = resultados.get("estadisticas", {})
        producto = resultado_corrida.get("producto")

        colores = REFERENCIAS_COLOR.get(producto, {})

        self.tabla_clasificacion.setRowCount(0)

        for clase, porcentaje in clasificacion.items():
            fila = self.tabla_clasificacion.rowCount()
            self.tabla_clasificacion.insertRow(fila)
            self.tabla_clasificacion.setItem(fila, 0, QTableWidgetItem(str(clase)))
            self.tabla_clasificacion.setItem(
                fila, 1, QTableWidgetItem(f"{porcentaje} %")
            )
            self.tabla_clasificacion.setItem(
                fila, 2, QTableWidgetItem(colores.get(clase, "no definido"))
            )

        superficie_ha = estadisticas.get("superficie_ha")
        superficie_km2 = estadisticas.get("superficie_km2")

        texto_resumen = (
            f"Producto: {resultado_corrida.get('producto', '—')}   |   "
            f"Capa: {resultado_corrida.get('nombre_capa', '—')}"
        )

        if superficie_ha is not None:
            texto_resumen += (
                f"   |   Superficie: {superficie_ha:,.2f} ha "
                f"({superficie_km2:,.2f} km²)"
            )

        self.etiqueta_resumen.setText(texto_resumen)

        # Mostramos el informe real que ya arma motor.py (el mismo texto
        # que va al .txt exportado) — no una reconstrucción aparte, así
        # no hay riesgo de que las dos versiones se desincronicen.
        self.texto_json.setPlainText(
            resultado_corrida.get("informe_texto") or formatear_detalle_tecnico(resultados)
        )

    def _generar_informe_si_corresponde(self, resultado_corrida):
        api_key = QgsSettings().value(CLAVE_SETTINGS_API_GEMINI, "").strip()

        if not api_key:
            self.texto_informe.setPlainText(
                "La interpretación con IA es opcional — no hace falta para "
                "nada de lo demás (la tabla y el JSON de arriba ya están "
                "completos). Si en algún momento querés un resumen en "
                "texto además, cargá una clave gratis de Gemini en la "
                "pestaña 'Clave API' y volvé a ejecutar."
            )
            self.pestanas.setCurrentIndex(1)
            self.sub_pestanas_informe.setCurrentIndex(1)
            return

        self.texto_informe.setPlainText("Consultando a Gemini, un momento…")
        self.pestanas.setCurrentIndex(1)
        self.sub_pestanas_informe.setCurrentIndex(1)
        QApplication.processEvents()  # refresca la UI antes de la llamada bloqueante

        try:
            texto = pedir_interpretacion_gemini(
                api_key=api_key,
                producto=resultado_corrida["producto"],
                nombre_capa=resultado_corrida["nombre_capa"],
                lat=resultado_corrida["centroide_lat"],
                lon=resultado_corrida["centroide_lon"],
                resultados=resultado_corrida["resultados"],
                colores=REFERENCIAS_COLOR.get(resultado_corrida["producto"], {}),
            )
            self.texto_informe.setPlainText(texto)

        except Exception as error:
            self.texto_informe.setPlainText(
                f"No se pudo generar la interpretación con IA.\n\n{error}"
            )

    def obtener_capa_seleccionada(self):
        if self.combo_capa.count() == 0:
            return None

        return self.combo_capa.currentData()