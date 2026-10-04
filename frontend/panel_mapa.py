"""Panel de mapa: puntos de una tabla espacial y resultados resaltados (issue #24).

El enunciado pide un mapa interactivo (Leaflet, Google Maps, etc.). Opciones
para este frontend en Tkinter (decisión pendiente del issue #24):

- tkintermapview: widget Tk con tiles de OpenStreetMap; marcadores, círculos,
  polígonos y clic en el mapa dentro de la misma ventana.
- Leaflet: generar un HTML con los puntos y abrirlo en el navegador, o servirlo
  con un endpoint HTTP local que entregue los puntos en GeoJSON.

La interfaz de abajo no depende de esa elección: main.py la llama tras cada
consulta espacial. Estado: estructura base.
"""

from tkinter import ttk


class PanelMapa(ttk.LabelFrame):
    """Mapa con los puntos de la tabla y los resultados de la consulta resaltados.

    Uso previsto:
        panel.mostrar_puntos(puntos)            # [(id, lat, lon, etiqueta)]
        panel.resaltar(ids)                     # resultados de la consulta
        panel.dibujar_circulo(lat, lon, radio_m)
        panel.dibujar_poligono([(lat, lon), ...])
        panel.on_click = lambda lat, lon: ...   # fija el punto de consulta
    """

    def __init__(self, master):
        super().__init__(master, text="Mapa")
        self.on_click = None
        ttk.Label(self, text="Panel de mapa: pendiente (issue #24)").pack(padx=8, pady=8)

    def mostrar_puntos(self, puntos):
        """Dibuja todos los puntos (agrupar en clusters si son muchos)."""
        raise NotImplementedError("Pendiente: issue #24")

    def resaltar(self, ids):
        """Resalta con otro color los puntos devueltos por la consulta."""
        raise NotImplementedError("Pendiente: issue #24")

    def dibujar_circulo(self, lat, lon, radio_m):
        """Punto de consulta y radio de una búsqueda por rango."""
        raise NotImplementedError("Pendiente: issue #24")

    def dibujar_poligono(self, vertices):
        """Polígono usado en una consulta de intersección."""
        raise NotImplementedError("Pendiente: issue #24")

    def limpiar(self):
        raise NotImplementedError("Pendiente: issue #24")
