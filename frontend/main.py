"""Ventana principal del frontend con los 4 paneles requeridos."""

import tkinter as tk
from tkinter import font as tkfont
import ttkbootstrap as ttk
from tkinter import ttk as ttk_classic

from frontend.motor import PROJECT_DIR, Motor
from frontend.panel_archivos import PanelArchivos
from frontend.panel_consultas import PanelConsultas
from frontend.panel_resultados import PanelResultados
from frontend.panel_plan_ejecucion import PanelPlanEjecucion
from frontend.panel_mapa import PanelMapa


class Aplicacion(ttk.Window):
    """Ventana principal del minigestor."""

    def __init__(self):
        super().__init__(themename="pydata-light")

        self.title("MiniGestor de Base de Datos Multimodal")
        self.geometry(f"{self.winfo_screenwidth() * 9 // 10}x{self.winfo_screenheight() * 85 // 100}")
        self.minsize(900, 600)

        self.motor = Motor()

        self.main_paned = ttk_classic.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        self.sidebar_frame = ttk.Frame(self.main_paned, width=250)
        self.main_paned.add(self.sidebar_frame, weight=1)

        self.workspace_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.workspace_frame, weight=4)

        self.workspace_paned = ttk_classic.PanedWindow(self.workspace_frame, orient=tk.VERTICAL)
        self.workspace_paned.pack(fill=tk.BOTH, expand=True)

        self.top_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.top_notebook, weight=3)

        self.bottom_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.bottom_notebook, weight=2)

        self.panel_archivos = PanelArchivos(self.sidebar_frame)
        self.panel_consultas = PanelConsultas(self, on_ejecutar=self._on_ejecutar, base_dir=PROJECT_DIR)
        self.panel_resultados = PanelResultados(self)
        self.panel_plan = PanelPlanEjecucion(self)

        self.panel_mapa = PanelMapa(self)
        self.panel_mapa.on_click = self._mapa_click

        self.panel_archivos.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.top_notebook.add(self.panel_consultas, text="Consulta SQL")
        self.top_notebook.add(self.panel_mapa, text="Mapa")

        self.bottom_notebook.add(self.panel_resultados, text="Resultados")
        self.bottom_notebook.add(self.panel_plan, text="Plan de Ejecución")

        self._aplicar_tema()

        self.panel_archivos.set_catalog(self.motor.catalog)
        self.panel_consultas.obtener_tablas = lambda: set(self.motor.catalog.tables)
        self.panel_consultas.on_error = self._mostrar_error

        self.protocol("WM_DELETE_WINDOW", self._on_cerrar)

    def _aplicar_tema(self):
        colores = self.style.colors
        alto_fila = tkfont.nametofont("TkDefaultFont").metrics("linespace") + 4
        self.style.configure("Treeview", fieldbackground=colores.bg, rowheight=alto_fila)

        tema = dict(bg=colores.inputbg, fg=colores.fg, selectbackground=colores.selectbg,
                    selectforeground=colores.selectfg)
        self.panel_archivos.lista.configure(**tema)
        for texto in (self.panel_archivos.texto_esquema, self.panel_consultas.editor):
            texto.configure(insertbackground=colores.fg, **tema)

    def _on_cerrar(self):
        try:
            self.panel_mapa.close()
            self.motor.cerrar()
        finally:
            self.destroy()

    def _on_ejecutar(self, sql, archivo_consulta=None):
        """Callback cuando el usuario presiona Ejecutar."""
        resultado = self.motor.ejecutar(sql)

        if resultado.tiene_error:
            self._mostrar_error(resultado.error)
            self.panel_plan.limpiar()
            return

        # 1. Manejo de EXPLAIN / EXPLAIN ANALYZE (Checkbox 4)
        if resultado.plan_nodos:
            self.panel_plan.mostrar_plan(
                resultado.plan_nodos, 
                analyze=resultado.tiempos[1] is not None,
                tiempos=resultado.tiempos
            )
            # Si es EXPLAIN, también mostramos el texto en Resultados (comportamiento estándar)
            if resultado.tiene_tabla:
                self.panel_resultados.mostrar_resultados(resultado.columnas, resultado.filas)
            self.bottom_notebook.select(self.panel_plan)
        
        # 2. Manejo de SIMILAR_TO con galería multimedia (Checkbox 2)
        elif 'SIMILAR_TO' in sql.upper() and resultado.tiene_tabla:
            self._mostrar_galeria_multimedia(resultado)
            self.panel_plan.limpiar()
            
        # 3. Manejo estándar de resultados
        elif resultado.tiene_tabla:
            self.panel_resultados.mostrar_resultados(resultado.columnas, resultado.filas)
            self.panel_plan.limpiar()
            self.bottom_notebook.select(self.panel_resultados)
            
        elif resultado.mensaje:
            self.panel_resultados.mostrar_mensaje(resultado.mensaje)
            self.panel_plan.limpiar()
            self.bottom_notebook.select(self.panel_resultados)
            
        else:
            self.panel_resultados.mostrar_mensaje("Sin resultados")
            self.panel_plan.limpiar()
            self.bottom_notebook.select(self.panel_resultados)

        self.panel_archivos.refresh()
        self.panel_mapa.actualizar(resultado.mapa)

    def _mostrar_galeria_multimedia(self, resultado):
        """Detecta columnas de ruta y score para mostrar la galería."""
        path_col_idx = None
        score_col_idx = None
        
        for i, col in enumerate(resultado.columnas):
            col_lower = col.lower()
            if 'score' in col_lower or 'similarity' in col_lower or 'relevancia' in col_lower:
                score_col_idx = i
            elif path_col_idx is None and resultado.filas:
                val = str(resultado.filas[0][i]).lower()
                if any(val.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.bmp', '.mp3', '.wav', '.ogg', '.flac')):
                    path_col_idx = i

        if path_col_idx is not None and score_col_idx is not None:
            primera_ruta = str(resultado.filas[0][path_col_idx]).lower()
            es_imagen = any(primera_ruta.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif'))
            tipo = 'imagen' if es_imagen else 'audio'
            
            items = [(fila[path_col_idx], float(fila[score_col_idx])) for fila in resultado.filas]
            self.panel_resultados.mostrar_galeria(tipo, items)
            self.bottom_notebook.select(self.panel_resultados)
        else:
            # Si no detecta las columnas, muestra la tabla normal
            self.panel_resultados.mostrar_resultados(resultado.columnas, resultado.filas)

    def _mostrar_error(self, error):
        self.panel_resultados.mostrar_error(error)
        self.bottom_notebook.select(self.panel_resultados)

    def _mapa_click(self, lat, lon):
        self.top_notebook.select(self.panel_consultas)
        self.panel_consultas.editor.insert("insert", f"POINT({lat:.6f}, {lon:.6f})")
        self.panel_consultas.editor.focus_set()


def main():
    app = Aplicacion()
    app.mainloop()


if __name__ == "__main__":
    main()