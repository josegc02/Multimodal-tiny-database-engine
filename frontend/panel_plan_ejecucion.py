"""Panel de plan de ejecucion: muestra el QUERY PLAN de EXPLAIN / EXPLAIN ANALYZE."""

import tkinter as tk
from tkinter import ttk

AYUDA = (
    "El plan se muestra al ejecutar EXPLAIN, como en PostgreSQL:\n\n"
    "  EXPLAIN SELECT * FROM cuentas WHERE id = 1;\n"
    "  EXPLAIN ANALYZE SELECT * FROM cuentas ORDER BY saldo;\n\n"
    "EXPLAIN muestra el plan con costos estimados sin ejecutar la consulta.\n"
    "EXPLAIN ANALYZE la ejecuta y agrega tiempos y filas reales por operador."
)


class PanelPlanEjecucion(ttk.LabelFrame):
    """Texto monoespaciado con el árbol del plan (formato de psql).

    Uso:
        panel.mostrar_plan_texto("Seq Scan on cuentas  (cost=0.00..1.00 rows=3)")
        panel.limpiar()
    """

    def __init__(self, master):
        super().__init__(master, text="Plan de ejecucion")
        self._construir()
        self.limpiar()

    def _construir(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.texto = tk.Text(frame, wrap="none", font=("Consolas", 10), state="disabled")
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.texto.yview)
        scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.texto.xview)
        self.texto.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.texto.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x", padx=4)
        self.texto.tag_configure("ayuda", foreground="#666666")

    def _escribir(self, contenido, tag=None):
        self.texto.config(state="normal")
        self.texto.delete("1.0", tk.END)
        self.texto.insert("1.0", contenido, tag or ())
        self.texto.config(state="disabled")

    def limpiar(self):
        """Vuelve al texto de ayuda (las consultas normales no muestran plan)."""
        self._escribir(AYUDA, "ayuda")

    def mostrar_plan_texto(self, texto):
        """Muestra el QUERY PLAN (una cadena o una lista de líneas)."""
        if isinstance(texto, (list, tuple)):
            texto = "\n".join(texto)
        self._escribir("QUERY PLAN\n" + "-" * 60 + "\n" + texto)
