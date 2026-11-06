import tkinter as tk
from tkinter import ttk
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


class PanelResultados(ttk.Frame):

    def __init__(self, master):
        super().__init__(master)
        self._construir()

    def _construir(self):
        style = ttk.Style(self)
        style.configure("Plan.Treeview", font=tema.fuentes(self)[1])

        frame = ttk.Frame(self)
        self.frame_tabla = frame
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.tree = ttk.Treeview(frame, show="headings", selectmode="browse")
        self.tree.tag_configure("alterna", background=tema.FILA_ALTERNA)
        self.tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll_y.set)

        self.vacio = tk.Label(self.tree, text="Ejecuta una consulta para ver los resultados",
                              bg=tema.SUPERFICIE, fg=tema.SECUNDARIO,
                              font=("TkDefaultFont", 11), borderwidth=0)
        self.vacio.place(relx=0.5, rely=0.5, anchor="center")

        scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.scroll_x = scroll_x
        scroll_x.pack(fill="x", padx=4, pady=(0, 4))
        self.tree.configure(xscrollcommand=scroll_x.set)

        self.mensaje = ttk.Label(self, text="Sin resultados", anchor="w")
        self.mensaje.pack(fill="x", padx=4, pady=(0, 4))

        # Frame para la galería multimedia (oculto por defecto)
        self.frame_galeria = ttk.Frame(self)
        self.canvas_galeria = None

    def limpiar(self):
        for col in self.tree["columns"]:
            self.tree.heading(col, text="")
        self.tree["columns"] = ()
        for item in self.tree.get_children():
            self.tree.delete(item)
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
            self.frame_tabla.pack(fill="both", expand=True, padx=4, pady=4, before=self.mensaje)
        if not self.scroll_x.winfo_manager():
            self.scroll_x.pack(fill="x", padx=4, pady=(0, 4), before=self.mensaje)

    def mostrar_resultados(self, columnas, filas):
        self.limpiar()
        if not columnas:
            return

        self.vacio.place_forget()

        self.tree["columns"] = list(columnas)
        es_plan = list(columnas) == ["QUERY PLAN"]
        self.tree.configure(style="Plan.Treeview" if es_plan else "Treeview")

        for i, col in enumerate(columnas):
            # Números a la derecha para comparar magnitudes, texto a la izquierda.
            numerica = es_numerica(fila[i] for fila in filas)
            alineacion = "e" if numerica else "w"
            col_lower = col.lower()
            self.tree.heading(col, text=col, anchor=alineacion)

            if es_plan:
                largo = max((len(str(fila[0])) for fila in filas), default=40)
                self.tree.column(col, width=max(400, largo * 8), stretch=True, anchor="w")
            elif "score" in col_lower or "relevancia" in col_lower:
                self.tree.column(col, width=100, anchor="e")
            elif "fragmento" in col_lower or "snippet" in col_lower:
                self.tree.column(col, width=400, anchor="w", stretch=True)
            else:
                self.tree.column(col, width=120 if numerica else 220, minwidth=90,
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
            self.tree.insert("", tk.END, values=tuple(fila_formateada), tags=("alterna",) if i % 2 else ())

        n = len(filas)
        self.mensaje.config(text=f"{n} fila(s)")
        self.mensaje.configure(style="StatusOk.TLabel")

    def mostrar_galeria(self, tipo, items):
        """Muestra galería de imágenes o lista de audio.
        tipo: 'imagen' o 'audio'
        items: lista de tuplas (ruta_archivo, score)
        """
        self.limpiar()
        self.frame_tabla.pack_forget()
        self.scroll_x.pack_forget()
        self.frame_galeria.pack(fill="both", expand=True, before=self.mensaje)

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
