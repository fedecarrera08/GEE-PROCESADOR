# =====================================================
# __INIT__.PY
# QGIS busca acá la función classFactory() al cargar el
# plugin. No poner lógica del complemento en este archivo.
# =====================================================


def classFactory(iface):
    from .gee_procesador import GeeProcesador
    return GeeProcesador(iface)
