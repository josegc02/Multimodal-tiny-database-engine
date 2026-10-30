"""Panel de archivos: muestra las tablas cargadas y su estructura."""

import tkinter as tk
import ttkbootstrap as ttk
from tkinter import ttk as ttk_classic

class PanelArchivos(ttk.LabelFrame):
    """Panel que lista las tablas y sus esquemas."""

    def __init__(self, master, catalog=None):
        super().__init__(master, text="Explorador de Objetos")
        self.catalog = catalog
        self._construir()
        self.refresh()

    def _construir(self):
        # 1. Usamos ttk_classic aquí para evitar el bug de ttkbootstrap
        paned = ttk_classic.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill="both", expand=True, padx=2, pady=2)

        # --- Parte Superior: Lista de tablas ---
        frame_arriba = ttk.Frame(paned)
        paned.add(frame_arriba, weight=1)

        self.lista = tk.Listbox(frame_arriba, exportselection=False)
        self.lista.pack(side="left", fill="both", expand=True)

        scroll_lista = ttk.Scrollbar(frame_arriba, orient="vertical", command=self.lista.yview)
        scroll_lista.pack(side="right", fill="y")
        self.lista.config(yscrollcommand=scroll_lista.set)

        self.lista.bind("<<ListboxSelect>>", self._on_seleccion)

        # --- Parte Inferior: Esquema de la tabla ---
        frame_abajo = ttk.Frame(paned)
        paned.add(frame_abajo, weight=2)

        ttk.Label(frame_abajo, text="Propiedades / Esquema:").pack(anchor="w", padx=2, pady=(2,0))

        frame_texto = ttk.Frame(frame_abajo)
        frame_texto.pack(fill="both", expand=True, pady=2)

        self.texto_esquema = tk.Text(frame_texto, height=10, width=30,
                                     state="disabled", font=("Consolas", 9), wrap="word")
        self.texto_esquema.pack(side="left", fill="both", expand=True)

        scroll_texto = ttk.Scrollbar(frame_texto, orient="vertical", command=self.texto_esquema.yview)
        scroll_texto.pack(side="right", fill="y")
        self.texto_esquema.config(yscrollcommand=scroll_texto.set)

    def set_catalog(self, catalog):
        self.catalog = catalog
        self.refresh()

    def refresh(self):
        seleccion = self.lista.curselection()
        anterior = self.lista.get(seleccion[0]) if seleccion else None
        self.lista.delete(0, tk.END)

        if self.catalog is None:
            return

        nombres = sorted(self.catalog.tables.keys())
        for nombre in nombres:
            self.lista.insert(tk.END, nombre)

        if not nombres:
            self._mostrar_esquema("")
            return

        posicion = nombres.index(anterior) if anterior in nombres else 0
        self.lista.selection_set(posicion)
        self.lista.see(posicion)
        self._on_seleccion(None)

    def _on_seleccion(self, event):
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
            lineas.append("Índices:")
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
            lineas.append("Llaves foráneas:")
            for fk in binding.foreign_keys:
                lineas.append(f"  - {fk.column} -> {fk.ref_table}({fk.ref_column}) ON DELETE {fk.on_delete}")
        referencias = self.catalog.referencing(nombre) if hasattr(self.catalog, "referencing") else []
        if referencias:
            lineas.append("")
            lineas.append("Referenciada por:")
            for fk in referencias:
                lineas.append(f"  - {fk.table}.{fk.column} ({fk.on_delete})")

        stats = binding.statistics
        if stats is not None:
            lineas.append("")
            lineas.append(f"Filas: {stats.rows}")
            lineas.append(f"Páginas: {stats.pages}")

        self._mostrar_esquema("\n".join(lineas))

    def _mostrar_esquema(self, texto):
        self.texto_esquema.config(state="normal")
        self.texto_esquema.delete("1.0", tk.END)
        if texto:
            self.texto_esquema.insert("1.0", texto)
        self.texto_esquema.config(state="disabled")