"""Panel de mapa nativo usando tkintermapview optimizado con figuras y botón de centrado."""

import tkinter as tk
from tkinter import ttk
import tkintermapview
import math

from frontend.mapa_datos import encuadre, seleccionar_puntos


class PanelMapa(ttk.Frame):
    """Panel que incrusta un mapa interactivo nativo directamente en tkinter."""

    def __init__(self, master):
        super().__init__(master)
        self.on_click = None

        # Barra de estado superior
        frame_estado = ttk.Frame(self)
        frame_estado.pack(side="top", fill="x", padx=2, pady=2)

        self.status = ttk.Label(frame_estado, text="Sin datos espaciales", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=4)

        # El widget del mapa nativo
        self.mapa = tkintermapview.TkinterMapView(self, corner_radius=0)
        self.mapa.pack(fill="both", expand=True)

        # --- BOTÓN PARA CENTRAR LA VISTA ---
        self.btn_centrar = tk.Button(
            self, text="⦿", font=("Arial", 9, "bold"),
            bg="#ffffff", fg="#333333", cursor="hand2", relief="raised",
            command=self._centrar_mapa
        )
        # Lo colocamos flotando en la esquina inferior derecha del mapa
        self.btn_centrar.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

        # --- AJUSTE DE FLUIDEZ ---
        if hasattr(self.mapa, 'image_load_thread_pool') and isinstance(self.mapa.image_load_thread_pool, list):
            self.mapa.image_load_thread_pool = self.mapa.image_load_thread_pool[:4]

        # --- SERVIDOR DE MAPAS (Google Maps) ---
        self.mapa.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)

        # Configuración inicial (Lima, Perú)
        self.mapa.set_position(-12.0464, -77.0428)
        self.mapa.set_zoom(12)

        # Eventos
        self.mapa.add_right_click_menu_command(label="Insertar POINT aquí", command=self._clicked_derecho,
                                               pass_coords=True)
        # Con la pestaña oculta el mapa no conoce su tamaño: se encuadra al mostrarla.
        self.bind("<Map>", self._al_mostrar)
        # add="+": tkintermapview usa este mismo evento para actualizar sus dimensiones.
        self.mapa.bind("<Configure>", self._al_redimensionar, add="+")
        self.redimension = None

        # Variables de estado
        self.marcadores_dict = {}
        self.tabla_actual = None
        self.figura_circulo = None
        self.figura_poligono = None
        self.marcador_centro = None

        # Vista del botón de centrar
        self.encuadre = None
        self.encuadre_pendiente = False

    def _clicked_derecho(self, coords):
        lat, lon = coords
        self._notificar_clic(lat, lon)

    def _notificar_clic(self, lat, lon):
        self.status.config(text=f"Punto seleccionado: POINT({lat:.6f}, {lon:.6f})")
        if self.on_click:
            self.on_click(lat, lon)

    def _centrar_mapa(self):
        """Vuelve a encuadrar el mapa en la vista de la última consulta."""
        if self.encuadre is None:
            return
        self.encuadre_pendiente = not self.winfo_viewable()
        if not self.encuadre_pendiente:
            self.mapa.fit_bounding_box(*self.encuadre)

    def _al_mostrar(self, event):
        if self.encuadre_pendiente:
            self._centrar_mapa()

    def _al_redimensionar(self, event):
        # El encuadre depende del tamaño: se repite cuando el tamaño deja de cambiar.
        if self.redimension is not None:
            self.after_cancel(self.redimension)
        self.redimension = self.after(150, self._tras_redimensionar)

    def _tras_redimensionar(self):
        self.redimension = None
        self._centrar_mapa()

    def actualizar(self, payload):
        if payload is None:
            return

        points = payload.get("points", [])
        result_ids = set(payload.get("result_ids", []))
        tabla_nombre = payload.get("table")

        if tabla_nombre != self.tabla_actual or not points:
            self.limpiar()
            self.tabla_actual = tabla_nombre

        # Borrar TODOS los dibujos anteriores
        self._borrar_dibujos()

        # --- DIBUJADO INTELIGENTE ---
        dibujados = seleccionar_puntos(points, result_ids)
        for p_id, lat, lon, label in dibujados:
            color = "red" if p_id in result_ids else "blue"
            self.marcadores_dict[p_id] = self.mapa.set_marker(lat, lon, text=str(label), marker_color_circle=color)

        figuras = self._dibujar_circulo(payload.get("circle")) + self._dibujar_poligono(payload.get("polygon"))

        estado = f"{len(points)} punto(s), {len(result_ids)} en el resultado"
        if len(dibujados) < len(points):
            estado += f" ({len(dibujados)} dibujados)"
        self.status.config(text=estado)

        # Ajustar la vista: la consulta manda; sin figura ni resultados, los puntos dibujados.
        resultado = [(lat, lon) for p_id, lat, lon, _ in dibujados if p_id in result_ids]
        self.encuadre = encuadre(figuras + resultado or [(p[1], p[2]) for p in dibujados])
        self._centrar_mapa()

    def _dibujar_circulo(self, circle_data):
        """Dibuja el centro y, si hay radio, el círculo. Devuelve sus coordenadas."""
        if not circle_data:
            return []

        lat, lon, radio = circle_data["lat"], circle_data["lon"], circle_data["radius"]
        self.marcador_centro = self.mapa.set_marker(lat, lon, text="Consulta", marker_color_circle="white",
                                                    marker_color_outside="#2e7d32")
        if radio <= 0:
            return [(lat, lon)]

        puntos_circulo = self._generar_puntos_circulo(lat, lon, radio)
        self.figura_circulo = self.mapa.set_polygon(puntos_circulo, outline_color="red", fill_color=None,
                                                    border_width=2)
        return puntos_circulo

    def _dibujar_poligono(self, polygon_data):
        """Dibuja el polígono de WITHIN. Devuelve sus coordenadas."""
        if not polygon_data:
            return []

        self.figura_poligono = self.mapa.set_polygon(polygon_data, outline_color="green", fill_color=None,
                                                     border_width=2)
        return list(polygon_data)

    def _generar_puntos_circulo(self, lat_centro, lon_centro, radio_metros, num_puntos=36):
        R = 6378137.0
        lat_rad = math.radians(lat_centro)
        lon_rad = math.radians(lon_centro)
        puntos = []

        for i in range(num_puntos):
            angulo = (i * 360.0) / num_puntos
            angulo_rad = math.radians(angulo)
            lat_punto = math.asin(math.sin(lat_rad) * math.cos(radio_metros / R) +
                                  math.cos(lat_rad) * math.sin(radio_metros / R) * math.cos(angulo_rad))
            lon_punto = lon_rad + math.atan2(math.sin(angulo_rad) * math.sin(radio_metros / R) * math.cos(lat_rad),
                                             math.cos(radio_metros / R) - math.sin(lat_rad) * math.sin(lat_punto))
            puntos.append((math.degrees(lat_punto), math.degrees(lon_punto)))
        return puntos

    def _borrar_dibujos(self):
        figuras = [self.figura_circulo, self.figura_poligono, self.marcador_centro]
        for dibujo in [*self.marcadores_dict.values(), *figuras]:
            if dibujo:
                dibujo.delete()
        self.marcadores_dict.clear()
        self.figura_circulo = self.figura_poligono = self.marcador_centro = None

    def limpiar(self):
        self._borrar_dibujos()
        self.tabla_actual = None
        self.encuadre = None
        self.encuadre_pendiente = False
        self.status.config(text="Sin datos espaciales")

    def close(self):
        pass
