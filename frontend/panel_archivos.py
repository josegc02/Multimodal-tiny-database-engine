"""Panel de archivos: muestra las tablas cargadas y su estructura."""

import tkinter as tk
from tkinter import ttk


class PanelArchivos(ttk.LabelFrame):
    """Panel que lista las tablas y sus esquemas."""

    def __init__(self, master, catalog=None):
        super().__init__(master, text="Archivos")
        self.catalog = catalog
        self._construir()
        self.refresh()

    def _construir(self):
        # Lista de tablas (izquierda)
        self.lista = tk.Listbox(self, exportselection=False)
        self.lista.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.lista.bind("<<ListboxSelect>>", self._on_seleccion)

        # Esquema de la tabla seleccionada (derecha)
        frame_derecha = ttk.Frame(self)
        frame_derecha.pack(side="right", fill="both", expand=True, padx=4, pady=4)

        ttk.Label(frame_derecha, text="Esquema:").pack(anchor="w")

        self.texto_esquema = tk.Text(frame_derecha, height=10, width=30,
                                     state="disabled", font=("Consolas", 10))
        self.texto_esquema.pack(fill="both", expand=True)

    def set_catalog(self, catalog):
        """Asigna el catalogo y refresca la lista de tablas."""
        self.catalog = catalog
        self.refresh()

    def refresh(self):
        """Recarga la lista de tablas desde el catalogo."""
        self.lista.delete(0, tk.END)

        if self.catalog is None:
            return

        for nombre in sorted(self.catalog.tables.keys()):
            self.lista.insert(tk.END, nombre)

        self._mostrar_esquema("")

    def _on_seleccion(self, event):
        """Muestra el esquema de la tabla seleccionada."""
        seleccion = self.lista.curselection()
        if not seleccion:
            return

        nombre = self.lista.get(seleccion[0])
        try:
            binding = self.catalog.table(nombre)
            storage = binding.storage
        except Exception as e:
            self._mostrar_esquema(f"Error: {e}")
            return

        # Construir el texto del esquema
        lineas = [f"Tabla: {nombre}", ""]
        lineas.append(f"Storage: {type(storage).__name__}")
        if hasattr(storage, "filepath"):
            lineas.append(f"Archivo: {storage.filepath}")
        elif hasattr(storage, "filepath_main"):
            lineas.append(f"Archivo main: {storage.filepath_main}")
            lineas.append(f"Archivo aux: {storage.filepath_aux}")
        lineas.append("")
        lineas.append("Campos:")
        for campo, tipo in zip(storage.schema.fields, storage.schema.types):
            lineas.append(f"  - {campo}: {tipo}")

        # Info adicional de estadisticas
        stats = binding.statistics
        if stats is not None:
            lineas.append("")
            lineas.append(f"Filas: {stats.rows}")
            lineas.append(f"Paginas: {stats.pages}")

        self._mostrar_esquema("\n".join(lineas))

    def _mostrar_esquema(self, texto):
        """Escribe texto en el area de esquema."""
        self.texto_esquema.config(state="normal")
        self.texto_esquema.delete("1.0", tk.END)
        if texto:
            self.texto_esquema.insert("1.0", texto)
        self.texto_esquema.config(state="disabled")