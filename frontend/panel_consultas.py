"""Panel de consultas: editor donde el usuario escribe SQL."""

import tkinter as tk
from tkinter import ttk


SQL_EJEMPLO = """-- Escribe tu consulta aqui
SELECT * FROM cuentas;
"""


class PanelConsultas(ttk.LabelFrame):
    """Panel con un editor de texto para escribir SQL."""

    def __init__(self, master, on_ejecutar=None):
        super().__init__(master, text="Consultas")
        self.on_ejecutar = on_ejecutar
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

    def limpiar(self):
        self.editor.delete("1.0", tk.END)

    def ejecutar(self):
        if self.on_ejecutar is None:
            return
        sql = self.get_sql()
        if not sql:
            return
        self.on_ejecutar(sql)