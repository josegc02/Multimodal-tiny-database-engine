"""Tokens y estilos nativos del espacio de trabajo Dark / Neutral Pro."""

import sys
from tkinter import ttk, font as tkfont

TOKENS = {
    "canvas": "#171d26", "sidebar": "#1e2733", "panel": "#222c39",
    "editor": "#1c2530", "header": "#293647", "border": "#39485a",
    "text": "#e1e8f0", "muted": "#a6b5c7", "accent": "#77b7ff",
    "button": "#2769a5", "button_hover": "#337fbd", "selection": "#354f6b",
    "alternate": "#263241", "gutter": "#202b38", "success": "#87d7a7",
    "error": "#ff9399", "warning": "#e6c47a", "focus": "#83bfff",
    "keyword": "#8bbdff", "string": "#a6d79d", "type": "#6fdbc9",
    "comment": "#a2b1c2", "number": "#e7bb87",
}
FUENTES = {
    "ui": ("Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if sys.platform == "darwin" else "Inter", 10),
    "codigo": ("Consolas" if sys.platform == "win32" else "JetBrains Mono", 11),
}

FONDO = TOKENS["canvas"]
LATERAL = TOKENS["sidebar"]
LATERAL_TEXTO = TEXTO = TOKENS["text"]
LATERAL_SECUNDARIO = SECUNDARIO = TOKENS["muted"]
LATERAL_SELECCION = SELECCION = TOKENS["selection"]
SUPERFICIE = TOKENS["editor"]
ENCABEZADO = TOKENS["header"]
ACENTO = TOKENS["accent"]
FILA_ALTERNA = TOKENS["alternate"]
MARGEN = TOKENS["gutter"]


def fuentes(master):
    disponibles = set(tkfont.families(master))
    def elegir(candidatos, tamano):
        familia = next((f for f in candidatos if f in disponibles), None)
        return (familia, tamano) if familia else ("TkFixedFont" if tamano == 11 else "TkDefaultFont")
    return (elegir((FUENTES["ui"][0], "Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans"), 10),
            elegir((FUENTES["codigo"][0], "Consolas", "JetBrains Mono", "DejaVu Sans Mono"), 11))


def inicializar_estilos(master):
    """Instala clam y estilos planos, incluyendo foco y selección."""
    style = ttk.Style(master)
    style.theme_use("clam")
    ui, codigo = fuentes(master)
    linea = tkfont.Font(master, font=codigo).metrics("linespace")
    style.configure(".", background=FONDO, foreground=TEXTO, font=ui, borderwidth=0)
    style.configure("TFrame", background=FONDO)
    style.configure("Sidebar.TFrame", background=LATERAL)
    style.configure("TLabel", background=FONDO, foreground=TEXTO, padding=2)
    style.configure("StatusError.TLabel", foreground=TOKENS["error"])
    style.configure("StatusOk.TLabel", foreground=TOKENS["success"])
    style.configure("TNotebook", background=FONDO, borderwidth=0, tabmargins=(0, 0, 0, 0),
                    bordercolor=FONDO, lightcolor=FONDO, darkcolor=FONDO)
    style.configure("TNotebook.Tab", background=LATERAL, foreground=SECUNDARIO, padding=(16, 9), borderwidth=0,
                    bordercolor=LATERAL, lightcolor=LATERAL, darkcolor=LATERAL)
    style.map("TNotebook.Tab", background=[("selected", TOKENS["panel"]), ("active", ENCABEZADO)],
              foreground=[("selected", ACENTO), ("active", TEXTO)],
              bordercolor=[("selected", TOKENS["border"])],
              lightcolor=[("selected", TOKENS["border"])], darkcolor=[("selected", TOKENS["border"])])
    style.configure("TButton", background=ENCABEZADO, foreground=TEXTO, padding=(12, 7), relief="flat", borderwidth=0)
    style.map("TButton", background=[("disabled", LATERAL), ("pressed", SELECCION), ("active", SELECCION),
                                      ("focus", ENCABEZADO)],
              bordercolor=[("focus", TOKENS["focus"])],
              foreground=[("disabled", SECUNDARIO), ("focus", TEXTO)])
    style.configure("Accent.TButton", background=TOKENS["button"], foreground="#ffffff", padding=(14, 7), relief="flat")
    style.map("Accent.TButton", background=[("disabled", LATERAL), ("pressed", "#205784"),
                                           ("active", TOKENS["button_hover"]), ("focus", TOKENS["button_hover"])],
              bordercolor=[("focus", TOKENS["focus"])],
              foreground=[("disabled", SECUNDARIO)])
    style.configure("Treeview", background=SUPERFICIE, fieldbackground=SUPERFICIE, foreground=TEXTO,
                    font=codigo, rowheight=linea + 10, borderwidth=0, relief="flat",
                    bordercolor=FONDO, lightcolor=FONDO, darkcolor=FONDO)
    style.map("Treeview", background=[("selected", SELECCION)], foreground=[("selected", TEXTO)])
    style.configure("Treeview.Heading", background=ENCABEZADO, foreground=TEXTO, font=ui, padding=(8, 7), relief="flat")
    style.map("Treeview.Heading", background=[("active", SELECCION)])
    for orientation in ("Vertical", "Horizontal"):
        style.configure(orientation + ".TScrollbar", background=TOKENS["border"], troughcolor=FONDO,
                        bordercolor=FONDO, lightcolor=TOKENS["border"], darkcolor=TOKENS["border"],
                        arrowcolor=SECUNDARIO, borderwidth=0, relief="flat", arrowsize=10)
        style.map(orientation + ".TScrollbar", background=[("active", SELECCION)])
    style.configure("TPanedwindow", background=TOKENS["border"], sashwidth=5)
    return style, ui, codigo


def configurar_sintaxis(editor):
    for tag, color in (("keyword", "keyword"), ("string", "string"), ("type", "type"),
                       ("comment", "comment"), ("number", "number")):
        editor.tag_configure("sql_" + tag, foreground=TOKENS[color])
