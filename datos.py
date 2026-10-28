# =====================================================
# DATOS.PY
# Diccionarios de referencia (no cambian según ejecución)
# Extraído tal cual de 01_Proyecto_Base_copia.py
# =====================================================

# =====================================================
# METADATOS
# =====================================================

METADATOS = {
    "version": "4.0",
    "autor": "Federico Carrera"
}

# =====================================================
# FAMILIAS DE PRODUCTOS
# =====================================================

FAMILIAS = {

    "TURBIDEZ": [
        "NDTI"
    ],

    "METEOROLOGIA": [
        "CHIRPS", 
        "VIENTO_ERA5"
    ],

    "USO_SUELO": [
        "DYNAMIC_WORLD",
        "ESA_WORLDCOVER"
    ],

    "VEGETACION": [
        "NDVI",
        "MSAVI"
    ],

    "AGUA": [
        "NDWI",
        "MNDWI"
    ],

    "URBANIZACION": [
        "NDBI",
        "EBBI"
    ],

    "HUMEDAD": [
        "NDMI"
    ],

    "INCENDIOS": [
        "NBR"
    ],

    "TEMPERATURA":[
        "LST"
    ],

    # Agregado para la interfaz del plugin: agrupa los productos DEM,
    # que en el script original nunca necesitaron estar en FAMILIAS
    # (tienen su propia rama de interpretación aparte).
    "RELIEVE": [
        "DEM",
        "DEM_RELIEVE",
        "PENDIENTE",
        "ASPECT",
        "CURVATURA",
        "TRI",
        "TPI",
        "IRREGULARIDAD"
    ]
}

# =====================================================
# PRODUCTOS
# =====================================================

PRODUCTOS = {

    "NDTI": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("RED", "GREEN"),
        "estilo": "TURBIDEZ",
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "VIENTO_ERA5": {
        "fuente": "ERA5_LAND",
        "tipo": "continuo",
        "metodo": "viento_vectorial",
        "banda": "u_component_of_wind_10m",
        "estilo": "VIENTO",
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "CHIRPS": {
        "fuente": "CHIRPS",
        "tipo": "continuo",
        "metodo": "suma_temporal",
        "banda": "precipitation",
        "estilo": "LLUVIA",
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "DYNAMIC_WORLD": {
        "fuente": "DYNAMIC_WORLD",
        "tipo": "clasificacion",
        "metodo": "clasificacion_ia",
        "banda": "label",
        "estilo": "USO_SUELO",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "ESA_WORLDCOVER": {
        "fuente": "ESA_WORLDCOVER",
        "tipo": "clasificacion",
        "metodo": "clasificacion_ia",
        "banda": "Map",
        "estilo": "ESA_WORLDCOVER",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    #INDICES

    "NDVI": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("NIR", "RED"),
        "estilo": "VEGETACION",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "NDWI": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("GREEN", "NIR"),
        "estilo": "AGUA",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "MNDWI": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("GREEN", "SWIR1"),
        "estilo": "AGUA",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "NDBI": {
        "fuente": "LANDSAT_8",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("SWIR1", "NIR"),
        "estilo": "URBANIZACION",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "EBBI": {
        "tipo": "indice",
        "metodo": "EBBI",
        "estilo": "EBBI",
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "MSAVI": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "MSAVI",
        "estilo": "VEGETACION",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "NDMI": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("NIR", "SWIR1"),
        "estilo": "HUMEDAD",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "NBR": {
        "fuente": "COPERNICUS_S2",
        "tipo": "indice",
        "metodo": "normalizedDifference",
        "bandas": ("NIR", "SWIR2"),
        "estilo": "INCENDIOS",
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "LST": {
        "tipo": "indice",
        "metodo": "LST",
        "estilo": "TEMPERATURA",
        "guardar_estilo": True,
        "rango_automatico": True
    },

    #MODELO DIGITAL DE ELEVACIONES

    "DEM": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "DEM",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "DEM_RELIEVE": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "DEM_RELIEVE",
        "hillshade": True,
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "PENDIENTE": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "PENDIENTE",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "ASPECT": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "ASPECT",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": False
    },

    "CURVATURA": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "CURVATURA",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "TRI": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "TRI",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "TPI": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "TPI",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": True
    },

    "IRREGULARIDAD": {
        "fuente": "COPERNICUS_DEM",
        "banda": "DEM",
        "tipo": "elevacion",
        "metodo": "banda",
        "estilo": "IRREGULARIDAD",
        "hillshade": False,
        "guardar_estilo": True,
        "rango_automatico": True
    },

}

# =====================================================
# CLASIFICACIONES
# =====================================================

CLASIFICACIONES = {

    "NDTI": [
        (-1.00, -0.15, "Turbidez muy baja"),
        (-0.15, -0.08, "Turbidez baja"),
        (-0.08,  0.00, "Turbidez moderada"),
        ( 0.00,  0.10, "Turbidez alta"),
        ( 0.10,  1.01, "Turbidez muy alta")
    ],

    "DYNAMIC_WORLD": [
        (-0.5, 0.5, "Agua"),
        ( 0.5, 1.5, "Árboles"),
        ( 1.5, 2.5, "Pasto / Vegetación baja"),
        ( 2.5, 3.5, "Vegetación inundada"),
        ( 3.5, 4.5, "Cultivos"),
        ( 4.5, 5.5, "Arbustos / Matorrales"),
        ( 5.5, 6.5, "Área construida (Urbana)"),
        ( 6.5, 7.5, "Suelo desnudo"),
        ( 7.5, 8.5, "Nieve y hielo")
    ],

    "ESA_WORLDCOVER": [
        (  5.0,  15.0, "Árboles"),
        ( 15.0,  25.0, "Arbustos / Matorrales"),
        ( 25.0,  35.0, "Pasto / Vegetación baja"),
        ( 35.0,  45.0, "Cultivos"),
        ( 45.0,  55.0, "Área construida (Urbana)"),
        ( 55.0,  65.0, "Suelo desnudo"),
        ( 65.0,  75.0, "Nieve y hielo"),
        ( 75.0,  85.0, "Agua"),
        ( 85.0,  95.0, "Vegetación inundada"),
        ( 95.0,  99.0, "Manglares"),
        ( 99.0, 105.0, "Musgo y líquenes")
    ],

    "NDVI": [

        (-0.50, -0.10, "Agua"),
        (-0.10,  0.00, "Suelo desnudo"),
        ( 0.00,  0.20, "Vegetación escasa"),
        ( 0.20,  0.30, "Vegetación baja"),
        ( 0.30,  0.40, "Vegetación moderada"),
        ( 0.40,  0.60, "Vegetación densa"),
        ( 0.60,  1.00, "Vegetación muy densa")

    ],

    "NDWI": [

        (-1.00, -0.20, "Agua muy baja"),
        (-0.20,  0.00, "Agua baja"),
        ( 0.00,  0.20, "Agua moderada"),
        ( 0.20,  0.40, "Agua alta"),
        ( 0.40,  1.01, "Agua muy alta")

    ],

    "MNDWI": [

        (-1.00, -0.30, "Suelo muy seco"),
        (-0.30, -0.10, "Suelo"),
        (-0.10,  0.00, "Transición"),
        ( 0.00,  0.20, "Humedad"),
        ( 0.20,  0.40, "Agua somera"),
        ( 0.40,  0.60, "Agua"),
        ( 0.60,  1.00, "Agua profunda")

    ],

    "NDBI": [

        (-1.00, -0.20, "Vegetación"),
        (-0.20,  0.00, "Suelo"),
        ( 0.00,  0.15, "Transición"),
        ( 0.15,  0.35, "Urbanización baja"),
        ( 0.35,  0.55, "Urbanización media"),
        ( 0.55,  1.00, "Urbanización alta")

    ],

    "EBBI": [
        # Sierras, vegetación activa y sombras térmicas
        (-1.000, -0.040, "Vegetación"),
        
        # Matorrales y pastizales secos (La verdadera matriz de San Luis)
        (-0.040, -0.010, "Transición"),
        
        # Tierra pelada, canteras, lotes agrícolas en descanso
        (-0.010,  0.015, "Suelo"),
        
        # Barrios periurbanos muy arbolados (Acá empieza el ~18% de ciudad)
        ( 0.015,  0.040, "Urbanización baja"),
        
        # Barrios consolidados, asfalto, cuadrícula tradicional
        ( 0.040,  0.090, "Urbanización media"),
        
        # Planchas de cemento puro, aeropuerto, techos de chapa
        ( 0.090,  1.000, "Urbanización alta")
    ],

    "MSAVI": [
        (-1.00, 0.00, "Suelo desnudo"),
        ( 0.00, 0.20, "Vegetación escasa"),
        ( 0.20, 0.40, "Vegetación baja"),
        ( 0.40, 0.60, "Vegetación moderada"),
        ( 0.60, 1.00, "Vegetación densa")
    ],

    "NDMI": [
        (-1.0, -0.2, "Estrés hídrico severo"),
        (-0.2,  0.0, "Estrés hídrico moderado"),
        ( 0.0,  0.2, "Humedad baja"),
        ( 0.2,  0.4, "Humedad moderada"),
        ( 0.4,  1.0, "Humedad alta")
    ],

    "NBR": [
        (-1.00, -0.25, "Alta severidad de quema"),
        (-0.25, -0.10, "Moderada-alta severidad"),
        (-0.10,  0.10, "Baja severidad"),
        ( 0.10,  0.27, "Área no quemada"),
        ( 0.27,  1.00, "Vegetación sana")
    ],

    "LST": [
        (-20,  0, "Muy frío"),
        (  0, 15, "Frío"),
        ( 15, 25, "Templado"),
        ( 25, 35, "Cálido"),
        ( 35, 60, "Muy cálido")
    ],

}

# =====================================================
# ESTILOS
# =====================================================

ESTILOS = { #trabajar etiquetas este modulo

    "TURBIDEZ": {
        "tipo": "pseudocolor",
        "colores": [
            "#08306b",
            "#4292c6",
            "#c7e9b4",
            "#d8b365",
            "#8c510a"
        ]
    },

    "VIENTO": {
        "tipo": "pseudocolor",
        "min": 0,
        "max": 10,
        "colores": ["#ffffff", "#ffff00", "#ff0000"] # De calma (blanco) a fuerte (rojo)
    },

    "LLUVIA": {
        "tipo": "pseudocolor",
        "min": 0,
        "max": 1000,
        "colores": ["#ffffff", "#00ffff", "#0000ff", "#ff00ff"]
    },

    "USO_SUELO": {
        "tipo": "pseudocolor",
        "min": 0,
        "max": 8,
        "colores": [
            (0, "#419BDF"), # Agua
            (1, "#397D49"), # Árboles
            (2, "#88B053"), # Pasto
            (3, "#7A87C6"), # Vegetación inundada
            (4, "#E49635"), # Cultivos
            (5, "#DFC35A"), # Arbustos
            (6, "#C4281B"), # Área construida
            (7, "#A59B8F"), # Suelo desnudo
            (8, "#B39FE1")  # Nieve
        ]
    },

    "ESA_WORLDCOVER": {
        "tipo": "pseudocolor",
        "min": 10,
        "max": 100,
        "colores": [
            (10, "#006400"),  # Árboles
            (20, "#ffbb22"),  # Arbustos
            (30, "#ffff4c"),  # Pasto
            (40, "#f096ff"),  # Cultivos
            (50, "#fa0000"),  # Área construida
            (60, "#b4b4b4"),  # Suelo desnudo
            (70, "#f0f0f0"),  # Nieve
            (80, "#0064c8"),  # Agua
            (90, "#0096a0"),  # Vegetación inundada
            (95, "#00cf75"),  # Manglares
            (100,"#fae6a0")   # Musgo
        ]
    },

    "VEGETACION": {
        "tipo": "pseudocolor",
        "min": -0.5,
        "max": 1.0,
        "colores": [
            (-0.5, "#0c0c0c"),
            (0.0,  "#eaeaea"),
            (0.1,  "#ccc682"),
            (0.2,  "#91bf51"),
            (0.3,  "#70a33f"),
            (0.4,  "#4f892d"),
            (0.5,  "#306d1c"),
            (0.6,  "#0f540a"),
            (1.0,  "#004400")
        ]
    },

    "AGUA": {
        "tipo": "pseudocolor",
        "min": -1.0,
        "max": 1.0,
        "colores": [
            (-1.0, "#5b3a29"),
            (-0.5, "#8c6d5a"),
            (0.0,  "#f2f2f2"),
            (0.2,  "#b9e3f9"),
            (0.4,  "#7fc8f8"),
            (0.6,  "#3fa9f5"),
            (0.8,  "#0077cc"),
            (1.0,  "#003f88")
        ]
    },

    "URBANIZACION": {
        "tipo": "pseudocolor",
        "min": -1.0,
        "max": 1.0,
        "colores": [
            (-1.0, "#00441b"),   # vegetación muy densa
            (-0.3, "#238b45"),   # vegetación
            ( 0.0, "#ffffcc"),   # transición
            ( 0.2, "#fdae61"),   # suelo desnudo
            ( 0.4, "#f46d43"),   # urbano bajo
            ( 0.6, "#d73027"),   # urbano
            ( 1.0, "#7f0000")    # urbano muy intenso
        ]
    },

    "EBBI": {
        "tipo": "pseudocolor",
        "colores": [
            "#00441b",   # Valores bajos (vegetación)
            "#238b45",
            "#ffffcc",   # Valores medios (transición)
            "#fdae61",
            "#f46d43",
            "#d73027",
            "#7f0000"    # Valores altos (urbano/suelo desnudo)
        ]
    },

    "HUMEDAD": {
        "tipo": "pseudocolor",
        "min": -0.8,
        "max": 0.8,  # Ajustamos los límites generales al estándar
        "colores": [
            (-0.800, "#800000"),  # Granate / Estrés extremo
            (-0.240, "#ff0000"),  # Rojo / Estrés moderado
            (-0.032, "#ffff00"),  # Amarillo / Transición
            ( 0.032, "#00ffff"),  # Cian / Humedad óptima
            ( 0.240, "#0000ff"),  # Azul / Alta humedad
            ( 0.800, "#000080")   # Azul marino / Saturación
        ]
    },

    "INCENDIOS": {
        "tipo": "pseudocolor",
        "min": -1.0,
        "max": 1.0,
        "colores": [
            (-1.0, "#000000"), 
            (-0.5, "#a50026"),
            (0.0,  "#fdae61"),
            (0.5,  "#a6d96a"),
            (1.0,  "#1a9850") 
        ]
    },

    "TEMPERATURA": {
        "tipo": "pseudocolor",
        "colores": [
            "#313695",
            "#74add1",
            "#e0f3f8",
            "#fdae61",
            "#f46d43",
            "#a50026"
        ]
    },

    "DEM": {
        "tipo": "singlebandgray",
        "contraste": {
            "modo": "cumulative",
            "min": 2,
            "max": 98
        }
    },

    "DEM_RELIEVE": {
        "tipo": "singlebandgray",
        "hillshade": True,
        "estilo": "DEM",
        "contraste": {
            "modo": "cumulative",
            "min": 5,
            "max": 95
        }
    },

    "PENDIENTE": {
        "tipo": "singlebandgray",
        "tipo": "pseudocolor",
        "min": 0,
        "max": 45,
        "colores": [
            (0,   "#1a9850"),
            (5,   "#66bd63"),
            (10,  "#a6d96a"),
            (15,  "#d9ef8b"),
            (20,  "#fee08b"),
            (25,  "#fdae61"),
            (30,  "#f46d43"),
            (35,  "#d73027"),
            (45,  "#7f0000")
        ]
    },

    "ASPECT": {
        "tipo": "pseudocolor",
        "min": 0,
        "max": 360,
        "colores": [
            (0,   "#ff0000"),   # Norte
            (45,  "#ff7f00"),   # Noreste
            (90,  "#ffff00"),   # Este
            (135, "#00ff00"),   # Sudeste
            (180, "#00ffff"),   # Sur
            (225, "#0000ff"),   # Sudoeste
            (270, "#8b00ff"),   # Oeste
            (315, "#ff00ff"),   # Noroeste
            (360, "#ff0000")    # Norte nuevamente
        ]
    },

    "CURVATURA": {
        "tipo": "pseudocolor",
        "colores": [
            "#08306b",
            "#4292c6",
            "#f7f7f7",
            "#fb6a4a",
            "#99000d"
        ]
    },
    
    "TRI": {
        "tipo": "pseudocolor",
        "colores": [
            "#f7f4ea",
            "#d9c7a3",
            "#b08b5a",
            "#7a5230",
            "#3d2413"
        ]
    },

    "TPI": {
        "tipo": "pseudocolor",
        "colores": [
            "#2166ac",
            "#67a9cf",
            "#ffffcc",
            "#d8b365",
            "#8c510a"
        ]
    },

    "IRREGULARIDAD": {
        "tipo": "pseudocolor",
        "colores": [
            "#08306b",
            "#4292c6",
            "#f7f7f7",
            "#fb6a4a",
            "#99000d"
        ]
    },

}

# =====================================================
# REFERENCIAS DE COLOR PARA EL INFORME TEXTUAL
# =====================================================

REFERENCIAS_COLOR = {

    "NDTI": {
        "Turbidez muy baja": "Azul oscuro",
        "Turbidez baja": "Azul",
        "Turbidez moderada": "Verde claro",
        "Turbidez alta": "Ocre",
        "Turbidez muy alta": "Marrón"
    },
    
    "ESA_WORLDCOVER": {
        "Árboles": "Verde oscuro",
        "Arbustos / Matorrales": "Ocre / Naranja",
        "Pasto / Vegetación baja": "Amarillo",
        "Cultivos": "Rosa",
        "Área construida (Urbana)": "Rojo",
        "Suelo desnudo": "Gris",
        "Agua": "Azul"
    },
    
    "DYNAMIC_WORLD": {
        "Agua": "Azul",
        "Árboles": "Verde oscuro",
        "Pasto / Vegetación baja": "Verde claro",
        "Vegetación inundada": "Celeste / Lila",
        "Cultivos": "Naranja",
        "Arbustos / Matorrales": "Amarillo",
        "Área construida (Urbana)": "Rojo",
        "Suelo desnudo": "Gris"
    },
    
    "NDVI": {
        "Agua": "Negro / Marrón",
        "Suelo desnudo": "Gris",
        "Vegetación escasa": "Amarillo verdoso",
        "Vegetación baja": "Verde claro",
        "Vegetación moderada": "Verde medio",
        "Vegetación densa": "Verde oscuro",
        "Vegetación muy densa": "Verde muy oscuro"
    },

    "EBBI": {
        "Vegetación": "Verde oscuro",
        "Transición": "Amarillo",
        "Suelo": "Naranja",
        "Urbanización baja": "Rojo claro",
        "Urbanización media": "Rojo fuerte",
        "Urbanización alta": "Bordó"
    },

    "MSAVI": {
        "Suelo desnudo": "Gris claro",
        "Vegetación escasa": "Amarillo verdoso",
        "Vegetación baja": "Verde claro",
        "Vegetación moderada": "Verde medio",
        "Vegetación densa": "Verde oscuro"
    },

    "NBR": {
        "Alta severidad de quema": "Negro",
        "Moderada-alta severidad": "Rojo",
        "Baja severidad": "Naranja",
        "Área no quemada": "Verde claro",
        "Vegetación sana": "Verde oscuro"
    },

    "NDWI": {
        "Agua muy baja": "Marrón",
        "Agua baja": "Beige",
        "Agua moderada": "Celeste claro",
        "Agua alta": "Celeste",
        "Agua muy alta": "Azul oscuro"
    },

    "MNDWI": {
        "Suelo muy seco": "Marrón",
        "Suelo": "Beige",
        "Transición": "Gris claro",
        "Humedad": "Celeste claro",
        "Agua somera": "Celeste",
        "Agua": "Azul",
        "Agua profunda": "Azul oscuro"
    },

    "NDMI": {
        "Estrés hídrico severo": "Bordó",
        "Estrés hídrico moderado": "Rojo",
        "Humedad baja": "Amarillo",
        "Humedad moderada": "Celeste",
        "Humedad alta": "Azul oscuro"
    },

    "NDBI": {
        "Vegetación": "Verde oscuro",
        "Suelo": "Verde claro",
        "Transición": "Amarillo",
        "Urbanización baja": "Naranja",
        "Urbanización media": "Rojo",
        "Urbanización alta": "Bordó"
    },

    "LST": {
        "Muy frío": "Azul oscuro",
        "Frío": "Celeste",
        "Templado": "Blanco / gris claro",
        "Cálido": "Naranja",
        "Muy cálido": "Rojo"
    }

    # DYNAMIC_WORLD y ESA_WORLDCOVER ya estaban arriba.
}

# =====================================================
# FUENTES
# =====================================================

FUENTES = {

    "ERA5_LAND": {
        "id": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "tipo": "coleccion",
        "resolucion": 11132,
        "bandas": {
            "U": "u_component_of_wind_10m",
            "V": "v_component_of_wind_10m"
        }
    },

    "CHIRPS": {
        "id": "UCSB-CHG/CHIRPS/DAILY",
        "tipo": "coleccion",
        "resolucion": 5566,  # Resolución nativa de CHIRPS (aprox 5.5 km)
        "bandas": {
            "PRECIPITACION": "precipitation"
        }
    },

    "ESA_WORLDCOVER": {
        "id": "ESA/WorldCover/v200",
        "tipo": "coleccion",
        "resolucion": 10,
        "bandas": {
            "LABEL": "Map"
        }
    },

    "DYNAMIC_WORLD": {
        "id": "GOOGLE/DYNAMICWORLD/V1",
        "tipo": "coleccion",
        "resolucion": 10,
        "bandas": {
            "LABEL": "label"
        }
    },

    "COPERNICUS_DEM": {
        "id": "COPERNICUS/DEM/GLO30",
        "tipo": "coleccion",
        "resolucion": 30
    },

    "COPERNICUS_S2": {

        "id": "COPERNICUS/S2_SR_HARMONIZED",
        "tipo": "coleccion",
        "resolucion": 10,  # valor por defecto; motor.py lo sobreescribe según config
        "bandas": {
            "RED": "B4",
            "GREEN": "B3",
            "BLUE": "B2",
            "NIR": "B8",
            "SWIR1": "B11",
            "SWIR2": "B12"
        },
        "nubosidad": "CLOUDY_PIXEL_PERCENTAGE",
        "factor_escala": 1,
        "offset": 0
    },

    "LANDSAT_9": {
            "id": "LANDSAT/LC09/C02/T1_L2",
            "tipo": "coleccion",
            "resolucion": 30,
            "bandas": {
                "RED": "SR_B4",
                "GREEN": "SR_B3",
                "BLUE": "SR_B2",
                "NIR": "SR_B5",
                "SWIR1": "SR_B6",
                "SWIR2": "SR_B7",
                "THERMAL": "ST_B10"
            },
            "nubosidad": "CLOUD_COVER",
            "factor_escala": 0.0000275,
            "offset": -0.2
        },

    "LANDSAT_8": {
        "id": "LANDSAT/LC08/C02/T1_L2",
        "tipo": "coleccion",
        "resolucion": 30,
        "bandas": {
            "RED": "SR_B4",
            "GREEN": "SR_B3",
            "BLUE": "SR_B2",
            "NIR": "SR_B5",
            "SWIR1": "SR_B6",
            "SWIR2": "SR_B7",
            "THERMAL": "ST_B10"
        },
        "nubosidad": "CLOUD_COVER",
        "factor_escala": 0.0000275,
        "offset": -0.2
    },

    "LANDSAT_5": {
        "id": "LANDSAT/LT05/C02/T1_L2",
        "tipo": "coleccion",
        "resolucion": 30,
        "bandas": {
            "RED": "SR_B3",
            "GREEN": "SR_B2",
            "BLUE": "SR_B1",
            "NIR": "SR_B4",
            "SWIR1": "SR_B5",
            "SWIR2": "SR_B7",
            "THERMAL": "ST_B6",
        },
        "nubosidad": "CLOUD_COVER",
        "factor_escala": 0.0000275,
        "offset": -0.2
    }
}

# =====================================================
# REGLAS SATÉLITES PARA ÍNDICES
# =====================================================

REGLAS_SATELITES = {

    "NORMAL": [

        {
            "inicio": "2020-01-01",
            "fin": None,
            "fuente": "COPERNICUS_S2"
        },

        {
            "inicio": "2013-04-01",
            "fin": "2019-12-31",
            "fuente": "LANDSAT_8"
        },

        {
            "inicio": "1984-01-01",
            "fin": "2011-11-30",
            "fuente": "LANDSAT_5"
        }

    ],

    "TERMICO": [

        {
            "inicio": "2021-01-01",
            "fin": None,
            "fuente": "LANDSAT_9"
        },

        {
            "inicio": "2013-04-01",
            "fin": "2020-12-31",
            "fuente": "LANDSAT_8"
        },

        {
            "inicio": "1984-01-01",
            "fin": "2011-11-30",
            "fuente": "LANDSAT_5"
        }

    ]

}

# =====================================================
# PRODUCTOS TÉRMICOS
# =====================================================

PRODUCTOS_TERMICOS = {
    "EBBI": True,
    "LST": True,
    "UHI": True
}

# =====================================================
# FUENTES CON BANDA TÉRMICA
# =====================================================

FUENTES_TERMICAS = {

    "LANDSAT": [

        "LANDSAT_5",
        "LANDSAT_8",
        "LANDSAT_9"

    ]

}

# =====================================================
# REGLAS TEMPORALES
# =====================================================

REGLAS_TEMPORALES = {

    "NDTI": REGLAS_SATELITES["NORMAL"],
    "NDVI": REGLAS_SATELITES["NORMAL"],
    "NDWI": REGLAS_SATELITES["NORMAL"],
    "MNDWI": REGLAS_SATELITES["NORMAL"],
    "NDBI": REGLAS_SATELITES["NORMAL"],
    "MSAVI": REGLAS_SATELITES["NORMAL"],
    "NDMI": REGLAS_SATELITES["NORMAL"],
    "NBR": REGLAS_SATELITES["NORMAL"],
    "LST": REGLAS_SATELITES["TERMICO"],

    # Visualización de bandas crudas (RGB): mismo criterio que los
    # índices normales — prioriza Sentinel-2 desde 2020, Landsat 8
    # 2013-2019, Landsat 5 antes de eso.
    "BANDAS": REGLAS_SATELITES["NORMAL"],

    # Índices Térmicos
    "EBBI": REGLAS_SATELITES["TERMICO"],

    "DYNAMIC_WORLD": [
        {
            "inicio": "2015-06-27",
            "fin": None,
            "fuente": "DYNAMIC_WORLD"
        }
    ],

    "ESA_WORLDCOVER": [
        {
            "inicio": "2021-01-01",
            "fin": "2021-12-31",
            "fuente": "ESA_WORLDCOVER"
        }
    ],

    "CHIRPS": [
        {
            "inicio": "1981-01-01",
            "fin": None,
            "fuente": "CHIRPS"
        }
    ],

    "TERRACLIMATE": [
        {
            "inicio": "1958-01-01",
            "fin": None,
            "fuente": "TERRACLIMATE"
        }
    ],

    "ERA5_LAND": [
        {
            "inicio": "1950-01-01",
            "fin": None,
            "fuente": "ERA5_LAND"
        }
    ]

}

# =====================================================
# MENSAJES
# =====================================================

MENSAJES = {

    "inicio": "Iniciando Motor Geográfico...",

    "conexion": "Conectando con Google Earth Engine...",

    "consulta": "Consultando imágenes...",

    "producto": "Generando producto...",

    "visualizacion": "Cargando raster en QGIS...",

    "final": "Proceso finalizado correctamente.",

    "aplicando_estilo": "Aplicando estilo..."

}

# =====================================================
# CONSTANTES
# =====================================================

FORMATO_RASTER = "GEO_TIFF"

EXTENSION_RASTER = ".tif"

NODATA = -9999

# =====================================================
# PRESETS DE COMBINACIÓN DE BANDAS (RGB)
# =====================================================
# Combinaciones estándar de la industria (las mismas que usa
# Copernicus Browser / Sentinel Hub / la mayoría de los visores
# satelitales). Definidas por ROL (RED, GREEN, BLUE, NIR, SWIR1,
# SWIR2), no por código de banda crudo, para que funcionen igual
# en Sentinel-2 o en Landsat sin duplicar nada por fuente.

PRESETS_BANDAS = {

    "Color natural (True Color)": ("RED", "GREEN", "BLUE"),

    "Infrarrojo color / Falso color vegetación": ("NIR", "RED", "GREEN"),

    "Agricultura": ("SWIR1", "NIR", "BLUE"),

    "SWIR / Humedad y quemados": ("SWIR2", "NIR", "RED"),

    "Urbano": ("SWIR2", "SWIR1", "RED"),

    "Geología": ("SWIR2", "SWIR1", "BLUE"),

    "Fusión Tolari (NIR + SWIR)": "TOLARI",

    "Green City (Urbano B&N + Vegetación)": "GREEN_CITY"

} 