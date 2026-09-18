"""Panel de visualización del plan de ejecución físico y operadores."""

import tkinter as tk
from tkinter import ttk


class PanelPlanEjecucion(ttk.LabelFrame):
    """Panel que muestra el plan de ejecucion (indices usados, orden, etc.)."""

    def __init__(self, master):
        super().__init__(master, text="Plan de ejecucion")
        self._construir()

    def _construir(self):
        # Area de texto donde se mostrara el plan
        self.texto = tk.Text(self, height=10, width=50, state="disabled", wrap="word")
        self.texto.pack(fill="both", expand=True, padx=4, pady=4)