"""Preprocesamiento de texto: tokenización, stopwords y stemming (issue #44)."""

from functools import lru_cache
from pathlib import Path
import re
import unicodedata

_LETTER = r"[^\W\d_]"
_ALNUM = r"[^\W_]"

# Sigla: letras sueltas separadas por puntos (O.N.U.).
_ACRONYM = rf"(?<!{_ALNUM})(?P<acronym>{_LETTER}(?:\.{_LETTER})+)\.?(?!{_ALNUM})"
# Decimal: números separados por punto o coma (3,14).
_NUMBER = r"(?P<number>\d+(?:[.,]\d+)+)"
# Palabra: letras y números seguidos, con apóstrofes internos (mp3, don't).
_WORD = rf"{_ALNUM}+(?:'{_ALNUM}+)*"

# El orden importa: se prueba primero la sigla, luego el decimal y al final la palabra.
_TOKEN = re.compile(f"{_ACRONYM}|{_NUMBER}|{_WORD}")

# La ñ no está aquí: es una letra distinta de la n (año no es ano).
_TILDES = str.maketrans("áéíóúü", "aeiouu")
IDIOMAS = ("es", "en")


# Convierte un texto en la lista de tokens que usarán los pasos siguientes del pipeline.
def tokenizar(texto: str) -> list[str]:
    """Separa el texto en tokens en minúsculas y descarta la puntuación.

    Las siglas se unen (O.N.U. -> onu) y los decimales son un solo token con punto
    (3,14 -> 3.14). Las tildes siguen aquí porque el stemmer las necesita.
    """
    texto = unicodedata.normalize("NFC", texto).lower().replace("’", "'")
    return [_normalizar(match) for match in _TOKEN.finditer(texto)]


# Da la forma final a un token: quita los puntos de las siglas y unifica el separador decimal.
def _normalizar(match: re.Match) -> str:
    if match["acronym"]:
        return match["acronym"].replace(".", "")
    if match["number"]:
        return match["number"].replace(",", ".")
    return match[0]


# Quita las tildes de una palabra y conserva la ñ.
def quitar_tildes(palabra: str) -> str:
    return palabra.translate(_TILDES)


# Lee la lista de stopwords de un idioma una sola vez y la guarda sin tildes.
@lru_cache(maxsize=None)
def stopwords(idioma: str = "es") -> frozenset[str]:
    if idioma not in IDIOMAS:
        raise ValueError(f"Idioma no soportado: {idioma}")
    ruta = Path(__file__).with_name(f"stopwords_{idioma}.txt")
    return frozenset(quitar_tildes(linea.strip()) for linea in ruta.read_text("utf-8").splitlines() if linea.strip())


# Elimina los tokens que son stopwords y deja los demás tal como llegaron.
def quitar_stopwords(tokens: list[str], idioma: str = "es") -> list[str]:
    lista = stopwords(idioma)
    return [token for token in tokens if quitar_tildes(token) not in lista]
