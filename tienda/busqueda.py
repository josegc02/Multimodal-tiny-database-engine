"""Búsqueda en español sobre descripciones en inglés.

Las descripciones del catálogo (Amazon) están en inglés y BM25 compara palabras: "mando
inalámbrico" no encontraba nada. Cada palabra de la búsqueda se completa con sus
equivalentes en inglés de un diccionario corto de la tienda; las palabras originales se
conservan, así que marcas, modelos y búsquedas en inglés siguen funcionando igual.
"""
import re
import unicodedata

DICCIONARIO = {
    "mando": "controller gamepad", "control": "controller gamepad", "joystick": "joystick controller",
    "inalambrico": "wireless", "bluetooth": "bluetooth wireless", "cable": "cable wired", "alambrico": "wired",
    "audifono": "headset headphones", "auricular": "headset headphones", "casco": "headset headphones",
    "diadema": "headset", "microfono": "microphone mic", "teclado": "keyboard", "mecanico": "mechanical",
    "raton": "mouse", "alfombrilla": "mousepad mouse pad", "tapete": "mousepad mouse pad",
    "consola": "console", "juego": "game", "videojuego": "video game", "funda": "case cover",
    "estuche": "case carrying", "viaje": "travel carrying", "cargador": "charger charging", "carga": "charging charger",
    "soporte": "stand holder mount", "base": "stand dock", "vertical": "vertical stand", "bateria": "battery",
    "pila": "battery", "memoria": "memory card", "tarjeta": "card", "regalo": "gift", "volante": "racing wheel",
    "pedal": "pedals", "silla": "chair", "camara": "camera", "pantalla": "screen", "protector": "protector",
    "pegatina": "skin sticker decal", "vinilo": "skin decal", "gafas": "vr headset", "virtual": "virtual reality vr",
    "carrera": "racing", "futbol": "soccer football fifa", "terror": "horror", "accion": "action",
    "aventura": "adventure", "deporte": "sports", "lucha": "fighting", "pelea": "fighting", "disparo": "shooter",
    "nino": "kids", "portatil": "portable", "luz": "light led", "negro": "black", "blanco": "white",
    "rojo": "red", "azul": "blue", "rosa": "pink", "morado": "purple", "verde": "green", "barato": "",
}
_PALABRAS = re.compile(r"[a-zA-Z0-9ñÑáéíóúüÁÉÍÓÚÜ]+")


def _plano(palabra):
    return "".join(c for c in unicodedata.normalize("NFD", palabra.lower()) if unicodedata.category(c) != "Mn")


def _traduccion(palabra):
    base = _plano(palabra)
    for forma in (base, base[:-1] if base.endswith("s") else None, base[:-2] if base.endswith("es") else None):
        if forma and forma in DICCIONARIO:
            return DICCIONARIO[forma]
    return None


def ampliar(consulta):
    """La consulta con los equivalentes en inglés agregados (sin repetir palabras)."""
    extra = []
    for palabra in _PALABRAS.findall(consulta or ""):
        traduccion = _traduccion(palabra)
        if traduccion:
            extra += [t for t in traduccion.split() if t not in extra]
    return f"{consulta} {' '.join(extra)}".strip() if extra else (consulta or "")
