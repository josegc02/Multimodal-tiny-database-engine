"""Búsqueda en español: precisión de los 10 primeros resultados con y sin ampliar la consulta.

Uso, con la API corriendo sobre la tienda cargada::

    python -m benchmarks.tienda.busqueda_es

Cada búsqueda tiene el tipo de producto que se espera (las mismas reglas del título que
benchmarks.tienda.medir). Se pide a GET /catalogo la consulta tal cual y la ampliada con
tienda.busqueda.ampliar, para medir el efecto sin reiniciar la API.
"""
import json
import urllib.parse
import urllib.request

from benchmarks.tienda.medir import tipo_titulo
from tienda.busqueda import ampliar

API = "http://127.0.0.1:8000"
BUSQUEDAS = [
    ("mando inalámbrico", "mando"), ("mando para switch", "mando"), ("control de xbox", "mando"),
    ("audífonos gamer", "audífonos"), ("audífonos inalámbricos para ps5", "audífonos"), ("auriculares con micrófono", "audífonos"),
    ("teclado mecánico", "teclado"), ("teclado rgb", "teclado"), ("mouse inalámbrico", "mouse"), ("ratón para juegos", "mouse"),
    ("alfombrilla para mouse", "mousepad"), ("funda para switch", "estuche"), ("estuche de viaje", "estuche"),
    ("cargador de mandos ps4", "cargador o cable"), ("cable de carga", "cargador o cable"), ("soporte para audífonos", "soporte"),
    ("soporte vertical ps5", "soporte"), ("juego de carreras", "juego"), ("juego de fútbol", "juego"), ("pegatinas para consola", "skin"),
]


def buscar(q):
    url = f"{API}/catalogo?{urllib.parse.urlencode({'q': q, 'limite': 10})}"
    return json.load(urllib.request.urlopen(url, timeout=120))


def main():
    filas, total = [], {"tal cual": 0.0, "ampliada": 0.0}
    for q, esperado in BUSQUEDAS:
        fila = [q]
        for nombre, consulta in (("tal cual", q), ("ampliada", ampliar(q))):
            resultados = buscar(consulta)
            p = sum(tipo_titulo(r) == esperado for r in resultados) / 10
            total[nombre] += p
            fila.append(p)
        filas.append(fila)
        print(f"{q:36s} tal cual {fila[1]:.1f}   ampliada {fila[2]:.1f}", flush=True)
    n = len(BUSQUEDAS)
    print(f"\nP@10 promedio: tal cual {total['tal cual'] / n:.3f}, ampliada {total['ampliada'] / n:.3f}")
    json.dump({"busquedas": filas, "p10": {k: v / n for k, v in total.items()}},
              open("benchmarks/tienda/busqueda_es.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
