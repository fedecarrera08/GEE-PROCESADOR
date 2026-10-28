# =====================================================
# GEE_PROCESADOR.PY
# Clase principal del plugin. Se encarga de:
#   - Agregar el ícono a la barra de herramientas y al menú
#   - Abrir el diálogo cuando el usuario hace clic
#   - Sacar todo prolijamente cuando se desactiva el plugin
#
# TODAVÍA NO llama al motor (motor.py) — eso lo conectamos
# en el próximo paso, cuando el diálogo tenga los campos
# reales.
# =====================================================

import os

from qgis.PyQt.QtWidgets import QAction, QApplication # type: ignore
from qgis.PyQt.QtGui import QIcon # type: ignore

from .gee_procesador_dialog import GeeProcesadorDialog


class GeeProcesador:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.accion = None
        self.dialogo = None

    def initGui(self):
        """QGIS llama esto una vez, al activar el plugin."""

        icono = QIcon(os.path.join(self.plugin_dir, "icon.png"))

        self.accion = QAction(icono, "GEE Procesador", self.iface.mainWindow())
        self.accion.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.accion)
        self.iface.addPluginToRasterMenu("GEE Procesador", self.accion)

    def unload(self):
        """QGIS llama esto al desactivar o desinstalar el plugin."""

        self.iface.removePluginRasterMenu("GEE Procesador", self.accion)
        self.iface.removeToolBarIcon(self.accion)

    def run(self):
        """Se ejecuta cada vez que el usuario hace clic en el ícono/menú."""

        if self.dialogo is None:
            self.dialogo = GeeProcesadorDialog()

        self.dialogo.cargar_capas_poligono()

        # Centrar la ventana en la pantalla cada vez que se abre — evita
        # que quede "perdida" arriba de todo después de usarla más de
        # una vez (Qt a veces arrastra una posición vieja rara).
        pantalla = QApplication.primaryScreen().availableGeometry()
        x = pantalla.center().x() - self.dialogo.width() // 2
        y = pantalla.center().y() - self.dialogo.height() // 2
        self.dialogo.move(x, y)

        self.dialogo.show()
        self.dialogo.exec_()