"""Panel de plan de ejecucion: visualiza como se ejecuto la consulta."""

import tkinter as tk
from tkinter import ttk


class PanelPlanEjecucion(ttk.LabelFrame):
    """Panel que muestra el plan de ejecucion en formato de arbol.

    Uso:
        panel.mostrar_plan_texto("Filter\\n  └── Scan (cuentas)")
        panel.mostrar_plan_objeto(plan)
        panel.limpiar()
    """

    def __init__(self, master):
        super().__init__(master, text="Plan de ejecucion")
        self._construir()

    def _construir(self):
        # Area de texto con scroll
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.texto = tk.Text(frame, height=10, width=50, state="disabled",
                             wrap="word", font=("Consolas", 10))
        self.texto.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(frame, orient="vertical",
                                 command=self.texto.yview)
        scroll_y.pack(side="right", fill="y")
        self.texto.configure(yscrollcommand=scroll_y.set)

    def limpiar(self):
        """Limpia el area de texto."""
        self._set_texto("")

    def mostrar_plan_texto(self, texto):
        """Muestra un texto de plan ya formateado."""
        self._set_texto(texto)

    def mostrar_plan_objeto(self, plan):
        """Muestra un plan a partir de su representacion dict.

        El plan debe tener un metodo to_dict() o ser un dict directo.
        """
        if hasattr(plan, "to_dict"):
            data = plan.to_dict()
        elif isinstance(plan, dict):
            data = plan
        else:
            self._set_texto(str(plan))
            return

        lineas = self._formatear_plan(data, 0)
        self._set_texto("\n".join(lineas))

    def _formatear_plan(self, nodo, nivel):
        """Convierte un plan a lista de lineas con indentacion."""
        indent = "  " * nivel
        if isinstance(nodo, dict):
            operacion = nodo.get("operation", "?")
            opciones = nodo.get("options", {})
            children = nodo.get("children", [])

            # Encabezado
            linea = f"{indent}{operacion}"
            if opciones:
                partes = [f"{k}={v}" for k, v in opciones.items()]
                linea += f" ({', '.join(partes)})"
            lineas = [linea]

            # Hijos
            for child in children:
                lineas.extend(self._formatear_plan(child, nivel + 1))
            return lineas
        else:
            return [f"{indent}{nodo}"]

    def _set_texto(self, texto):
        """Reemplaza el contenido del area de texto."""
        self.texto.config(state="normal")
        self.texto.delete("1.0", tk.END)
        if texto:
            self.texto.insert("1.0", texto)
        self.texto.config(state="disabled")