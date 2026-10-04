"""Panel de consultas: editor donde el usuario escribe SQL."""

import tkinter as tk
from tkinter import filedialog, ttk

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

        scroll_y = ttk.Scrollbar(frame_editor, orient="vertical",
                                 command=self.editor.yview)
        scroll_y.pack(side="right", fill="y")
        self.editor.configure(yscrollcommand=scroll_y.set)

        self.editor.insert("1.0", SQL_EJEMPLO)

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

        self.editor.bind("<Control-Return>", lambda e: self.ejecutar())

    def set_on_ejecutar(self, callback):
        self.on_ejecutar = callback
        self._actualizar_botones()

    def _actualizar_botones(self):
        if self.on_ejecutar is None:
            self.boton_ejecutar.state(["disabled"])
        else:
            self.boton_ejecutar.state(["!disabled"])

    def get_sql(self) -> str:
        return self.editor.get("1.0", tk.END).strip()

    def set_sql(self, sql: str):
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", sql)

    def cargar_csv(self):
        """Elige un CSV y escribe en el editor el SQL para cargarlo.

        No ejecuta: el usuario revisa el CREATE TABLE sugerido y pulsa Ejecutar.
        """
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

    def ejecutar(self):
        if self.on_ejecutar is None:
            return
        sql = self.get_sql()
        if not sql:
            return
        self.on_ejecutar(sql)