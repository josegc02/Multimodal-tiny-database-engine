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
        """Recarga la lista de tablas conservando la tabla seleccionada."""
        seleccion = self.lista.curselection()
        anterior = self.lista.get(seleccion[0]) if seleccion else None
        self.lista.delete(0, tk.END)

        if self.catalog is None:
            return

        nombres = sorted(self.catalog.tables.keys())
        for nombre in nombres:
            self.lista.insert(tk.END, nombre)

        if anterior in nombres:
            posicion = nombres.index(anterior)
            self.lista.selection_set(posicion)
            self.lista.see(posicion)
            self._on_seleccion(None)
        else:
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

        if binding.indexes:
            lineas.append("")
            lineas.append("Indices:")
            for campo, registro in binding.indexes.items():
                info = registro.metadata
                tipo = type(registro.index).__name__
                if info is not None and info.clustered:
                    tipo = "B+ agrupado (la tabla)"
                elif info is not None and info.ordered:
                    tipo = "B+ no agrupado"
                elif "Hash" in tipo:
                    tipo = "Hash extensible"
                nombre_indice = info.name if info is not None else campo
                lineas.append(f"  - {nombre_indice} ({campo}): {tipo}")

        if binding.primary_key:
            lineas.append("")
            lineas.append(f"Clave primaria: {binding.primary_key} ({binding.primary_key_name})")
        if binding.foreign_keys:
            lineas.append("")
            lineas.append("Llaves foraneas:")
            for fk in binding.foreign_keys:
                lineas.append(f"  - {fk.column} -> {fk.ref_table}({fk.ref_column}) ON DELETE {fk.on_delete}")
        referencias = self.catalog.referencing(nombre) if hasattr(self.catalog, "referencing") else []
        if referencias:
            lineas.append("")
            lineas.append("Referenciada por:")
            for fk in referencias:
                lineas.append(f"  - {fk.table}.{fk.column} ({fk.on_delete})")

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