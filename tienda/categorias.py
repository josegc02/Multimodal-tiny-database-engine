"""Limpieza de la metadata de Amazon para la tienda.

El archivo de Video Games de Amazon Reviews 2023 trae ruido que la tienda no puede mostrar:

- **Productos fuera de tema**: libros, películas, música, comida o juegos de mesa con la ruta
  "Video Games > PC > Games" (p. ej. *Born a Crime*, cuya main_category es "Books").
  Se descartan por main_category, por el formato ("Type of item": Blu-ray, Paperback...),
  por campos que solo tienen libros y películas (ISBN, duración, director...) o por un
  título inequívoco ("[DVD]", "Complete Series").
- **Consolas contradictorias**: una funda de Switch en "Nintendo DS", un protector de
  Switch en "Wii", un cargador de PS5 en "PlayStation 4". Si el título nombra una sola
  consola y la ruta dice otra, la ruta pasa a la de esa consola (se conserva el resto:
  "Accessories > Cases & Storage").
- **Rutas promocionales** como segundo nivel ("Game Genre of the Month", "Ubisoft",
  "Value Games Under $20"): no son consolas. Pasan a la consola del título, o a
  "Video Games" si el título no nombra ninguna.
"""
import re

from tienda.recomendaciones import plataformas

RAIZ = "Video Games"
LEGADO = f"{RAIZ} > Legacy Systems"
RUTAS = {  # consola (como la nombra tienda.recomendaciones.plataformas) -> su ruta en Amazon
    "switch": f"{RAIZ} > Nintendo Switch",
    "ps5": f"{RAIZ} > PlayStation 5",
    "ps4": f"{RAIZ} > PlayStation 4",
    "xbox series": f"{RAIZ} > Xbox Series X & S",
    "xbox one": f"{RAIZ} > Xbox One",
    "pc": f"{RAIZ} > PC",
    "vr": f"{RAIZ} > Virtual Reality",
    "ps3": f"{LEGADO} > PlayStation Systems > PlayStation 3",
    "ps2": f"{LEGADO} > PlayStation Systems > PlayStation 2",
    "psp": f"{LEGADO} > PlayStation Systems > Sony PSP",
    "psvita": f"{LEGADO} > PlayStation Systems > PlayStation Vita",
    "xbox 360": f"{LEGADO} > Xbox Systems > Xbox 360",
    "3ds": f"{LEGADO} > Nintendo Systems > Nintendo 3DS & 2DS",
    "ds": f"{LEGADO} > Nintendo Systems > Nintendo DS",
    "wii u": f"{LEGADO} > Nintendo Systems > Wii U",
    "wii": f"{LEGADO} > Nintendo Systems > Wii",
    "gamecube": f"{LEGADO} > Nintendo Systems > GameCube",
    # Solo para reconocer la ruta (el título nunca da "mac" ni una Sega concreta): así un
    # soporte de PS5 que Amazon dejó en "Sega Game Gear" o en "Mac" pasa a su consola.
    "sega": f"{LEGADO} > Sega Systems",
    "mac": f"{RAIZ} > Mac",
}
# Segundo nivel que sí es una consola o familia de consolas (el resto es promocional).
CONSOLAS = {"Nintendo Switch", "PlayStation 5", "PlayStation 4", "Xbox Series X & S", "Xbox One", "PC", "Mac",
            "Virtual Reality", "Legacy Systems"}

MAIN_FUERA = {"Books", "Buy a Kindle", "Movies & TV", "Digital Music", "Grocery"}
FORMATOS_FUERA = {"Blu-ray", "DVD", "Paperback", "Hardcover", "Mass Market Paperback", "Spiral-bound",
                  "Leather Bound", "Board book", "Kindle Edition", "Library Binding", "Audible Audiobook"}
CAMPOS_FUERA = re.compile(r"^(ISBN|Print length|Hardcover|Paperback|Board book|Spiral-bound|Runtime|Run time|"
                          r"Director|Actors|Contributor|Aspect Ratio|Media Format|MPAA rating|Lexile)", re.I)
TITULO_FUERA = re.compile(r"\[(?:DVD|Blu-?ray)\b[^\]]*\]|\bDVD Collection\b|\bComplete (?:Movie |TV )?Series\b|"
                          r"\bTV Series\b|\[ART book\]|"
                          # Juegos de mesa, rompecabezas y libros de reglas que Amazon dejó en consolas
                          # (Star Wars Armada en "PC > Games", un rompecabezas en "PlayStation 2").
                          r"\bboard game\b|\bminiatures battle\b|\bjigsaw puzzle\b|\bstrategy card game\b|\bcodex:", re.I)


# Revisión a mano de los productos sin ninguna palabra de videojuegos (2026-11-20): no son de la
# tienda y ningún campo de Amazon los delata (la main_category dice Video Games o Electronics).
EXCLUIDOS = {
    "B0BRF6PX4Z": "protector de cámara de iPhone",
    "B0BG8Z51S5": "audífonos Lightning",
    "B09QQT4ZMC": "cómic",
    "B0BS6J3HMP": "audífonos infantiles",
    "1626547203": "libro para colorear",
    "B08X226PPT": "libro",
    "B07WMTHLTH": "cargador de Apple Watch",
    "B09TWYP159": "libro",
    "B0B55Z3Y2Y": "audífonos",
    "B00O2GW3EO": "antivirus",
    "B08DBN47CH": "adorno navideño",
    "B07DK574FC": "estuche de celular",
    "B087P9LD3P": "cargador de Fitbit",
    "B07KM3Z3JQ": "cargador de Fitbit",
    "B00W5BLE3O": "cargador de Fitbit",
    "B01H75DVOC": "cargador de Fitbit",
    "B07QDST5LG": "audífonos",
    "B00LJ7QC3W": "insumo de destilado",
    "B09SV96K6S": "esmalte de uñas",
    "B09KHVTSJR": "réplica de cinturón de lucha",
    "B082H2NWGS": "figura de Harry Potter",
    "B09JSL95WP": "juguete Playmobil",
    "B08D6ZZ4M8": "cargador de Apple",
    "B08QG98TPZ": "lightstick de K-pop",
    "B08NDVBKL3": "lightstick de K-pop",
    "B01N1GX16M": "software de impuestos",
    "B07QC55N5L": "figuras de acción",
    "B0BS3VMVFK": "audífonos",
    "B01N3C0G9W": "álbum de música",
    "B085QK8D9W": "álbum de música",
    "B09BQWM81V": "Funko Pop de anime",
    "B07PBBX4C5": "Funko Pop de Harry Potter",
    "B06WGTDPJ4": "Funko Pop de anime",
    "B096JZVGDJ": "Funko Pop de Marvel",
    "B096KD27TN": "Funko Pop de Disney",
    "B09BC4LVY1": "Funko Pop de anime",
    "B09F616XFR": "Funko Pop de anime",
    "B09F57618W": "Funko Pop de fútbol",
}


def fuera_de_tema(meta):
    """El motivo por el que un registro de Amazon no es de la tienda, o None si lo es."""
    if meta.get("parent_asin") in EXCLUIDOS:
        return f"revisión: {EXCLUIDOS[meta['parent_asin']]}"
    if meta.get("main_category") in MAIN_FUERA:
        return f"main_category {meta['main_category']}"
    detalles = meta.get("details") or {}
    formato = str(detalles.get("Type of item", ""))
    if formato in FORMATOS_FUERA:
        return f"formato {formato}"
    campo = next((k for k in detalles if CAMPOS_FUERA.match(k)), None)
    if campo:
        return f"campo {campo}"
    if TITULO_FUERA.search(meta.get("title") or ""):
        return "título de película o serie"
    return None


def consola_de_ruta(ruta):
    """La consola de una ruta de categoría (la de prefijo más largo), o None."""
    mejor = None
    for consola, prefijo in RUTAS.items():
        if (ruta == prefijo or ruta.startswith(prefijo + " > ")) and (mejor is None or len(prefijo) > len(RUTAS[mejor])):
            mejor = consola
    return mejor


def normalizar(categorias, titulo):
    """La ruta de categoría que la tienda muestra, corregida contra el título."""
    partes = [c for c in categorias if isinstance(c, str) and c.strip()]
    ruta = " > ".join(partes) or RAIZ
    del_titulo = plataformas(titulo, "")
    unica = next(iter(del_titulo)) if len(del_titulo) == 1 else None
    if unica not in RUTAS:
        unica = None
    promocional = len(partes) < 2 or partes[0] != RAIZ or partes[1] not in CONSOLAS
    if promocional:
        return RUTAS[unica] if unica else RAIZ
    actual = consola_de_ruta(ruta)
    if unica and actual and unica != actual:
        resto = ruta[len(RUTAS[actual]):]  # " > Accessories > Cases & Storage", o vacío
        if actual == "sega":  # una familia: se quita también la consola Sega concreta
            resto = "".join(f" > {parte}" for parte in resto.split(" > ")[2:])
        return RUTAS[unica] + resto
    return ruta
