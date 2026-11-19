"""Tiendas reales de Lima desde OpenStreetMap (issue #100).

Consulta la API Overpass por comercios relacionados con videojuegos dentro
del recuadro de Lima Metropolitana y escribe ``datasets/tienda/tiendas_lima.csv``
con su ubicación como ``POINT(lat, lon)``. OpenStreetMap cambia a diario,
así que ese CSV es una instantánea que **se versiona** (licencia ODbL,
© OpenStreetMap contributors); la fecha de la consulta queda en
``tiendas_lima.json``.

Uso::

    python -m tienda.osm
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from tienda.comun import DATASET_DIR, USER_AGENT, escribir_csv

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Espejo público de respaldo si el servidor principal está saturado (429/504).
OVERPASS_RESPALDO = "https://overpass.kumi.systems/api/interpreter"
TIENDAS = DATASET_DIR / "tiendas_lima.csv"
CONSULTA_INFO = DATASET_DIR / "tiendas_lima.json"
# Recuadro de Lima Metropolitana (sur, oeste, norte, este): de Pucusana a Ancón.
LIMA_BBOX = (-12.52, -77.20, -11.57, -76.62)
TIPOS = ("video_games", "electronics", "computer", "department_store", "mall")
CAMPOS_TIENDAS = ("id", "osm_id", "nombre", "tipo", "distrito", "direccion", "ubicacion")


def consulta(bbox=LIMA_BBOX, tipos=TIPOS):
    sur, oeste, norte, este = bbox
    return (f'[out:json][timeout:180];\n'
            f'nwr["shop"~"^({"|".join(tipos)})$"]["name"]({sur},{oeste},{norte},{este});\n'
            f'out center tags;')


def pedir(texto, abrir=urllib.request.urlopen, urls=(OVERPASS_URL, OVERPASS_RESPALDO), pausa=10, log=print):
    """POST a Overpass; ante saturación o caída reintenta y luego prueba el espejo."""
    datos = urllib.parse.urlencode({"data": texto}).encode()
    ultimo = None
    for url in urls:
        for intento in range(3):
            request = urllib.request.Request(url, data=datos, headers={"User-Agent": USER_AGENT})
            try:
                with abrir(request, timeout=240) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 502, 503, 504):
                    raise
                ultimo = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                ultimo = exc
            log(f"Overpass no respondió ({ultimo}); reintento en {pausa * (intento + 1)} s")
            time.sleep(pausa * (intento + 1))
    raise ConnectionError(f"Overpass no disponible: {ultimo}")


def tiendas(respuesta, bbox=LIMA_BBOX):
    """Filas de tiendas ordenadas por identificador OSM; ids desde 1."""
    sur, oeste, norte, este = bbox
    filas = []
    for elemento in respuesta.get("elements", []):
        tags = elemento.get("tags", {})
        centro = elemento if elemento.get("type") == "node" else elemento.get("center", {})
        lat, lon = centro.get("lat"), centro.get("lon")
        nombre = " ".join(str(tags.get("name", "")).split())
        if lat is None or lon is None or not nombre or not (sur <= lat <= norte and oeste <= lon <= este):
            continue
        calle = " ".join(p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p)
        filas.append({
            "osm_id": f"{elemento['type']}/{elemento['id']}",
            "nombre": nombre,
            "tipo": tags.get("shop", "")[:20],
            "distrito": tags.get("addr:district") or tags.get("addr:suburb") or tags.get("addr:city") or "",
            "direccion": calle,
            "ubicacion": f"POINT({lat:.7f}, {lon:.7f})",
        })
    orden = {"node": 0, "way": 1, "relation": 2}
    filas.sort(key=lambda f: (orden[f["osm_id"].split("/")[0]], int(f["osm_id"].split("/")[1])))
    return [{"id": numero, **fila} for numero, fila in enumerate(filas, 1)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tiendas de Lima desde OpenStreetMap (issue #100)")
    parser.add_argument("--forzar", action="store_true", help="rehacer la instantánea existente")
    args = parser.parse_args(argv)
    if TIENDAS.exists() and not args.forzar:
        parser.error(f"{TIENDAS} ya existe: es la instantánea versionada; use --forzar para rehacerla")
    texto = consulta()
    filas = tiendas(pedir(texto))
    if not filas:
        parser.exit(1, "Error: Overpass no devolvió tiendas\n")
    escribir_csv(TIENDAS, CAMPOS_TIENDAS, filas)
    CONSULTA_INFO.write_text(json.dumps({
        "fuente": "OpenStreetMap vía Overpass API",
        "licencia": "ODbL 1.0 — © OpenStreetMap contributors",
        "url": OVERPASS_URL,
        "fecha_consulta": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "consulta": texto,
        "tiendas": len(filas),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    por_tipo = {}
    for fila in filas:
        por_tipo[fila["tipo"]] = por_tipo.get(fila["tipo"], 0) + 1
    print(f"{len(filas)} tiendas en {TIENDAS}: {por_tipo}")


if __name__ == "__main__":
    main()