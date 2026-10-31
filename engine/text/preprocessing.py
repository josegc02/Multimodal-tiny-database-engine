"""Preprocesamiento de texto: tokenización, stopwords y stemming (issue #44)."""

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
