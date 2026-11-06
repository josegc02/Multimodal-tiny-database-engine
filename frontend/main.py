"""Ventana principal del frontend con los 4 paneles requeridos."""

import tkinter as tk
from tkinter import ttk

from frontend.motor import PROJECT_DIR, Motor
from frontend.panel_archivos import PanelArchivos
from frontend.panel_consultas import PanelConsultas
from frontend.panel_resultados import PanelResultados
from frontend.panel_plan_ejecucion import PanelPlanEjecucion
from frontend.panel_mapa import PanelMapa
from frontend import tema
from engine.query import ast
from engine.query.logical_plan import expression_children
from engine.query.parser import parse_script
from engine.query.sql_executor import _generar_fragmento


class Aplicacion(tk.Tk):
    """Ventana principal del minigestor."""

    def __init__(self):
        super().__init__()
        self.tema_actual = "oscuro"
        tema.seleccionar_tema(self.tema_actual)
        self.style, self.fuente_ui, self.fuente_codigo = tema.inicializar_estilos(self)

        self.title("MiniGestor de Base de Datos Multimodal")
        self.geometry(f"{self.winfo_screenwidth() * 9 // 10}x{self.winfo_screenheight() * 85 // 100}")
        self.minsize(900, 600)

        self.motor = Motor()

        # --- CREACIÓN DEL LAYOUT TIPO PGADMIN ---

        # 1. Contenedor principal horizontal (Usamos ttk_classic porque ttkbootstrap tiene un bug aquí)
        self.main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # 2. Panel Izquierdo (Barra lateral)
        self.sidebar_frame = ttk.Frame(self.main_paned, width=280, style="Sidebar.TFrame")
        self.main_paned.add(self.sidebar_frame, weight=1)

        self.workspace_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.workspace_frame, weight=4)

        # 4. Contenedor vertical para el área de trabajo (Usamos ttk_classic aquí también)
        self.workspace_paned = ttk.PanedWindow(self.workspace_frame, orient=tk.VERTICAL)
        self.workspace_paned.pack(fill=tk.BOTH, expand=True)

        self.top_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.top_notebook, weight=3)

        self.bottom_notebook = ttk.Notebook(self.workspace_paned)
        self.workspace_paned.add(self.bottom_notebook, weight=2)

        self.panel_archivos = PanelArchivos(self.sidebar_frame)
        self.panel_consultas = PanelConsultas(self, on_ejecutar=self._on_ejecutar, base_dir=PROJECT_DIR,
                                              on_cambiar_tema=self._cambiar_tema)
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
        self.after(150, lambda: self.main_paned.sashpos(0, min(300, self.winfo_width() // 4)))

        self.panel_archivos.set_catalog(self.motor.catalog)
        self.panel_consultas.obtener_tablas = lambda: set(self.motor.catalog.tables)
        self.panel_consultas.on_error = self._mostrar_error

        self.protocol("WM_DELETE_WINDOW", self._on_cerrar)

    def _aplicar_tema(self):
        """Colores del tema en lo que ttkbootstrap no estiliza: widgets tk y fondo de Treeview."""
        self.configure(background=tema.FONDO)
        self.panel_archivos.lista.configure(bg=tema.LATERAL, fg=tema.LATERAL_TEXTO,
                                           font=self.fuente_ui,
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
        for titulo in (self.panel_archivos.titulo, self.panel_archivos.titulo_esquema):
            titulo.configure(bg=tema.LATERAL, fg=tema.LATERAL_SECUNDARIO)
        self.panel_consultas.margen_lineas.configure(bg=tema.MARGEN)
        self.panel_consultas.ayuda_atajo.configure(foreground=tema.SECUNDARIO)
        tema.configurar_sintaxis(self.panel_consultas.editor)
        self.panel_consultas._dibujar_lineas()
        self.panel_resultados.tree.tag_configure("alterna", background=tema.FILA_ALTERNA)
        self.panel_resultados._programar_reajuste()
        self.panel_resultados.vacio.configure(bg=tema.SUPERFICIE, fg=tema.SECUNDARIO)
        if self.panel_resultados.canvas_galeria is not None:
            self.panel_resultados.canvas_galeria.configure(background=tema.FONDO)
        self.panel_mapa.btn_centrar.configure(bg=tema.SUPERFICIE, fg=tema.ACENTO,
                                              activebackground=tema.SELECCION, activeforeground=tema.ACENTO)
        self.panel_consultas.boton_tema.configure(text="Tema oscuro" if self.tema_actual == "claro" else "Tema claro")

    def _cambiar_tema(self):
        self.tema_actual = "claro" if self.tema_actual == "oscuro" else "oscuro"
        tema.seleccionar_tema(self.tema_actual)
        self.style, self.fuente_ui, self.fuente_codigo = tema.inicializar_estilos(self)
        self._aplicar_tema()

    def _on_cerrar(self):
        try:
            self.panel_mapa.close()
            self.motor.cerrar()
        finally:
            self.destroy()

    def _on_ejecutar(self, sql, archivo_consulta=None):
        """Callback cuando el usuario presiona Ejecutar."""
        self.panel_resultados.mensaje.configure(text="Ejecutando consulta…", style="TLabel")
        self.update_idletasks()
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
            columnas, filas = self._preparar_resultados_texto(sql, resultado)
            self.panel_resultados.mostrar_resultados(columnas, filas)
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
                if any(val.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.mp3', '.wav', '.ogg', '.flac')):
                    path_col_idx = i

        if path_col_idx is not None:
            primera_ruta = str(resultado.filas[0][path_col_idx]).lower()
            es_imagen = any(primera_ruta.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif'))
            tipo = 'imagen' if es_imagen else 'audio'

            items = [(fila[path_col_idx], fila[score_col_idx] if score_col_idx is not None else None)
                     for fila in resultado.filas]
            self.panel_resultados.mostrar_galeria(tipo, items)
            self.bottom_notebook.select(self.panel_resultados)
        else:
            # Si no detecta las columnas, muestra la tabla normal
            self.panel_resultados.mostrar_resultados(resultado.columnas, resultado.filas)
            self.bottom_notebook.select(self.panel_resultados)

    @staticmethod
    def _preparar_resultados_texto(sql, resultado):
        """Añade un fragmento visual si se proyectó la columna buscada, sin cambiar SQL."""
        sentencia = parse_script(sql)[-1]
        if not isinstance(sentencia, ast.SelectStatement) or sentencia.where is None:
            return resultado.columnas, resultado.filas
        pendientes = [sentencia.where]
        while pendientes:
            nodo = pendientes.pop()
            if isinstance(nodo, ast.MatchCall):
                try:
                    indice = resultado.columnas.index(nodo.column.name)
                except ValueError:
                    return resultado.columnas, resultado.filas
                if "fragmento" in resultado.columnas:
                    return resultado.columnas, resultado.filas
                filas = [tuple(fila) + (_generar_fragmento({nodo.column.name: fila[indice]}, nodo.query),)
                         for fila in resultado.filas]
                return [*resultado.columnas, "fragmento"], filas
            pendientes.extend(expression_children(nodo))
        return resultado.columnas, resultado.filas

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
