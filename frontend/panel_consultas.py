import tkinter as tk
from tkinter import filedialog
from tkinter import ttk
from frontend.csv_sql import sql_para_csv
from frontend.sql_highlight import syntax_spans
from frontend import tema

SQL_EJEMPLO = """-- Escribe tu consulta aqui
SELECT * FROM cuentas;
"""

class PanelConsultas(ttk.Frame):

    def __init__(self, master, on_ejecutar=None, base_dir=None, on_cambiar_tema=None):
        super().__init__(master)
        self.on_ejecutar = on_ejecutar
        self.base_dir = base_dir
        self.on_cambiar_tema = on_cambiar_tema
        self.obtener_tablas = set
        self.on_error = None
        self.archivo_consulta = None
        self._construir()
        self.bind("<Destroy>", self._al_destruir, add=True)
        self._actualizar_botones()

    def _construir(self):
        frame_editor = ttk.Frame(self)
        frame_editor.pack(fill="both", expand=True, padx=4, pady=4)

        self.margen_lineas = tk.Canvas(frame_editor, width=42, bg=tema.MARGEN,
                                       highlightthickness=0)
        self.margen_lineas.pack(side="left", fill="y")
        self._fuente_codigo = tema.fuentes(self)[1]
        self.editor = tk.Text(frame_editor, height=10, width=50, wrap="word",
                              font=self._fuente_codigo, spacing1=2, spacing3=2)
        self.editor.pack(side="left", fill="both", expand=True)

        self.editor.config(undo=True, maxundo=-1, autoseparators=True)
        self.editor.bind("<Control-z>", self._deshacer)
        self.editor.bind("<Control-y>", self._rehacer)

        scroll_y = ttk.Scrollbar(frame_editor, orient="vertical",
                                 command=self.editor.yview)
        scroll_y.pack(side="right", fill="y")
        def actualizar_scroll(first, last):
            scroll_y.set(first, last)
            self.after_idle(self._dibujar_lineas)
        self.editor.configure(yscrollcommand=actualizar_scroll)
        self.editor.bind("<Configure>", lambda _event: self.after_idle(self._dibujar_lineas), add=True)

        tema.configurar_sintaxis(self.editor)
        self._resaltado_pendiente = None
        self.editor.bind("<KeyRelease>", self._programar_resaltado, add=True)
        self.editor.bind("<<Paste>>", self._pegar)
        self.editor.bind("<<Cut>>", self._programar_resaltado, add=True)

        self.editor.insert("1.0", SQL_EJEMPLO)
        self._resaltar_sql()
        self.editor.edit_reset()

        frame_botones = ttk.Frame(self)
        frame_botones.pack(fill="x", padx=8, pady=(6, 2), before=frame_editor)

        self.boton_limpiar = ttk.Button(frame_botones, text="Limpiar",
                                        command=self.limpiar)
        self.boton_tema = ttk.Button(frame_botones, text="Tema claro", command=self._cambiar_tema)
        self.boton_tema.pack(side="right", padx=(6, 0))
        self.boton_limpiar.pack(side="right", padx=(4, 0))

        self.boton_ejecutar = ttk.Button(frame_botones, text="Ejecutar", style="Accent.TButton",
                                         command=self.ejecutar)
        self.boton_ejecutar.pack(side="left", padx=(0, 6))

        self.boton_csv = ttk.Button(frame_botones, text="Cargar CSV...",
                                    command=self.cargar_csv)
        self.boton_csv.pack(side="left")
        self.ayuda_atajo = ttk.Label(frame_botones, text="Ctrl + Enter", foreground=tema.SECUNDARIO)
        self.ayuda_atajo.pack(side="left", padx=10)

        frame_archivo = ttk.Frame(frame_botones)
        frame_archivo.pack(side="left", padx=(10, 0))

        self.ruta_archivo = tk.StringVar(self, value="")
        self.entry_archivo = ttk.Entry(frame_archivo, width=36, textvariable=self.ruta_archivo, state="readonly")
        self.entry_archivo.pack(side="left", padx=(0, 4))

        self.boton_archivo = ttk.Button(frame_archivo, text="Archivo...",
                                        command=self._seleccionar_archivo_consulta)
        self.boton_archivo.pack(side="left")

        self.editor.bind("<Control-Return>", self._atajo_ejecutar)
        self.editor.bind("<F5>", self._atajo_ejecutar)
        self.editor.bind("<Control-l>", self._seleccionar_linea)
        self.editor.bind("<Alt-Up>", self._mover_linea_arriba)
        self.editor.bind("<Alt-Down>", self._mover_linea_abajo)

    def set_on_ejecutar(self, callback):
        self.on_ejecutar = callback
        self._actualizar_botones()

    def _cambiar_tema(self):
        if self.on_cambiar_tema is not None:
            self.on_cambiar_tema()

    def _actualizar_botones(self):
        if self.on_ejecutar is None:
            self.boton_ejecutar.state(["disabled"])
        else:
            self.boton_ejecutar.state(["!disabled"])

    def get_sql(self) -> str:
        try:
            seleccion = self.editor.get("sel.first", "sel.last").strip()
            if seleccion:
                return seleccion
        except tk.TclError:
            pass
        return self.editor.get("1.0", tk.END).strip()

    def set_sql(self, sql: str):
        self.editor.edit_separator()
        self.editor.config(autoseparators=False)
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", sql)
        self._resaltar_sql()
        self.editor.config(autoseparators=True)
        self.editor.edit_separator()

    def _programar_resaltado(self, _event=None):
        if self._resaltado_pendiente is not None:
            self.after_cancel(self._resaltado_pendiente)
        self._resaltado_pendiente = self.after(35, self._resaltar_sql)

    def _resaltar_sql(self):
        if self._resaltado_pendiente is not None:
            self.after_cancel(self._resaltado_pendiente)
        self._resaltado_pendiente = None
        for tag in ("sql_keyword", "sql_string", "sql_comment", "sql_type", "sql_number"):
            self.editor.tag_remove(tag, "1.0", tk.END)
        text = self.editor.get("1.0", "end-1c")
        for kind, start, end in syntax_spans(text):
            self.editor.tag_add("sql_" + kind, f"1.0+{start}c", f"1.0+{end}c")
        self.editor.tag_raise("sel")
        self.after_idle(self._dibujar_lineas)

    def _al_destruir(self, event):
        if event.widget is self and self._resaltado_pendiente is not None:
            self.after_cancel(self._resaltado_pendiente)
            self._resaltado_pendiente = None

    def _dibujar_lineas(self):
        if not self.editor.winfo_exists():
            return
        self.margen_lineas.delete("all")
        indice = self.editor.index("@0,0")
        while True:
            posicion = self.editor.dlineinfo(indice)
            if posicion is None:
                break
            self.margen_lineas.create_text(34, posicion[1], anchor="ne",
                                           text=indice.split(".")[0], fill=tema.SECUNDARIO,
                                           font=self.editor.cget("font"))
            siguiente = self.editor.index(f"{indice} + 1 line")
            if siguiente == indice:
                break
            indice = siguiente

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

    def _seleccionar_archivo_consulta(self):
        tipos = [
            ("Imagenes", "*.jpg *.jpeg *.png *.bmp *.gif"),
            ("Audio", "*.mp3 *.wav *.ogg *.flac"),
            ("Todos los archivos multimedia", "*.jpg *.jpeg *.png *.bmp *.gif *.mp3 *.wav *.ogg *.flac"),
            ("Todos los archivos", "*.*")
        ]
        ruta = filedialog.askopenfilename(
            title="Seleccionar archivo de consulta",
            initialdir=self.base_dir,
            filetypes=tipos
        )
        if ruta:
            self.archivo_consulta = ruta
            self.ruta_archivo.set(ruta)
            self._insertar_plantilla_similar_to(ruta)

    def _insertar_plantilla_similar_to(self, ruta_archivo):
        extension = ruta_archivo.lower().split('.')[-1]
        if extension in ['jpg', 'jpeg', 'png', 'bmp', 'gif']:
            tabla = "imagenes"
            metrica = "cosine"
        elif extension in ['mp3', 'wav', 'ogg', 'flac']:
            tabla = "canciones"
            metrica = "euclidean"
        else:
            tabla = "datos"
            metrica = "cosine"

        ruta_sql = ruta_archivo.replace("'", "''")
        plantilla = (f"SELECT *, SIMILARITY_SCORE() as score\n"
                     f"FROM {tabla}\n"
                     f"WHERE SIMILAR_TO('{ruta_sql}', k=10)\n"
                     f"  USING HNSW WITH METRIC={metrica}\n"
                     f"ORDER BY score DESC;")
        self.set_sql(plantilla)
        self.editor.focus_set()

    def limpiar_archivo_consulta(self):
        self.archivo_consulta = None
        self.ruta_archivo.set("")

    def limpiar(self):
        self.set_sql("")
        self.limpiar_archivo_consulta()

    def _deshacer(self, event):
        try:
            self.editor.edit_undo()
        except tk.TclError:
            pass
        self._programar_resaltado()
        return "break"

    def _rehacer(self, event):
        try:
            self.editor.edit_redo()
        except tk.TclError:
            pass
        self._programar_resaltado()
        return "break"

    def _pegar(self, _event=None):
        """Reemplaza la selección o inserta en el cursor como una sola edición."""
        try:
            texto = self.editor.clipboard_get()
        except tk.TclError:
            return "break"  # No borrar la selección si el portapapeles no contiene texto.
        self.editor.edit_separator()
        automatico = self.editor.cget("autoseparators")
        self.editor.configure(autoseparators=False)
        try:
            if self.editor.tag_ranges("sel"):
                inicio = self.editor.index("sel.first")
                self.editor.delete("sel.first", "sel.last")
                self.editor.mark_set("insert", inicio)
            self.editor.insert("insert", texto)
            self.editor.see("insert")
        finally:
            self.editor.configure(autoseparators=automatico)
            self.editor.edit_separator()
        self._programar_resaltado()
        return "break"  # Evita que Tk pegue el mismo contenido por segunda vez.

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
