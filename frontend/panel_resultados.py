"""Panel de resultados: tabla que muestra los resultados de las consultas."""

import tkinter as tk
from tkinter import ttk


class PanelResultados(ttk.LabelFrame):
    """Panel con un Treeview para mostrar filas y columnas.

    Uso:
        panel.mostrar_resultados(["id", "nombre"], [[1, "Ana"], [2, "Bob"]])
        panel.limpiar()
        panel.mostrar_mensaje("3 filas afectadas")
    """

    def __init__(self, master):
        super().__init__(master, text="Resultados")
        self._construir()

    def _construir(self):
        # Treeview con scroll vertical y horizontal
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

        # Mensaje inferior
        self.mensaje = ttk.Label(self, text="Sin resultados", anchor="w")
        self.mensaje.pack(fill="x", padx=4, pady=(0, 4))

    def limpiar(self):
        """Borra todas las filas y columnas del Treeview."""
        # Eliminar columnas
        for col in self.tree["columns"]:
            self.tree.heading(col, text="")
        self.tree["columns"] = ()
        # Eliminar filas
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.mensaje.config(text="Sin resultados")

    def mostrar_resultados(self, columnas, filas):
        """Muestra los resultados en la tabla.

        Args:
            columnas: lista de nombres de columnas, ej: ["id", "nombre"]
            filas: lista de tuplas o listas con los valores
        """
        self.limpiar()

        if not columnas:
            return

        self.tree["columns"] = list(columnas)
        for col in columnas:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="w")

        for fila in filas:
            self.tree.insert("", tk.END, values=tuple(fila))

        n = len(filas)
        self.mensaje.config(text=f"{n} fila(s)")

    def mostrar_mensaje(self, texto):
        """Muestra un mensaje en lugar de una tabla.

        Util para INSERT, DELETE, BEGIN, COMMIT, etc.
        """
        self.limpiar()
        self.mensaje.config(text=texto)

    def mostrar_error(self, texto):
        """Muestra un mensaje de error."""
        self.limpiar()
        self.mensaje.config(text=f"Error: {texto}")