import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from frontend import tema
import os
import sys
import subprocess

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def es_numerica(valores):
    presentes = [v for v in valores if v is not None]
    return bool(presentes) and all(type(v) in (int, float) for v in presentes)


def abreviar(texto, ancho, medir):
    """Devuelve texto con elipsis si no cabe, sin modificar el valor original."""
    texto = str(texto)
    if medir(texto) <= ancho:
        return texto
    puntos = "…"
    if medir(puntos) > ancho:
        return ""
    inicio, fin = 0, len(texto)
    while inicio < fin:
        mitad = (inicio + fin + 1) // 2
        if medir(texto[:mitad] + puntos) <= ancho:
            inicio = mitad
        else:
            fin = mitad - 1
    return texto[:inicio] + puntos


class PanelResultados(ttk.Frame):

    def __init__(self, master):
        super().__init__(master)
        self._filas_originales = {}
        self._separadores = []
        self._reajuste_pendiente = None
        self._construir()

    def _construir(self):
        style = ttk.Style(self)
        style.configure("Plan.Treeview", font=tema.fuentes(self)[1])

        frame = ttk.Frame(self)
        self.frame_tabla = frame
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.tree = ttk.Treeview(frame, show="headings", selectmode="browse")
        self.tree.tag_configure("alterna", background=tema.FILA_ALTERNA)
        self.tree.bind("<Double-1>", self._mostrar_detalle)
        self.tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll_y.pack(side="right", fill="y")
        def desplazar_y(first, last):
            scroll_y.set(first, last)
            self._programar_reajuste()
        self.tree.configure(yscrollcommand=desplazar_y)

        self.vacio = tk.Label(self.tree, text="Ejecuta una consulta para ver los resultados",
                              bg=tema.SUPERFICIE, fg=tema.SECUNDARIO,
                              font=("TkDefaultFont", 11), borderwidth=0)
        self.vacio.place(relx=0.5, rely=0.5, anchor="center")

        scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.scroll_x = scroll_x
        scroll_x.pack(fill="x", padx=4, pady=(0, 4))
        def desplazar_x(first, last):
            scroll_x.set(first, last)
            self._programar_reajuste()
        self.tree.configure(xscrollcommand=desplazar_x)
        for evento in ("<Configure>", "<ButtonRelease-1>", "<B1-Motion>"):
            self.tree.bind(evento, self._programar_reajuste, add=True)

        self.barra_estado = ttk.Frame(self)
        self.barra_estado.pack(fill="x", padx=4, pady=(0, 4))
        self.mensaje = ttk.Label(self.barra_estado, text="Sin resultados", anchor="w")
        self.mensaje.pack(side="left", fill="x", expand=True)
        self.ayuda_detalle = ttk.Label(self.barra_estado, text="Doble clic en una fila: ver valores completos")
        self.ayuda_detalle.pack(side="right")

        # Frame para la galería multimedia (oculto por defecto)
        self.frame_galeria = ttk.Frame(self)
        self.canvas_galeria = None

    def limpiar(self):
        for col in self.tree["columns"]:
            self.tree.heading(col, text="")
        self.tree["columns"] = ()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._filas_originales.clear()
        for separador in self._separadores:
            separador.place_forget()
        self.mensaje.config(text="Sin resultados")
        self.mensaje.configure(style="TLabel")
        self.vacio.configure(text="Ejecuta una consulta para ver los resultados")
        self.vacio.place(relx=0.5, rely=0.5, anchor="center")

        # Restaurar vista de tabla si estábamos en galería
        self.frame_galeria.pack_forget()
        self.canvas_galeria = None
        for widget in self.frame_galeria.winfo_children():
            widget.destroy()
        if not self.frame_tabla.winfo_manager():
            self.frame_tabla.pack(fill="both", expand=True, padx=4, pady=4, before=self.barra_estado)
        if not self.scroll_x.winfo_manager():
            self.scroll_x.pack(fill="x", padx=4, pady=(0, 4), before=self.barra_estado)

    def mostrar_resultados(self, columnas, filas):
        self.limpiar()
        if not columnas:
            return

        self.vacio.place_forget()

        self.tree["columns"] = list(columnas)
        es_plan = list(columnas) == ["QUERY PLAN"]
        self.tree.configure(style="Plan.Treeview" if es_plan else "Treeview")
        fuente = tkfont.Font(self, font=tema.fuentes(self)[1])

        for i, col in enumerate(columnas):
            # Números a la derecha para comparar magnitudes, texto a la izquierda.
            numerica = es_numerica(fila[i] for fila in filas)
            # Centrar números deja separación visual respecto al texto contiguo.
            alineacion = "center" if numerica else "w"
            col_lower = col.lower()
            self.tree.heading(col, text=col, anchor=alineacion)

            if es_plan:
                largo = max((len(str(fila[0])) for fila in filas), default=40)
                self.tree.column(col, width=max(400, largo * 8), stretch=True, anchor="w")
            elif "score" in col_lower or "relevancia" in col_lower:
                self.tree.column(col, width=120, minwidth=100, stretch=False, anchor="center")
            elif "fragmento" in col_lower or "snippet" in col_lower:
                self.tree.column(col, width=420, minwidth=200, anchor="w", stretch=True)
            else:
                # Medir una muestra acotada: evita recorrer dos veces tablas enormes.
                muestra = filas[:200]
                ancho = max((fuente.measure(str(fila[i])) for fila in muestra if fila[i] is not None), default=0)
                ancho = max(fuente.measure(str(col)), ancho) + 32
                self.tree.column(col, width=min(700, max(100 if numerica else 200, ancho)), minwidth=90,
                                 stretch=not numerica, anchor=alineacion)

        for i, fila in enumerate(filas):
            fila_formateada = []
            for columna, val in zip(columnas, fila):
                col_lower = columna.lower()
                if val is not None and ("score" in col_lower or "relevancia" in col_lower):
                    try:
                        val = f"{float(val):.4f}"
                    except (ValueError, TypeError):
                        pass
                elif val is not None and ("fragmento" in col_lower or "snippet" in col_lower):
                    val_str = str(val)
                    if len(val_str) > 150:
                        val = val_str[:147] + "..."
                fila_formateada.append(val)
            item = self.tree.insert("", tk.END, values=tuple(fila_formateada), tags=("alterna",) if i % 2 else ())
            self._filas_originales[item] = tuple(fila)

        n = len(filas)
        self.mensaje.config(text=f"{n} fila(s)")
        self.mensaje.configure(style="StatusOk.TLabel")
        self._programar_reajuste()

    def _programar_reajuste(self, _event=None):
        if self._reajuste_pendiente is not None:
            self.after_cancel(self._reajuste_pendiente)
        self._reajuste_pendiente = self.after(35, self._reajustar_tabla)

    def _reajustar_tabla(self):
        """Actualiza solamente las filas visibles tras resize o desplazamiento."""
        self._reajuste_pendiente = None
        columnas = self.tree["columns"]
        for separador in self._separadores:
            separador.place_forget()
        if not columnas or not self.tree.winfo_viewable():
            return
        fuente = tkfont.Font(self, font=tema.fuentes(self)[1])
        alto_fila = max(8, int(ttk.Style(self).lookup("Treeview", "rowheight") or 20) // 2)
        visibles = dict.fromkeys(self.tree.identify_row(y) for y in range(0, self.tree.winfo_height(), alto_fila))
        visibles.pop("", None)
        anchos = [self.tree.column(col, "width") for col in columnas]
        for item in visibles:
            fila = self._filas_originales.get(item)
            if fila is None:
                continue
            valores = []
            for col, valor, ancho in zip(columnas, fila, anchos):
                if valor is None:
                    valores.append("")
                    continue
                if "score" in col.lower() or "relevancia" in col.lower():
                    try:
                        valor = f"{float(valor):.4f}"
                    except (ValueError, TypeError):
                        pass
                valores.append(abreviar(valor, max(0, ancho - 16), fuente.measure))
            if tuple(map(str, self.tree.item(item, "values"))) != tuple(valores):
                self.tree.item(item, values=valores)
        if not visibles:
            return
        primero = next(iter(visibles))
        for i, col in enumerate(columnas[:-1]):
            caja = self.tree.bbox(primero, col)
            if not caja:
                continue
            x = caja[0] + caja[2] - 1
            if not 0 < x < self.tree.winfo_width() - 1:
                continue
            while len(self._separadores) <= i:
                self._separadores.append(tk.Frame(self.tree, width=1, borderwidth=0, highlightthickness=0))
            self._separadores[i].configure(background=tema.TOKENS["border"])
            self._separadores[i].place(x=x, y=max(0, caja[1]), width=1,
                                       height=max(0, self.tree.winfo_height() - caja[1]))

    def _mostrar_detalle(self, event):
        """Muestra los valores originales, sin truncamiento ni redondeo visual."""
        item = self.tree.identify_row(event.y)
        fila = self._filas_originales.get(item)
        if fila is None:
            return
        ventana = tk.Toplevel(self)
        ventana.title("Detalle de la fila")
        ventana.geometry("760x440")
        ventana.minsize(400, 220)
        ventana.configure(bg=tema.FONDO)
        contenido = tk.Text(ventana, wrap="word", bg=tema.SUPERFICIE, fg=tema.TEXTO,
                            insertbackground=tema.TEXTO, font=tema.fuentes(ventana)[1],
                            padx=16, pady=12, relief="flat", borderwidth=0)
        scroll = ttk.Scrollbar(ventana, orient="vertical", command=contenido.yview)
        contenido.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)
        contenido.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        contenido.tag_configure("columna", foreground=tema.ACENTO)
        for nombre, valor in zip(self.tree["columns"], fila):
            contenido.insert("end", f"{nombre}\n", "columna")
            contenido.insert("end", f"{'NULL' if valor is None else valor}\n\n")
        contenido.configure(state="disabled")

    def mostrar_galeria(self, tipo, items):
        """Muestra galería de imágenes o lista de audio.
        tipo: 'imagen' o 'audio'
        items: lista de tuplas (ruta_archivo, score)
        """
        self.limpiar()
        self.frame_tabla.pack_forget()
        self.scroll_x.pack_forget()
        self.frame_galeria.pack(fill="both", expand=True, before=self.barra_estado)

        self.canvas_galeria = tk.Canvas(self.frame_galeria, background=tema.FONDO, highlightthickness=0)
        scroll = ttk.Scrollbar(self.frame_galeria, orient="vertical", command=self.canvas_galeria.yview)
        self.canvas_galeria.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas_galeria.pack(side="left", fill="both", expand=True)
        self.contenido_galeria = ttk.Frame(self.canvas_galeria)
        ventana = self.canvas_galeria.create_window((0, 0), window=self.contenido_galeria, anchor="nw")
        self.contenido_galeria.bind("<Configure>", lambda _e: self.canvas_galeria.configure(
            scrollregion=self.canvas_galeria.bbox("all")))
        self.canvas_galeria.bind("<Configure>", lambda e: self.canvas_galeria.itemconfigure(ventana, width=e.width))

        if tipo == 'imagen':
            self._render_imagenes(items)
        elif tipo == 'audio':
            self._render_audio(items)

        self.mensaje.config(text=f"{len(items)} resultado(s) multimedia")
        self.mensaje.configure(style="StatusOk.TLabel")

    def _render_imagenes(self, items):
        if not HAS_PIL:
            ttk.Label(self.contenido_galeria, text="Error: Instala Pillow (pip install Pillow) para ver imágenes.").pack(pady=20)
            return

        row, col = 0, 0
        for ruta, score in items:
            frame_item = ttk.Frame(self.contenido_galeria)
            frame_item.grid(row=row, column=col, padx=10, pady=10)

            if os.path.exists(ruta):
                try:
                    with Image.open(ruta) as img:
                        img.thumbnail((150, 150))
                        photo = ImageTk.PhotoImage(img)
                    lbl_img = ttk.Label(frame_item, image=photo)
                    lbl_img.image = photo  # Mantener referencia
                    lbl_img.pack()
                except Exception as e:
                    ttk.Label(frame_item, text=f"Error cargando\n{os.path.basename(ruta)}").pack()
            else:
                ttk.Label(frame_item, text="Imagen no\nencontrada").pack()

            ttk.Label(frame_item, text=os.path.basename(ruta)).pack()
            if isinstance(score, (int, float)):
                ttk.Label(frame_item, text=f"Score: {score:.4f}").pack()

            col += 1
            if col > 3:  # 4 columnas
                col = 0
                row += 1

    def _render_audio(self, items):
        for i, (ruta, score) in enumerate(items):
            frame_item = ttk.Frame(self.contenido_galeria)
            frame_item.pack(fill="x", pady=5, padx=10)

            nombre = os.path.basename(ruta) if os.path.exists(ruta) else ruta
            ttk.Label(frame_item, text=nombre, width=40, anchor="w").pack(side="left")
            if isinstance(score, (int, float)):
                ttk.Label(frame_item, text=f"Score: {score:.4f}", width=15).pack(side="left", padx=10)

            btn_play = ttk.Button(frame_item, text="▶ Reproducir",
                                  command=lambda r=ruta: self._play_audio(r))
            btn_play.pack(side="right")

    def _play_audio(self, ruta):
        if os.path.exists(ruta):
            if os.name == 'nt':  # Windows
                os.startfile(ruta)
            else:  # Linux/Mac
                try:
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', ruta])
                except OSError as error:
                    self.mensaje.config(text=f"Error al abrir audio: {error}")
        else:
            self.mensaje.config(text=f"Error: Archivo de audio no encontrado en {ruta}")

    def mostrar_mensaje(self, texto):
        self.limpiar()
        self.mensaje.config(text=texto)
        self.mensaje.configure(style="StatusOk.TLabel")
        self.vacio.configure(text=texto)

    def mostrar_error(self, texto):
        self.limpiar()
        self.mensaje.config(text=f"Error: {texto}")
        self.mensaje.configure(style="StatusError.TLabel")
        self.vacio.configure(text="No se pudo ejecutar la consulta")
