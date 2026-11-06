import tkinter as tk
from tkinter import ttk


def es_numerica(valores):
    """True si la columna solo tiene números (los NULL no cuentan)."""
    presentes = [v for v in valores if v is not None]
    return bool(presentes) and all(type(v) in (int, float) for v in presentes)


class PanelResultados(ttk.Frame):
    """Panel con un Treeview para mostrar filas y columnas."""

    def __init__(self, master):
        super().__init__(master)
        self._construir()

    def _construir(self):
        style = ttk.Style(self)
        style.configure("Plan.Treeview", font=("Consolas", 10))

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.tree = ttk.Treeview(frame, show="headings", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll_y.set)

        scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        scroll_x.pack(fill="x", padx=4, pady=(0, 4))
        self.tree.configure(xscrollcommand=scroll_x.set)

        self.mensaje = ttk.Label(self, text="Sin resultados", anchor="w")
        self.mensaje.pack(fill="x", padx=4, pady=(0, 4))

    def limpiar(self):
        for col in self.tree["columns"]:
            self.tree.heading(col, text="")
        self.tree["columns"] = ()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.mensaje.config(text="Sin resultados")

    def mostrar_resultados(self, columnas, filas):
        self.limpiar()

        if not columnas:
            return

        self.tree["columns"] = list(columnas)
        es_plan = list(columnas) == ["QUERY PLAN"]
        self.tree.configure(style="Plan.Treeview" if es_plan else "Treeview")
        
        for i, col in enumerate(columnas):
            col_lower = col.lower()
            
            if es_numerica(fila[i] for fila in filas):
                alineacion = "e"
            else:
                alineacion = "w"
                
            self.tree.heading(col, text=col, anchor=alineacion)
            
            if es_plan:
                largo = max((len(str(fila[0])) for fila in filas), default=40)
                self.tree.column(col, width=max(400, largo * 8), stretch=True, anchor="w")
            elif "score" in col_lower or "relevancia" in col_lower:
                self.tree.column(col, width=100, anchor="e")
            elif "fragmento" in col_lower or "snippet" in col_lower:
                self.tree.column(col, width=400, anchor="w", stretch=True)
            else:
                self.tree.column(col, width=100, anchor=alineacion)

        for fila in filas:
            fila_formateada = []
            for i, val in enumerate(fila):
                col_lower = columnas[i].lower()
                
                if val is not None and ("score" in col_lower or "relevancia" in col_lower):
                    try:
                        val = f"{float(val):.4f}"
                    except (ValueError, TypeError):
                        pass
                elif val is not None and ("fragmento" in col_lower or "snippet" in col_lower):
                    val_str = str(val)
                    if len(val_str) > 150:
                        val = val_str[:147] + "..."
                        
                fila_formateada.append(val)
            
            self.tree.insert("", tk.END, values=tuple(fila_formateada))

        n = len(filas)
        self.mensaje.config(text=f"{n} fila(s)")

    def mostrar_mensaje(self, texto):
        self.limpiar()
        self.mensaje.config(text=texto)

    def mostrar_error(self, texto):
        self.limpiar()
        self.mensaje.config(text=f"Error: {texto}")