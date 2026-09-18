"""Panel de visualización de resultados tabulares."""

import tkinter as tk
from tkinter import ttk


class PanelResultados(ttk.LabelFrame):
    """Panel con un Treeview para mostrar filas y columnas."""

    def __init__(self, master):
        super().__init__(master, text="Resultados")
        self._construir()

    def _construir(self):
        # Treeview con scroll vertical y horizontal
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.tree = ttk.Treeview(frame, show="headings")
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