"""Datos reproducibles compartidos por los experimentos del issue #10."""

import random
import string
from typing import Any, Dict, List

SCHEMA = [("id", "int"), ("name", "str", 20), ("price", "float")]


def generate_records(n: int, seed: int = 42) -> List[Dict[str, Any]]:
    """Genera n registros con IDs únicos 0..n-1 en orden aleatorio.

    Los nombres tienen exactamente 20 caracteres ASCII (20 bytes en el schema).
    Conserva el estado RNG del llamador aunque use random.seed(seed).
    """
    if type(n) is not int or n < 0:
        raise ValueError("n debe ser un entero no negativo")
    state = random.getstate()
    try:
        random.seed(seed)
        keys = list(range(n))
        random.shuffle(keys)
        return [{"id": key, "name": "".join(random.choices(string.ascii_letters, k=20)),
                 "price": round(random.uniform(1.0, 1000.0), 2)} for key in keys]
    finally:
        random.setstate(state)
