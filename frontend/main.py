"""Punto de entrada principal para la interfaz gráfica."""

"""Ventana principal del frontend con los 4 paneles requeridos.

Layout:
    ┌────────────────────┬────────────────────┐
    │  Panel de Archivos │ Panel de Consultas │
    ├────────────────────┼────────────────────┤
    │ Panel de Resultados│ Panel de Plan      │
    └────────────────────┴────────────────────┘
"""

import tkinter as tk
from tkinter import ttk

from frontend.panel_archivos import PanelArchivos
from frontend.panel_consultas import PanelConsultas
from frontend.panel_resultados import PanelResultados
from frontend.panel_plan_ejecucion import PanelPlanEjecucion


class Aplicacion(tk.Tk):
    """Ventana principal del minigestor."""

    def __init__(self):
        super().__init__()
        self.title("MiniGestor de Base de Datos Multimodal")
        self.geometry("1200x800")
        self.minsize(900, 600)

        # Estilo
        style = ttk.Style(self)
        style.theme_use("clam")

        # Layout: 2x2 con pesos iguales
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Crear los 4 paneles
        self.panel_archivos = PanelArchivos(self)
        self.panel_consultas = PanelConsultas(self)
        self.panel_resultados = PanelResultados(self)
        self.panel_plan = PanelPlanEjecucion(self)

        # Colocarlos en la cuadricula
        self.panel_archivos.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.panel_consultas.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)
        self.panel_resultados.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        self.panel_plan.grid(row=1, column=1, sticky="nsew", padx=2, pady=2)


def main():
    app = Aplicacion()
    app.mainloop()


if __name__ == "__main__":
    main()