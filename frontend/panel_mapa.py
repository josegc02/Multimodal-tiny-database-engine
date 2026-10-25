"""Panel de mapa nativo usando tkintermapview optimizado con figuras y botón de centrado."""

import tkinter as tk
from tkinter import ttk
import tkintermapview
import math

class PanelMapa(ttk.LabelFrame):
    """Panel que incrusta un mapa interactivo nativo directamente en tkinter."""

    def __init__(self, master):
        super().__init__(master, text="Mapa Espacial")
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
        self.mapa.add_right_click_menu_command(label="Insertar POINT aquí", command=self._clicked_derecho)

        # Variables de estado
        self.marcadores_dict = {}
        self.tabla_actual = None
        self.figura_circulo = None
        self.figura_poligono = None

        # Coordenadas para el botón de centrar
        self.centro_busqueda = None
        self.zoom_busqueda = 11

    def _clicked_derecho(self, coords):
        lat, lon = coords
        self._notificar_clic(lat, lon)

    def _notificar_clic(self, lat, lon):
        self.status.config(text=f"Punto seleccionado: POINT({lat:.6f}, {lon:.6f})")
        if self.on_click:
            self.on_click(lat, lon)

    def _centrar_mapa(self):
        """Vuelve a centrar el mapa en la vista de la última consulta."""
        if self.centro_busqueda:
            lat, lon = self.centro_busqueda
            self.mapa.set_position(lat, lon)
            self.mapa.set_zoom(self.zoom_busqueda)

    def actualizar(self, payload):
        if payload is None:
            return

        points = payload.get("points", [])
        result_ids = set(payload.get("result_ids", []))
        tabla_nombre = payload.get("table")

        # Extraer datos de figuras
        circle_data = payload.get("circle")
        polygon_data = payload.get("polygon")

        if tabla_nombre != self.tabla_actual or not points:
            self.limpiar()
            self.tabla_actual = tabla_nombre

        # Borrar TODOS los marcadores anteriores
        for m in self.marcadores_dict.values():
            try:
                m.delete()
            except Exception:
                pass
        self.marcadores_dict.clear()

        # --- DIBUJADO INTELIGENTE ---
        # Si hay demasiados puntos, solo dibujamos los que están en el resultado (rojos)
        dibujar_todos = len(points) < 100

        puntos_dibujados = []
        for p in points:
            p_id, lat, lon, label = p

            if not dibujar_todos and p_id not in result_ids:
                continue

            color = "red" if p_id in result_ids else "blue"
            marcador = self.mapa.set_marker(lat, lon, text=str(label), marker_color_circle=color)
            self.marcadores_dict[p_id] = marcador
            puntos_dibujados.append(p)

        # Manejo del Círculo (Radio)
        if circle_data:
            self._dibujar_circulo(circle_data)
            # Si el motor envía el círculo, el centro de búsqueda es el centro del círculo
            try:
                self.centro_busqueda = (float(circle_data[0]), float(circle_data[1]))
                self.zoom_busqueda = 12
            except:
                pass
        else:
            if self.figura_circulo:
                self.figura_circulo.delete()
                self.figura_circulo = None

        # Manejo del Polígono
        if polygon_data:
            self._dibujar_poligono(polygon_data)
        else:
            if self.figura_poligono:
                self.figura_poligono.delete()
                self.figura_poligono = None

        self.status.config(text=f"{len(points)} punto(s), {len(result_ids)} en el resultado")

        # Ajustar la vista
        if puntos_dibujados:
            self._ajustar_vista(puntos_dibujados)

    def _dibujar_circulo(self, circle_data):
        if self.figura_circulo:
            try:
                self.figura_circulo.delete()
            except Exception:
                pass
            finally:
                self.figura_circulo = None

        try:
            if not isinstance(circle_data, (list, tuple)) or len(circle_data) < 3:
                return

            lat = circle_data[0]
            lon = circle_data[1]
            radio = circle_data[2]

            if isinstance(lat, str) and lat == "lat":
                return

            lat = float(lat)
            lon = float(lon)
            radio = float(radio)

            puntos_circulo = self._generar_puntos_circulo(lat, lon, radio)

            def dibujar():
                try:
                    if self.winfo_exists():
                        self.figura_circulo = self.mapa.set_polygon(
                            puntos_circulo,
                            outline_color="red",
                            fill_color=None,
                            border_width=2
                        )
                except Exception as e:
                    print(f"No se pudo dibujar el círculo: {e}")

            self.after(100, dibujar)

        except Exception as e:
            print(f"Nota: No se pudo dibujar el círculo (datos inválidos): {e}")

    def _dibujar_poligono(self, polygon_data):
        if self.figura_poligono:
            try:
                self.figura_poligono.delete()
            except Exception:
                pass
            finally:
                self.figura_poligono = None

        # Calcular el centro del polígono para el botón de centrar
        try:
            lats = [p[0] for p in polygon_data]
            lons = [p[1] for p in polygon_data]
            self.centro_busqueda = (sum(lats)/len(lats), sum(lons)/len(lons))
            self.zoom_busqueda = 9
        except:
            pass

        def dibujar():
            try:
                if self.winfo_exists():
                    self.figura_poligono = self.mapa.set_polygon(
                        polygon_data,
                        outline_color="green",
                        fill_color=None,
                        border_width=2
                    )
            except Exception as e:
                print(f"No se pudo dibujar el polígono: {e}")

        self.after(100, dibujar)

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

    def _ajustar_vista(self, points):
        if not points:
            return

        if len(points) == 1:
            self.centro_busqueda = (points[0][1], points[0][2])
            self.zoom_busqueda = 14
            self.mapa.set_position(*self.centro_busqueda)
            self.mapa.set_zoom(self.zoom_busqueda)
            return

        avg_lat = sum(p[1] for p in points) / len(points)
        avg_lon = sum(p[2] for p in points) / len(points)

        self.centro_busqueda = (avg_lat, avg_lon)
        self.zoom_busqueda = 10

        self.after(100, lambda: self.mapa.set_position(avg_lat, avg_lon))
        self.after(150, lambda: self.mapa.set_zoom(self.zoom_busqueda))

    def limpiar(self):
        for m in self.marcadores_dict.values():
            try:
                m.delete()
            except Exception:
                pass
        self.marcadores_dict.clear()

        if self.figura_circulo:
            try:
                self.figura_circulo.delete()
            except Exception:
                pass
            self.figura_circulo = None

        if self.figura_poligono:
            try:
                self.figura_poligono.delete()
            except Exception:
                pass
            self.figura_poligono = None

        self.tabla_actual = None
        self.centro_busqueda = None
        self.status.config(text="Sin datos espaciales")

    def close(self):
        pass