"""Panel de editor de consultas SQL."""

import tkinter as tk
from tkinter import ttk


class PanelConsultas(ttk.LabelFrame):
    """Panel con un editor de texto para escribir SQL."""

    def __init__(self, master):
        super().__init__(master, text="Consultas")
        self._construir()

    def _construir(self):
        # Editor de texto
        self.editor = tk.Text(self, height=10, width=50, wrap="word")
        self.editor.pack(fill="both", expand=True, padx=4, pady=4)

        # Barra de botones
        frame_botones = ttk.Frame(self)
        frame_botones.pack(fill="x", padx=4, pady=(0, 4))

        self.boton_ejecutar = ttk.Button(frame_botones, text="Ejecutar")
        self.boton_ejecutar.pack(side="right")

        self.boton_limpiar = ttk.Button(frame_botones, text="Limpiar")
        self.boton_limpiar.pack(side="right", padx=(0, 4))