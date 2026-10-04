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

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import ttk


class MapServer:
    """Servidor local que entrega Leaflet y una API JSON de estado/clicks."""

    def __init__(self, on_click=None):
        self.state = {"points": [], "highlighted": [], "circle": None, "polygon": None}
        self.on_click = on_click
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/state":
                    self.respond("application/json", json.dumps(server.state))
                elif self.path == "/":
                    self.respond("text/html; charset=utf-8", server.html())
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/api/click":
                    self.send_error(404); return
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    data = json.loads(self.rfile.read(size))
                    lat, lon = float(data["lat"]), float(data["lng"])
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    self.send_error(400); return
                if server.on_click:
                    server.on_click(lat, lon)
                self.respond("application/json", "{}")

            def respond(self, kind, body):
                data = body.encode(); self.send_response(200)
                self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)

            def log_message(self, *_): pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}/"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def html():
        return '''<!doctype html><html><head><meta charset=utf-8><title>Mapa espacial</title><link rel=stylesheet href=https://unpkg.com/leaflet@1.9.4/dist/leaflet.css><style>html,body,#map{height:100%;margin:0}</style></head><body><div id=map></div><script src=https://unpkg.com/leaflet@1.9.4/dist/leaflet.js></script><script>const map=L.map('map').setView([-12.0464,-77.0428],12);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);let layer=L.layerGroup().addTo(map);async function draw(){let s=await(await fetch('/api/state')).json();layer.clearLayers();let ids=new Set(s.highlighted),b=[];for(let p of s.points){L.circleMarker([p.lat,p.lon],{radius:ids.has(p.id)?8:5,color:ids.has(p.id)?'#e63946':'#2563eb',fillOpacity:.8}).bindPopup(p.label).addTo(layer);b.push([p.lat,p.lon])}if(s.circle){L.circle([s.circle.lat,s.circle.lon],{radius:s.circle.radius,color:'#f59e0b'}).addTo(layer);b.push([s.circle.lat,s.circle.lon])}if(s.polygon){L.polygon(s.polygon,{color:'#16a34a'}).addTo(layer);b.push(...s.polygon)}if(b.length)map.fitBounds(b,{padding:[20,20],maxZoom:15})}map.on('click',e=>fetch('/api/click',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(e.latlng)}));draw();setInterval(draw,1000);</script></body></html>'''

    def close(self):
        self.http.shutdown(); self.http.server_close()


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
        self.server = MapServer(self._clicked)
        self.status = ttk.Label(self, text="Sin datos espaciales", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(self, text="Abrir mapa", command=lambda: webbrowser.open_new_tab(self.server.url)).pack(side="right", padx=8, pady=8)

    def _clicked(self, lat, lon):
        self.status.after(0, lambda: self.status.config(text=f"Punto seleccionado: POINT({lat:.6f}, {lon:.6f})"))
        if self.on_click: self.on_click(lat, lon)

    def mostrar_puntos(self, puntos):
        """Dibuja todos los puntos (agrupar en clusters si son muchos)."""
        self.server.state["points"] = [{"id": p[0], "lat": p[1], "lon": p[2], "label": str(p[3])} for p in puntos]
        self.status.config(text=f"{len(puntos)} punto(s); abre el mapa para verlos")

    def resaltar(self, ids):
        """Resalta con otro color los puntos devueltos por la consulta."""
        self.server.state["highlighted"] = list(ids)

    def dibujar_circulo(self, lat, lon, radio_m):
        """Punto de consulta y radio de una búsqueda por rango."""
        self.server.state["circle"] = {"lat": lat, "lon": lon, "radius": radio_m}

    def dibujar_poligono(self, vertices):
        """Polígono usado en una consulta de intersección."""
        self.server.state["polygon"] = [[lat, lon] for lat, lon in vertices]

    def limpiar(self):
        self.server.state = {"points": [], "highlighted": [], "circle": None, "polygon": None}
        self.status.config(text="Sin datos espaciales")

    def actualizar(self, payload):
        if payload is None: return
        self.mostrar_puntos(payload["points"]); self.resaltar(payload["result_ids"])
        self.server.state["circle"] = payload.get("circle"); self.server.state["polygon"] = payload.get("polygon")

    def close(self): self.server.close()
