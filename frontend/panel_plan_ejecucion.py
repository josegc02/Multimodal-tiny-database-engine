"""Panel de plan de ejecucion: análisis por nodo de EXPLAIN / EXPLAIN ANALYZE.

El texto del QUERY PLAN ya aparece en Resultados (como en psql o pgAdmin con
F5). Este panel no lo repite: muestra el mismo árbol como tabla, al estilo de la
pestaña "Analysis" de pgAdmin, con una fila por operador y columnas de costo,
filas estimadas y reales, tiempos y loops.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

AYUDA = (
    "El plan se muestra al ejecutar EXPLAIN, como en PostgreSQL:\n\n"
    "  EXPLAIN SELECT * FROM cuentas WHERE id = 1;\n"
    "  EXPLAIN ANALYZE SELECT * FROM cuentas ORDER BY saldo;\n\n"
    "Resultados muestra el QUERY PLAN en texto; aquí aparece el mismo árbol\n"
    "como tabla, con una fila por operador.\n\n"
    "EXPLAIN muestra costos y filas estimadas sin ejecutar la consulta.\n"
    "EXPLAIN ANALYZE la ejecuta y agrega filas reales, tiempos y loops."
)

COLUMNAS = [
    ("costo", "Costo", 120, "e"),
    ("estimadas", "Filas est.", 75, "e"),
    ("reales", "Filas reales", 85, "e"),
    ("desvio", "Desvío est.", 85, "e"),
    ("exclusivo", "Excl. (ms)", 80, "e"),
    ("inclusivo", "Incl. (ms)", 80, "e"),
    ("loops", "Loops", 55, "e"),
]

# Desvío de la estimación de filas (como el "rows x" de pgAdmin y explain.depesz).
DESVIO_MEDIO = 2.0
DESVIO_ALTO = 10.0


def desvio_estimacion(estimadas, reales):
    """Factor entre filas estimadas y reales: (factor, "↑" subestimó / "↓" sobreestimó)."""
    estimadas, reales = max(estimadas, 1), max(reales, 1)
    if reales >= estimadas:
        return reales / estimadas, "↑"
    return estimadas / reales, "↓"


def filas_analisis(nodos):
    """Convierte los nodos del plan (preorden con profundidad) en filas de la tabla.

    Devuelve [(profundidad, etiqueta, valores, tag, detalles)]. El tiempo exclusivo
    es el inclusivo del nodo menos el de sus hijos directos. Bajo un Limit el hijo
    entrega menos filas de las estimadas porque el Limit deja de pedirle: no se
    marca como error de estimación.
    """
    filas = []
    padres = {}
    for i, nodo in enumerate(nodos):
        padres[nodo["depth"]] = nodo["label"]
        bajo_limit = nodo["depth"] > 0 and padres.get(nodo["depth"] - 1) == "Limit"
        hijos = []
        for siguiente in nodos[i + 1:]:
            if siguiente["depth"] <= nodo["depth"]:
                break
            if siguiente["depth"] == nodo["depth"] + 1:
                hijos.append(siguiente)
        costo = f"{nodo['startup']:.2f}..{nodo['cost']:.2f}"
        real = nodo.get("actual")
        if real is None:
            valores = (costo, nodo["rows"], "", "", "", "", "")
            tag = ""
        else:
            loops = real["loops"]
            inclusivo = real["total"] * 1000
            hijos_ms = sum(h["actual"]["total"] * 1000 for h in hijos if h.get("actual"))
            exclusivo = max(0.0, inclusivo - hijos_ms)
            factor, sentido = desvio_estimacion(nodo["rows"], real["rows"])
            valores = (costo, nodo["rows"], real["rows"], f"{sentido} {factor:.1f}x",
                       f"{exclusivo:.3f}", f"{inclusivo:.3f}", loops)
            tag = "alto" if factor >= DESVIO_ALTO else "medio" if factor >= DESVIO_MEDIO else ""
            if bajo_limit and sentido == "↓":
                tag = ""
        filas.append((nodo["depth"], nodo["label"], valores, tag, list(nodo.get("details", []))))
    return filas


class PanelPlanEjecucion(ttk.LabelFrame):
    """Árbol de operadores con costos, filas y tiempos.

    Uso:
        panel.mostrar_plan(nodos, analyze=True, tiempos=(0.0002, 0.0051))
        panel.limpiar()
    """

    def __init__(self, master):
        super().__init__(master, text="Plan de ejecucion")
        self._construir()
        self.limpiar()

    def _construir(self):
        self.ayuda = tk.Label(self, text=AYUDA, justify="left", anchor="nw", fg="#666666",
                              font=("Consolas", 10))

        self.frame_arbol = ttk.Frame(self)
        frame = ttk.Frame(self.frame_arbol)
        frame.pack(fill="both", expand=True)
        self.arbol = ttk.Treeview(frame, columns=[c[0] for c in COLUMNAS], selectmode="browse")
        self.arbol.heading("#0", text="Nodo", anchor="w")
        self.arbol.column("#0", width=300, minwidth=180, stretch=True)
        for clave, titulo, ancho, alineacion in COLUMNAS:
            self.arbol.heading(clave, text=titulo, anchor=alineacion)
            self.arbol.column(clave, width=ancho, minwidth=50, anchor=alineacion, stretch=False)
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.arbol.yview)
        scroll_x = ttk.Scrollbar(self.frame_arbol, orient="horizontal", command=self.arbol.xview)
        self.arbol.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.arbol.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(fill="x")

        cursiva = tkfont.nametofont("TkDefaultFont").copy()
        cursiva.configure(slant="italic")
        self.arbol.tag_configure("detalle", foreground="#666666", font=cursiva)
        self.arbol.tag_configure("medio", background="#fff3cd")
        self.arbol.tag_configure("alto", background="#f8d7da")

        self.pie = ttk.Label(self.frame_arbol, anchor="w", justify="left")
        self.pie.pack(fill="x", pady=(4, 0))

    def limpiar(self):
        """Vuelve al texto de ayuda (las consultas normales no muestran plan)."""
        self.arbol.delete(*self.arbol.get_children())
        self.frame_arbol.pack_forget()
        self.ayuda.pack(fill="both", expand=True, padx=8, pady=8)

    def mostrar_plan(self, nodos, analyze=False, tiempos=(None, None)):
        """Muestra el árbol del plan como tabla de análisis."""
        self.ayuda.pack_forget()
        self.frame_arbol.pack(fill="both", expand=True, padx=4, pady=4)
        self.arbol.delete(*self.arbol.get_children())

        padres = {-1: ""}
        for profundidad, etiqueta, valores, tag, detalles in filas_analisis(nodos):
            item = self.arbol.insert(padres[profundidad - 1], tk.END, text=etiqueta, values=valores,
                                     tags=(tag,) if tag else (), open=True)
            padres[profundidad] = item
            for detalle in detalles:
                self.arbol.insert(item, tk.END, text=detalle, tags=("detalle",))

        if analyze:
            planificacion, ejecucion = tiempos
            partes = []
            if planificacion is not None:
                partes.append(f"Planning Time: {planificacion * 1000:.3f} ms")
            if ejecucion is not None:
                partes.append(f"Execution Time: {ejecucion * 1000:.3f} ms")
            leyenda = (f"Desvío est.: filas reales vs estimadas (↑ subestimó, ↓ sobreestimó); "
                       f"amarillo ≥ {DESVIO_MEDIO:g}x, rojo ≥ {DESVIO_ALTO:g}x. "
                       "Excl. = tiempo propio del nodo sin sus hijos.")
            self.pie.config(text="   ".join(partes) + "\n" + leyenda)
        else:
            self.pie.config(text="EXPLAIN sin ANALYZE: costos y filas estimadas; la consulta no se ejecutó.")
