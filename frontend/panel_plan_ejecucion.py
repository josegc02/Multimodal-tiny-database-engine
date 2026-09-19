"""Panel de plan de ejecucion: visualiza el acceso fisico elegido."""

import tkinter as tk
from tkinter import ttk


class PanelPlanEjecucion(ttk.LabelFrame):
    """Panel que muestra el plan en una tabla jerarquica.

    Uso:
        panel.mostrar_plan_texto("Filter\\n  └── Scan (cuentas)")
        panel.mostrar_plan_objeto(plan)
        panel.limpiar()
    """

    def __init__(self, master):
        super().__init__(master, text="Plan de ejecucion")
        self._construir()

    def _construir(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        columnas = ("operation", "access", "index", "cost", "details")
        self.tabla = ttk.Treeview(frame, columns=columnas, show="tree headings",
                                  selectmode="browse")
        self.tabla.heading("#0", text="Node")
        self.tabla.column("#0", width=145, minwidth=100, stretch=False)
        encabezados = {
            "operation": "Operation",
            "access": "Access Method",
            "index": "Index",
            "cost": "Cost",
            "details": "Details",
        }
        anchos = {"operation": 105, "access": 145, "index": 145,
                  "cost": 70, "details": 360}
        for columna in columnas:
            self.tabla.heading(columna, text=encabezados[columna])
            self.tabla.column(columna, width=anchos[columna], minwidth=70,
                              stretch=columna == "details")
        self.tabla.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(frame, orient="vertical",
                                 command=self.tabla.yview)
        scroll_y.pack(side="right", fill="y")
        self.tabla.configure(yscrollcommand=scroll_y.set)

        scroll_x = ttk.Scrollbar(self, orient="horizontal",
                                 command=self.tabla.xview)
        scroll_x.pack(side="bottom", fill="x", padx=4)
        self.tabla.configure(xscrollcommand=scroll_x.set)

    def limpiar(self):
        """Limpia la tabla del plan."""
        self.tabla.delete(*self.tabla.get_children())

    def mostrar_plan_texto(self, texto):
        """Muestra texto heredado como una fila de detalles."""
        self.limpiar()
        self.tabla.insert("", "end", text="Plan", values=("", "", "", "", texto))

    def mostrar_plan_objeto(self, plan):
        """Muestra un plan a partir de su representacion dict.

        El plan debe tener un metodo to_dict() o ser un dict directo.
        """
        if hasattr(plan, "to_dict"):
            data = plan.to_dict()
        elif isinstance(plan, dict):
            data = plan
        else:
            self._set_texto(str(plan))
            return

        self.limpiar()
        self._insertar_nodo("", data)

    def _insertar_nodo(self, parent, nodo):
        """Inserta una fila y sus hijos conservando la jerarquia del plan."""
        if not isinstance(nodo, dict):
            self.tabla.insert(parent, "end", text=str(nodo), values=("", "", "", "", ""))
            return

        physical = nodo.get("physical") or {}
        operation = nodo.get("operation", "?")
        access = physical.get("algorithm", "logical")
        index = physical.get("index") or ""
        cost = physical.get("estimated_io", "")
        if isinstance(cost, float):
            cost = f"{cost:.2f}"
        details = physical.get("reason", "")
        item = self.tabla.insert(
            parent, "end", text=operation,
            values=(operation, access, index, cost, details), open=True,
        )
        for child in nodo.get("children", []):
            self._insertar_nodo(item, child)