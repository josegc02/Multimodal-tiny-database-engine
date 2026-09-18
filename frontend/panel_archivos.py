"""Panel de visualización de tablas cargadas y sus esquemas."""

import tkinter as tk
from tkinter import ttk


class PanelArchivos(ttk.LabelFrame):
    """Panel que lista las tablas y sus esquemas."""

    def __init__(self, master):
        super().__init__(master, text="Archivos")
        self._construir()

    def _construir(self):
        # Lista de tablas (izquierda)
        self.lista = tk.Listbox(self, exportselection=False)
        self.lista.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        # Esquema de la tabla seleccionada (derecha)
        frame_derecha = ttk.Frame(self)
        frame_derecha.pack(side="right", fill="both", expand=True, padx=4, pady=4)

        ttk.Label(frame_derecha, text="Esquema:").pack(anchor="w")

        self.texto_esquema = tk.Text(frame_derecha, height=10, width=30, state="disabled")
        self.texto_esquema.pack(fill="both", expand=True)