import tkinter as tk
from tkinter import ttk
import os

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
        style.configure("Plan.Treeview", font=("Consolas", 10))

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.tree = ttk.Treeview(frame, show="headings", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll_y.set)

        scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        scroll_x.pack(fill="x", padx=4, pady=(0, 4))
        self.tree.configure(xscrollcommand=scroll_x.set)

        self.mensaje = ttk.Label(self, text="Sin resultados", anchor="w")
        self.mensaje.pack(fill="x", padx=4, pady=(0, 4))

        # Frame para la galería multimedia (oculto por defecto)
        self.frame_galeria = ttk.Frame(self)

    def limpiar(self):
        for col in self.tree["columns"]:
            self.tree.heading(col, text="")
        self.tree["columns"] = ()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.mensaje.config(text="Sin resultados")
        
        # Restaurar vista de tabla si estábamos en galería
        self.frame_galeria.pack_forget()
        for widget in self.frame_galeria.winfo_children():
            widget.destroy()

    def mostrar_resultados(self, columnas, filas):
        self.limpiar()
        if not columnas:
            return

        self.tree["columns"] = list(columnas)
        es_plan = list(columnas) == ["QUERY PLAN"]
        self.tree.configure(style="Plan.Treeview" if es_plan else "Treeview")
        
        for i, col in enumerate(columnas):
            col_lower = col.lower()
            alineacion = "e" if es_numerica(fila[i] for fila in filas) else "w"
            self.tree.heading(col, text=col, anchor=alineacion)
            
            if es_plan:
                largo = max((len(str(fila[0])) for fila in filas), default=40)
                self.tree.column(col, width=max(400, largo * 8), stretch=True, anchor="w")
            elif "score" in col_lower or "relevancia" in col_lower:
                self.tree.column(col, width=100, anchor="e")
            elif "fragmento" in col_lower or "snippet" in col_lower:
                self.tree.column(col, width=400, anchor="w", stretch=True)
            else:
                self.tree.column(col, width=100, anchor=alineacion)

        for fila in filas:
            fila_formateada = []
            for i, val in enumerate(fila):
                col_lower = columnas[i].lower()
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
            self.tree.insert("", tk.END, values=tuple(fila_formateada))

        n = len(filas)
        self.mensaje.config(text=f"{n} fila(s)")

    def mostrar_galeria(self, tipo, items):
        """Muestra galería de imágenes o lista de audio.
        tipo: 'imagen' o 'audio'
        items: lista de tuplas (ruta_archivo, score)
        """
        self.limpiar()
        self.tree.pack_forget()
        self.mensaje.pack_forget()
        self.frame_galeria.pack(fill="both", expand=True)

        if tipo == 'imagen':
            self._render_imagenes(items)
        elif tipo == 'audio':
            self._render_audio(items)
        
        self.mensaje.config(text=f"{len(items)} resultado(s) multimedia")
        self.mensaje.pack(fill="x", padx=4, pady=(0, 4))

    def _render_imagenes(self, items):
        if not HAS_PIL:
            ttk.Label(self.frame_galeria, text="Error: Instala Pillow (pip install Pillow) para ver imágenes.").pack(pady=20)
            return

        row, col = 0, 0
        for ruta, score in items:
            frame_item = ttk.Frame(self.frame_galeria)
            frame_item.grid(row=row, column=col, padx=10, pady=10)

            if os.path.exists(ruta):
                try:
                    img = Image.open(ruta)
                    img.thumbnail((150, 150))
                    photo = ImageTk.PhotoImage(img)
                    lbl_img = ttk.Label(frame_item, image=photo)
                    lbl_img.image = photo  # Mantener referencia
                    lbl_img.pack()
                except Exception as e:
                    ttk.Label(frame_item, text=f"Error cargando\n{os.path.basename(ruta)}").pack()
            else:
                ttk.Label(frame_item, text="Imagen no\nencontrada").pack()

            ttk.Label(frame_item, text=f"Score: {score:.4f}", font=("Arial", 8, "bold")).pack()

            col += 1
            if col > 3:  # 4 columnas
                col = 0
                row += 1

    def _render_audio(self, items):
        for i, (ruta, score) in enumerate(items):
            frame_item = ttk.Frame(self.frame_galeria)
            frame_item.pack(fill="x", pady=5, padx=10)

            nombre = os.path.basename(ruta) if os.path.exists(ruta) else ruta
            ttk.Label(frame_item, text=nombre, width=40, anchor="w").pack(side="left")
            ttk.Label(frame_item, text=f"Score: {score:.4f}", width=15).pack(side="left", padx=10)
            
            btn_play = ttk.Button(frame_item, text="▶ Reproducir", 
                                  command=lambda r=ruta: self._play_audio(r))
            btn_play.pack(side="right")

    def _play_audio(self, ruta):
        if os.path.exists(ruta):
            if os.name == 'nt':  # Windows
                os.startfile(ruta)
            else:  # Linux/Mac
                import subprocess
                subprocess.call(['xdg-open' if os.name == 'posix' else 'open', ruta])
        else:
            self.mensaje.config(text=f"Error: Archivo de audio no encontrado en {ruta}")

    def mostrar_mensaje(self, texto):
        self.limpiar()
        self.mensaje.config(text=texto)

    def mostrar_error(self, texto):
        self.limpiar()
        self.mensaje.config(text=f"Error: {texto}")