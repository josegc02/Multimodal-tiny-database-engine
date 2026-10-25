"""Ventana principal del frontend con los 4 paneles requeridos."""

import tkinter as tk
from tkinter import ttk

from frontend.motor import PROJECT_DIR, Motor
from frontend.panel_archivos import PanelArchivos
from frontend.panel_consultas import PanelConsultas
from frontend.panel_resultados import PanelResultados
from frontend.panel_plan_ejecucion import PanelPlanEjecucion
from frontend.panel_mapa import PanelMapa


class Aplicacion(tk.Tk):
    """Ventana principal del minigestor."""

    def __init__(self):
        super().__init__()
        self.title("MiniGestor de Base de Datos Multimodal")
        self.geometry("1200x900")
        self.minsize(900, 600)

        style = ttk.Style(self)
        style.theme_use("clam")

        # Crear el motor
        self.motor = Motor()

        # --- CREACIÓN DEL LAYOUT TIPO PGADMIN ---

        # 1. Contenedor principal horizontal (Izquierda vs Derecha)
        self.main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # 2. Panel Izquierdo (Barra lateral)
        self.sidebar_frame = ttk.Frame(self.main_paned, width=250)
        self.main_paned.add(self.sidebar_frame, weight=1)

        # 3. Panel Derecho (Área de trabajo)
        self.workspace_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.workspace_frame, weight=4)

        # 4. Contenedor vertical para el área de trabajo (Arriba vs Abajo)
        self.workspace_paned = ttk.PanedWindow(self.workspace_frame, orient=tk.VERTICAL)
        self.workspace_paned.pack(fill=tk.BOTH, expand=True)

        # 5. Zona Superior del área de trabajo (Pestañas)
        self.top_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.top_notebook, weight=3)

        # 6. Zona Inferior del área de trabajo (Pestañas)
        self.bottom_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.bottom_notebook, weight=2)

        # --- INSTANCIACIÓN DE LOS PANELES ---
        self.panel_archivos = PanelArchivos(self.sidebar_frame)
        self.panel_consultas = PanelConsultas(self, on_ejecutar=self._on_ejecutar, base_dir=PROJECT_DIR)
        self.panel_resultados = PanelResultados(self)
        self.panel_plan = PanelPlanEjecucion(self)

        # El mapa ahora es nativo
        self.panel_mapa = PanelMapa(self)
        self.panel_mapa.on_click = self._mapa_click

        # --- COLOCACIÓN VISUAL DE LOS PANELES ---

        # Sidebar
        self.panel_archivos.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Pestañas Superiores (Consulta SQL y Mapa)
        self.top_notebook.add(self.panel_consultas, text="Consulta SQL")
        self.top_notebook.add(self.panel_mapa, text="Mapa")

        # Pestañas Inferiores (Resultados y Plan)
        self.bottom_notebook.add(self.panel_resultados, text="Resultados")
        self.bottom_notebook.add(self.panel_plan, text="Plan de Ejecución")

        # --- CONEXIÓN CON EL MOTOR ---
        self.panel_archivos.set_catalog(self.motor.catalog)
        self.panel_consultas.obtener_tablas = lambda: set(self.motor.catalog.tables)
        self.panel_consultas.on_error = self.panel_resultados.mostrar_error

        # Registrar cierre limpio
        self.protocol("WM_DELETE_WINDOW", self._on_cerrar)

    def _on_cerrar(self):
        """Cierra los storages antes de salir."""
        try:
            self.panel_mapa.close()
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

        # El plan solo aparece cuando se ejecuta EXPLAIN / EXPLAIN ANALYZE:
        if resultado.plan_nodos:
            self.panel_plan.mostrar_plan(resultado.plan_nodos, analyze=resultado.tiempos[1] is not None,
                                         tiempos=resultado.tiempos)
        else:
            self.panel_plan.limpiar()

        self.panel_archivos.refresh()
        # Le quitamos el '#' para que se actualice el mapa
        self.panel_mapa.actualizar(resultado.mapa)

    def _mapa_click(self, lat, lon):
        self.panel_consultas.editor.insert("insert", f"POINT({lat:.6f}, {lon:.6f})")
        self.panel_consultas.editor.focus_set()


def main():
    app = Aplicacion()
    app.mainloop()


if __name__ == "__main__":
    main()