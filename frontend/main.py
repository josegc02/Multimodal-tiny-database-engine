"""Ventana principal del frontend con los 4 paneles requeridos."""

import tkinter as tk
from tkinter import ttk

from frontend.motor import Motor
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

        style = ttk.Style(self)
        style.theme_use("clam")

        # Crear el motor
        self.motor = Motor()

        # Layout: 2x2
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Crear los 4 paneles
        self.panel_archivos = PanelArchivos(self)
        self.panel_consultas = PanelConsultas(self, on_ejecutar=self._on_ejecutar)
        self.panel_resultados = PanelResultados(self)
        self.panel_plan = PanelPlanEjecucion(self)

        # Colocarlos
        self.panel_archivos.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.panel_consultas.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)
        self.panel_resultados.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        self.panel_plan.grid(row=1, column=1, sticky="nsew", padx=2, pady=2)

        # Conectar paneles con el motor
        self.panel_archivos.set_catalog(self.motor.catalog)

        # Registrar cierre limpio
        self.protocol("WM_DELETE_WINDOW", self._on_cerrar)

    def _on_cerrar(self):
        """Cierra los storages antes de salir."""
        try:
            self.motor.cerrar()
        finally:
            self.destroy()

    def _on_ejecutar(self, sql):
        """Callback cuando el usuario presiona Ejecutar."""
        resultado = self.motor.ejecutar(sql)

        if resultado.tiene_error:
            self.panel_resultados.mostrar_error(resultado.error)
            self.panel_plan.limpiar()
            return

        if resultado.tiene_tabla:
            self.panel_resultados.mostrar_resultados(resultado.columnas, resultado.filas)
        elif resultado.mensaje:
            self.panel_resultados.mostrar_mensaje(resultado.mensaje)
        else:
            self.panel_resultados.mostrar_mensaje("Sin resultados")

        if resultado.plan is not None:
            self.panel_plan.mostrar_plan_objeto(resultado.plan)
        else:
            self.panel_plan.limpiar()


def main():
    app = Aplicacion()
    app.mainloop()


if __name__ == "__main__":
    main()