"""Panel de consultas: editor donde el usuario escribe SQL."""

import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from frontend.csv_sql import sql_para_csv

SQL_EJEMPLO = """-- Escribe tu consulta aqui
SELECT * FROM cuentas;
"""

class PanelConsultas(ttk.LabelFrame):
    """Panel con un editor de texto para escribir SQL."""

    def __init__(self, master, on_ejecutar=None, base_dir=None):
        super().__init__(master, text="Consultas")
        self.on_ejecutar = on_ejecutar
        self.base_dir = base_dir
        self.obtener_tablas = set
        self.on_error = None
        self._construir()
        self._actualizar_botones()

    def _construir(self):
        frame_editor = ttk.Frame(self)
        frame_editor.pack(fill="both", expand=True, padx=4, pady=4)

        self.editor = tk.Text(frame_editor, height=10, width=50, wrap="word",
                              font=("Consolas", 10))
        self.editor.pack(side="left", fill="both", expand=True)

        # --- CONFIGURACIÓN DE DESHACER/REHACER ---
        self.editor.config(undo=True, maxundo=-1, autoseparators=True)
        self.editor.bind("<Control-z>", self._deshacer)
        self.editor.bind("<Control-y>", self._rehacer)

        scroll_y = ttk.Scrollbar(frame_editor, orient="vertical",
                                 command=self.editor.yview)
        scroll_y.pack(side="right", fill="y")
        self.editor.configure(yscrollcommand=scroll_y.set)

        self.editor.insert("1.0", SQL_EJEMPLO)
        self.editor.edit_reset()

        frame_botones = ttk.Frame(self)
        frame_botones.pack(fill="x", padx=4, pady=(0, 4))

        self.boton_limpiar = ttk.Button(frame_botones, text="Limpiar",
                                        command=self.limpiar)
        self.boton_limpiar.pack(side="right", padx=(4, 0))

        self.boton_ejecutar = ttk.Button(frame_botones, text="Ejecutar",
                                         command=self.ejecutar)
        self.boton_ejecutar.pack(side="right")

        self.boton_csv = ttk.Button(frame_botones, text="Cargar CSV...",
                                    command=self.cargar_csv)
        self.boton_csv.pack(side="left")

        # --- ATAJOS DE TECLADO ---
        self.editor.bind("<Control-Return>", self._atajo_ejecutar)
        self.editor.bind("<F5>", self._atajo_ejecutar)
        self.editor.bind("<Control-l>", self._seleccionar_linea)
        self.editor.bind("<Alt-Up>", self._mover_linea_arriba)
        self.editor.bind("<Alt-Down>", self._mover_linea_abajo)

    def set_on_ejecutar(self, callback):
        self.on_ejecutar = callback
        self._actualizar_botones()

    def _actualizar_botones(self):
        if self.on_ejecutar is None:
            self.boton_ejecutar.state(["disabled"])
        else:
            self.boton_ejecutar.state(["!disabled"])

    def get_sql(self) -> str:
        """Obtiene el SQL. Si hay texto seleccionado, devuelve solo esa selección."""
        try:
            seleccion = self.editor.get("sel.first", "sel.last").strip()
            if seleccion:
                return seleccion
        except tk.TclError:
            pass
        return self.editor.get("1.0", tk.END).strip()

    def set_sql(self, sql: str):
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", sql)
        self.editor.edit_reset()

    def cargar_csv(self):
        path = filedialog.askopenfilename(
            title="Cargar CSV", initialdir=self.base_dir,
            filetypes=[("Archivos CSV", "*.csv *.txt"), ("Todos los archivos", "*.*")])
        if not path:
            return
        try:
            sql = sql_para_csv(path, self.obtener_tablas(), self.base_dir)
        except (OSError, ValueError) as error:
            if self.on_error:
                self.on_error(f"No se pudo leer el CSV: {error}")
            return
        self.set_sql(sql)
        self.editor.focus_set()

    def limpiar(self):
        self.editor.delete("1.0", tk.END)
        self.editor.edit_reset()

    def _deshacer(self, event):
        try:
            self.editor.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def _rehacer(self, event):
        try:
            self.editor.edit_redo()
        except tk.TclError:
            pass
        return "break"

    def _atajo_ejecutar(self, event):
        self.ejecutar()
        return "break"

    def _seleccionar_linea(self, event):
        self.editor.tag_remove("sel", "1.0", tk.END)
        indice_cursor = self.editor.index("insert")
        inicio_linea = self.editor.index(f"{indice_cursor} linestart")
        fin_linea = self.editor.index(f"{indice_cursor} lineend")
        self.editor.tag_add("sel", inicio_linea, fin_linea)
        self.editor.mark_set("insert", fin_linea)
        return "break"

    def _mover_linea_arriba(self, event):
        indice = self.editor.index("insert")
        num_linea = int(indice.split(".")[0])

        if num_linea <= 1:
            return "break"

        texto_actual = self.editor.get(f"{num_linea}.0", f"{num_linea}.end")
        texto_arriba = self.editor.get(f"{num_linea-1}.0", f"{num_linea-1}.end")

        self.editor.replace(f"{num_linea-1}.0", f"{num_linea-1}.end", texto_actual)
        self.editor.replace(f"{num_linea}.0", f"{num_linea}.end", texto_arriba)

        columna = len(texto_actual)
        self.editor.mark_set("insert", f"{num_linea-1}.{columna}")
        return "break"

    def _mover_linea_abajo(self, event):
        indice = self.editor.index("insert")
        num_linea = int(indice.split(".")[0])

        total_lineas = int(self.editor.index("end-1c").split(".")[0])
        if num_linea >= total_lineas:
            return "break"

        texto_actual = self.editor.get(f"{num_linea}.0", f"{num_linea}.end")
        texto_abajo = self.editor.get(f"{num_linea+1}.0", f"{num_linea+1}.end")

        self.editor.replace(f"{num_linea+1}.0", f"{num_linea+1}.end", texto_actual)
        self.editor.replace(f"{num_linea}.0", f"{num_linea}.end", texto_abajo)

        columna = len(texto_actual)
        self.editor.mark_set("insert", f"{num_linea+1}.{columna}")
        return "break"

    def ejecutar(self):
        if self.on_ejecutar is None:
            return
        sql = self.get_sql()
        if not sql:
            return
        self.on_ejecutar(sql)