"""Panel de mapa: servidor local con Leaflet (frontend/mapa.html) y estado de la última consulta.

El navegador pide cada segundo la versión del estado y solo descarga y redibuja
cuando cambió, de modo que el mapa no pierde el zoom del usuario.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import ttk

HTML = Path(__file__).with_name("mapa.html")
EMPTY = {"table": None, "points": [], "highlighted": [], "circle": None, "polygon": None}


class MapServer:
    """API local: GET / (página), GET /api/version, GET /api/state y POST /api/click."""

    def __init__(self, on_click=None):
        self.on_click = on_click
        self._lock = threading.Lock()
        self.version = 0
        self._state, self._json = dict(EMPTY), json.dumps(EMPTY)
        self._points_source, self._points_json = None, "[]"
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    self.respond("text/html; charset=utf-8", HTML.read_text(encoding="utf-8"))
                elif self.path == "/api/version":
                    self.respond("application/json", json.dumps({"version": server.version}))
                elif self.path == "/api/state":
                    with server._lock:
                        body = server._json
                    self.respond("application/json", body)
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/api/click":
                    self.send_error(404)
                    return
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    data = json.loads(self.rfile.read(size))
                    lat, lon = float(data["lat"]), float(data["lng"])
                except (ValueError, TypeError, KeyError):
                    self.send_error(400)
                    return
                if server.on_click:
                    server.on_click(lat, lon)
                self.respond("application/json", "{}")

            def respond(self, kind, body):
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}/"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def state(self):
        return self._state

    def publish(self, **changes):
        """Actualiza el estado y arma su JSON una vez por versión.

        `points` es una lista de tuplas (id, lat, lon, etiqueta). Solo se vuelve a
        serializar si es otra lista: entre consultas a la misma tabla no cambia.
        """
        with self._lock:
            points = changes.pop("points", self._state["points"])
            if points is not self._points_source:
                self._points_source = points
                self._points_json = json.dumps([{"id": p[0], "lat": p[1], "lon": p[2], "label": str(p[3])}
                                                for p in points])
            self._state = {**self._state, **changes, "points": points}
            rest = json.dumps({key: value for key, value in self._state.items() if key != "points"})
            self._json = rest[:-1] + ', "points": ' + self._points_json + "}"
            self.version += 1

    def close(self):
        self.http.shutdown()
        self.http.server_close()


class PanelMapa(ttk.LabelFrame):
    """Barra con el estado del mapa y el botón para abrirlo en el navegador.

    Uso:
        panel.actualizar(resultado.mapa)        # tras cada SELECT sobre una tabla con POINT
        panel.on_click = lambda lat, lon: ...   # clic en el mapa
    """

    def __init__(self, master):
        super().__init__(master, text="Mapa")
        self.on_click = None
        self.server = MapServer(self._clicked)
        self.status = ttk.Label(self, text="Sin datos espaciales", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(self, text="Abrir mapa",
                   command=lambda: webbrowser.open_new_tab(self.server.url)).pack(side="right", padx=8, pady=8)

    def _clicked(self, lat, lon):
        # Llega desde el hilo del servidor: se pasa al hilo de Tk con after().
        def apply():
            self.status.config(text=f"Punto seleccionado: POINT({lat:.6f}, {lon:.6f})")
            if self.on_click:
                self.on_click(lat, lon)
        self.status.after(0, apply)

    def actualizar(self, payload):
        if payload is None:
            return
        self.server.publish(table=payload.get("table"), points=payload["points"],
                            highlighted=payload["result_ids"], circle=payload.get("circle"),
                            polygon=payload.get("polygon"))
        self.status.config(text=f"{len(payload['points'])} punto(s), {len(payload['result_ids'])} en el "
                                "resultado; pulsa «Abrir mapa» para verlos")

    def limpiar(self):
        self.server.publish(**EMPTY)
        self.status.config(text="Sin datos espaciales")

    def close(self):
        self.server.close()
