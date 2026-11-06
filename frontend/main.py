"""Ventana principal del frontend con los 4 paneles requeridos."""

import tkinter as tk
from tkinter import font as tkfont
import ttkbootstrap as ttk
from tkinter import ttk as ttk_classic # Importamos el ttk clásico para solucionar el error del PanedWindow

from frontend.motor import PROJECT_DIR, Motor
from frontend.panel_archivos import PanelArchivos
from frontend.panel_consultas import PanelConsultas
from frontend.panel_resultados import PanelResultados
from frontend.panel_plan_ejecucion import PanelPlanEjecucion
from frontend.panel_mapa import PanelMapa
from frontend import tema


class Aplicacion(ttk.Window):
    """Ventana principal del minigestor."""

    def __init__(self):
        # Aquí defines el tema (puedes probar "darkly", "cosmo", "flatly", "cyborg", etc.)
        super().__init__(themename="pydata-light")

        self.title("MiniGestor de Base de Datos Multimodal")
        # Relativo a la pantalla: en píxeles fijos queda pequeña si el sistema escala la letra.
        self.geometry(f"{self.winfo_screenwidth() * 9 // 10}x{self.winfo_screenheight() * 85 // 100}")
        self.minsize(900, 600)

        # Crear el motor
        self.motor = Motor()

        # --- CREACIÓN DEL LAYOUT TIPO PGADMIN ---

        # 1. Contenedor principal horizontal (Usamos ttk_classic porque ttkbootstrap tiene un bug aquí)
        self.main_paned = ttk_classic.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # 2. Panel Izquierdo (Barra lateral)
        self.sidebar_frame = ttk.Frame(self.main_paned, width=280, style="Sidebar.TFrame")
        self.main_paned.add(self.sidebar_frame, weight=1)

        # 3. Panel Derecho (Área de trabajo)
        self.workspace_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.workspace_frame, weight=4)

        # 4. Contenedor vertical para el área de trabajo (Usamos ttk_classic aquí también)
        self.workspace_paned = ttk_classic.PanedWindow(self.workspace_frame, orient=tk.VERTICAL)
        self.workspace_paned.pack(fill=tk.BOTH, expand=True)

        # 5. Zona Superior del área de trabajo (Pestañas modernas)
        self.top_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.top_notebook, weight=3)

        # 6. Zona Inferior del área de trabajo (Pestañas modernas)
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

        self._aplicar_tema()
        self.after(150, lambda: self.main_paned.sashpos(0, min(300, self.winfo_width() // 4)))

        # --- CONEXIÓN CON EL MOTOR ---
        self.panel_archivos.set_catalog(self.motor.catalog)
        self.panel_consultas.obtener_tablas = lambda: set(self.motor.catalog.tables)
        self.panel_consultas.on_error = self._mostrar_error

        # Registrar cierre limpio
        self.protocol("WM_DELETE_WINDOW", self._on_cerrar)

    def _aplicar_tema(self):
        """Colores del tema en lo que ttkbootstrap no estiliza: widgets tk y fondo de Treeview."""
        alto_fila = tkfont.nametofont("TkDefaultFont").metrics("linespace") + 4
        self.configure(background=tema.FONDO)
        self.style.configure("TFrame", background=tema.FONDO)
        self.style.configure("Sidebar.TFrame", background=tema.LATERAL)
        self.style.configure("Sidebar.TLabelframe", background=tema.LATERAL, borderwidth=0)
        self.style.configure("Sidebar.TLabelframe.Label", background=tema.LATERAL,
                             foreground=tema.LATERAL_SECUNDARIO, padding=(10, 8))
        self.style.configure("Sidebar.TLabel", background=tema.LATERAL, foreground=tema.LATERAL_SECUNDARIO)
        self.style.configure("TLabel", background=tema.FONDO, foreground=tema.TEXTO)
        self.style.configure("TNotebook", background=tema.FONDO, borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(16, 8), background=tema.FONDO,
                             foreground=tema.SECUNDARIO, borderwidth=0)
        self.style.map("TNotebook.Tab", background=[("selected", tema.SUPERFICIE)],
                       foreground=[("selected", tema.ACENTO)])
        self.style.configure("primary.TButton", background=tema.ACENTO, foreground="#ffffff", padding=(12, 6))
        self.style.configure("Treeview", background=tema.SUPERFICIE,
                             fieldbackground=tema.SUPERFICIE, foreground=tema.TEXTO, rowheight=alto_fila)
        self.style.map("Treeview", background=[("selected", tema.SELECCION)],
                       foreground=[("selected", tema.TEXTO)])
        self.style.configure("Treeview.Heading", background=tema.ENCABEZADO,
                             foreground=tema.TEXTO, padding=(6, 5))
        self.panel_archivos.lista.configure(bg=tema.LATERAL, fg=tema.LATERAL_TEXTO,
                                           selectbackground=tema.LATERAL_SELECCION,
                                           selectforeground=tema.LATERAL_TEXTO,
                                           relief="flat", highlightthickness=0, borderwidth=0)
        self.panel_archivos.texto_esquema.configure(bg=tema.LATERAL, fg=tema.LATERAL_TEXTO,
                                                    selectbackground=tema.LATERAL_SELECCION,
                                                    selectforeground=tema.LATERAL_TEXTO,
                                                    relief="flat", borderwidth=0, highlightthickness=0, padx=8)
        self.panel_consultas.editor.configure(bg=tema.SUPERFICIE, fg=tema.TEXTO,
                                              insertbackground=tema.TEXTO, selectbackground=tema.SELECCION,
                                              selectforeground=tema.TEXTO, relief="flat", borderwidth=0,
                                              highlightthickness=0, padx=10, pady=8)

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
            self._mostrar_error(resultado.error)
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
            self.bottom_notebook.select(self.panel_plan)
        else:
            self.panel_plan.limpiar()
            self.bottom_notebook.select(self.panel_resultados)

        self.panel_archivos.refresh()
        # Le quitamos el '#' para que se actualice el mapa
        self.panel_mapa.actualizar(resultado.mapa)

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
