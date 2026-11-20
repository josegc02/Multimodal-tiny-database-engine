"""Exactitud de las recomendaciones de la tienda con dos métricas.

Uso, desde la raíz del repositorio (después de tienda.amazon seleccionar, tienda.imagenes
y tienda.amazon compras, que descarga las reseñas)::

    python -m benchmarks.tienda.medir

Métricas (ver README.md):
- tipo: P@10 del mismo tipo de producto (sacado del título con reglas);
- comportamiento: recall@10 de los productos que el mismo usuario reseñó (compra
  verificada) a 30 días o menos, después del corte temporal T. La señal de compras se
  construye solo con reseñas anteriores a T.
Regla de selección, fijada antes de medir: en validación gana la configuración con
mayor promedio de (métrica / mejor valor de esa métrica en la etapa). Los resultados se
reportan en consultas de prueba distintas, con IC 95 % por bootstrap pareado.
La imagen se busca exacta por coseno (sin el error del HNSW) y el texto con
MATCH ... USING BM25 en nuestro motor. Las cachés quedan en datasets/tienda/benchmark.
"""
import bisect
import collections
import csv
import gzip
import json
import random
import re
import tempfile
import time
from pathlib import Path

import numpy as np

from tienda.recomendaciones import COSENO_DUPLICADO, clave_titulo, plataformas, sin_duplicados

PRODUCTOS = Path("datasets/tienda/generated/productos.csv")
RESENAS = Path("datasets/tienda/raw/Video_Games.jsonl.gz")
CACHE = Path("datasets/tienda/benchmark")
SALIDA = Path(__file__).with_name("resultados.json")
VENTANA = 30 * 86400
MAX_COMPRAS = 20
K_RRF = 60
REGLAS = [("mousepad", r"mouse ?pad|desk mat|gaming mat"), ("mouse", r"\bmouse\b|\bmice\b"),
          ("teclado", r"keyboard|keycaps?\b"), ("audífonos", r"headset|headphone|earphone|earbud"),
          ("mando", r"controller|gamepad|joystick|joy-?cons?\b|fight ?stick"),
          ("estuche", r"\bcase\b|carrying|travel bag|\bpouch\b|sleeve"),
          ("cargador o cable", r"charg|\bcable\b|adapter|power supply|\bbattery|batteries"),
          ("soporte", r"\bstand\b|\bmount\b|holder|\bdock\b"), ("skin", r"\bskins?\b|sticker|decal")]


def tipo_titulo(p):
    """Tipo de producto: los juegos por su categoría (fiable); el resto por el título."""
    if p["categoria"].endswith("> Games") and "Accessor" not in p["categoria"]:
        return "juego"
    t = p["titulo"].lower()
    return next((nombre for nombre, patron in REGLAS if re.search(patron, t)), None)


def unitarios(v):
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v), where=n > 0)


def vectores(nombre, productos, extraer):
    archivo = CACHE / f"{nombre}.npy"
    if archivo.exists():
        return unitarios(np.load(archivo))
    filas = []
    for k, p in enumerate(productos):
        try:
            filas.append(np.asarray(extraer(p["imagen"]), np.float32))
        except Exception:  # noqa: BLE001  imagen ilegible: vector nulo, nunca es vecina
            filas.append(None)
        if (k + 1) % 1000 == 0:
            print(f"  {nombre}: {k + 1}/{len(productos)}", flush=True)
    dim = next(len(v) for v in filas if v is not None)
    v = np.stack([x if x is not None else np.zeros(dim, np.float32) for x in filas])
    np.save(archivo, v)
    return unitarios(v)


def resenas_catalogo(productos):
    """(usuario, índice de producto, fecha en s) de las compras verificadas del catálogo."""
    archivo = CACHE / "resenas.csv"
    if not archivo.exists():
        indice = {p["asin"]: i for i, p in enumerate(productos)}
        with gzip.open(RESENAS, "rt", encoding="utf-8") as f, open(archivo, "w", newline="", encoding="utf-8") as out:
            w = csv.writer(out)
            for linea in f:
                r = json.loads(linea)
                i = indice.get(r.get("parent_asin"))
                if i is not None and r.get("user_id") and r.get("verified_purchase") is True:
                    w.writerow([r["user_id"], i, int(r.get("timestamp") or 0) // 1000])
    return [(u, int(i), int(f)) for u, i, f in csv.reader(open(archivo, encoding="utf-8"))]


def bm25(productos, consultas):
    """Los 102 mejores por BM25 de nuestro motor (índice SPIMI en inglés), sin la consulta."""
    archivo = CACHE / "bm25.json"
    texto = {int(k): {int(a): b for a, b in v.items()} for k, v in json.load(open(archivo)).items()} \
        if archivo.exists() else {}
    faltan = [q for q in consultas if q not in texto]
    if faltan:
        from frontend.motor import Motor
        from tienda.recomendaciones import consultar, literal
        motor = Motor(directorio=tempfile.mkdtemp(), modo_demo=False)
        motor.ejecutar("CREATE TABLE productos (id INT PRIMARY KEY, descripcion TEXT)")
        for inicio in range(0, len(productos), 500):
            motor.ejecutar("INSERT INTO productos VALUES " + ", ".join(
                f"({i}, {literal(p['descripcion'])})" for i, p in enumerate(productos[inicio:inicio + 500], inicio)))
        motor.ejecutar("CREATE INDEX desc_idx ON productos (descripcion) USING SPIMI WITH (LANGUAGE = 'en')")
        for k, q in enumerate(faltan, 1):
            filas = consultar(motor, f"SELECT id, SCORE() AS s FROM productos WHERE MATCH(descripcion, "
                                     f"{literal(productos[q]['descripcion'])}) USING BM25 ORDER BY s DESC LIMIT 102")
            texto[q] = {f["id"]: f["s"] for f in filas if f["id"] != q}
            if k % 200 == 0 or k == len(faltan):
                print(f"  bm25: {k}/{len(faltan)}", flush=True)
                json.dump(texto, open(archivo, "w"))
        motor.cerrar()
    return texto


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    productos = list(csv.DictReader(open(PRODUCTOS, encoding="utf-8")))
    n = len(productos)
    tipo = [tipo_titulo(p) for p in productos]
    cat = [p["categoria"] for p in productos]
    plat = [plataformas(p["titulo"], p["categoria"]) for p in productos]

    # Consultas de la métrica de tipo: hasta 30 por tipo en validación y 60 en prueba.
    por_tipo = collections.defaultdict(list)
    for i, t in enumerate(tipo):
        if t:
            por_tipo[t].append(i)
    rnd = random.Random(42)
    tipo_val = sorted(i for ids in por_tipo.values() for i in rnd.sample(ids, min(30, len(ids))))
    rnd2, tipo_prueba = random.Random(2026), []
    for ids in por_tipo.values():
        libres = [x for x in ids if x not in set(tipo_val)]
        tipo_prueba += rnd2.sample(libres, min(60, len(libres)))
    tipo_prueba.sort()

    # Métrica de comportamiento: corte T en el percentil 80 de las fechas.
    resenas = resenas_catalogo(productos)
    T = int(np.percentile([f for _, _, f in resenas], 80))
    construccion, evaluacion = collections.defaultdict(dict), collections.defaultdict(list)
    for u, p, f in resenas:
        if f < T:
            if p not in construccion[u] or f < construccion[u][p]:
                construccion[u][p] = f
        else:
            evaluacion[u].append((f, p))
    objetivos = collections.defaultdict(set)
    for rs in evaluacion.values():
        if len(rs) <= MAX_COMPRAS:
            for f1, a in rs:
                for f2, b in rs:
                    if a != b and abs(f1 - f2) <= VENTANA:
                        objetivos[a].add(b)
    comp = sorted(objetivos)
    random.Random(11).shuffle(comp)
    comp_val, comp_prueba = sorted(comp[:800]), sorted(comp[800:1600])
    print(f"{len(resenas)} compras verificadas; corte {np.datetime64(T, 's')}; cobertura "
          f"{len(objetivos)}/{n} productos; consultas de comportamiento {len(comp_val)}/{len(comp_prueba)}")

    # Señales.
    from engine.features.image.mobilenet import MobileNetExtractor
    from engine.features.registry import extract_features
    img = {"sift": vectores("sift_bovw", productos, lambda r: extract_features("image", r)),
           "mobilenet": vectores("mobilenet", productos, MobileNetExtractor())}
    texto = bm25(productos, sorted(set(tipo_val) | set(tipo_prueba) | set(comp_val) | set(comp_prueba)))
    popularidad = collections.Counter(p for rs in construccion.values() for p in rs)
    populares = [p for p, _ in popularidad.most_common(20)]

    def indice(usuarios):
        por_producto = collections.defaultdict(list)
        for u in usuarios:
            for p in construccion[u]:
                por_producto[p].append(u)
        return por_producto

    # "hoy": como generaba compras.csv tienda.amazon antes (primero quien más compra, 100k filas).
    orden = sorted((u for u, c in construccion.items() if len(c) >= 2), key=lambda u: (-len(construccion[u]), u))
    hoy, filas = [], 0
    for u in orden:
        if filas + len(construccion[u]) > 100_000:
            break
        hoy.append(u)
        filas += len(construccion[u])
    filtrados = [u for u, c in construccion.items() if 2 <= len(c) <= MAX_COMPRAS]
    variantes = {"hoy": (indice(hoy), None), "hoy_ventana": (indice(hoy), VENTANA),
                 "usuarios": (indice(filtrados), None), "filtrada": (indice(filtrados), VENTANA)}
    cache = {}

    def compras(variante, q):
        if (variante, q) not in cache:
            por_producto, ventana = variantes[variante]
            cuenta = collections.Counter()
            for u in por_producto.get(q, ()):
                fq = construccion[u][q]
                for b, fb in construccion[u].items():
                    if b != q and (ventana is None or abs(fb - fq) <= ventana):
                        cuenta[b] += 1
            cache[variante, q] = dict(cuenta)
        return cache[variante, q]

    def imagen(nombre, q, k):
        if (nombre, q) not in cache:
            sim = img[nombre] @ img[nombre][q]
            sim[q] = -np.inf
            top = np.argpartition(-sim, 101)[:101]
            cache[nombre, q] = [(int(i), float(sim[i])) for i in top[np.argsort(-sim[top])] if sim[i] > 0]
        return dict(cache[nombre, q][:k])

    def recomendar(q, c):
        """Como tienda.recomendaciones.fusionar (rrf o max) más el bono de categoría."""
        k = c["k"]
        senales = [(compras(c["compras"], q), c["wc"]), (imagen(c["img"], q, k), c["wi"]),
                   (dict(sorted(texto[q].items(), key=lambda x: -x[1])[:k]), c["wt"])]
        total = collections.defaultdict(float)
        for s, w in senales:
            s = sorted(((i, v) for i, v in s.items() if i != q and v > 0), key=lambda x: (-x[1], x[0]))
            if not w or not s:
                continue
            for r, (i, v) in enumerate(s):
                total[i] += w * ((K_RRF + 1) / (K_RRF + 1 + r) if c["fusion"] == "rrf" else v / s[0][1])
        for i in list(total):
            if c["wcat"] and cat[i] and cat[i] == cat[q]:
                total[i] += c["wcat"]
            if c.get("wplat") and len(plat[q]) == 1 and plat[q] <= plat[i]:
                total[i] += c["wplat"]
        ordenados = [i for i, _ in sorted(total.items(), key=lambda x: (-x[1], x[0]))]
        if not c.get("dedup"):
            return ordenados[:10]
        filas = [{"id": i, "titulo": productos[i]["titulo"]} for i in ordenados[:60]]
        origen = {"id": q, "titulo": productos[q]["titulo"]}
        return [f["id"] for f in sin_duplicados(origen, filas, lambda i: img["mobilenet"][i])]

    def m_tipo(qs, c=None, recs=None):
        out = []
        for q in qs:
            r = recs(q) if recs else recomendar(q, c)
            out.append(np.mean([tipo[v] == tipo[q] for v in r]) if r else 0.0)
        return np.array(out)

    def m_plataforma(qs, c=None, recs=None):
        """Fracción de recomendados de la misma consola (consultas con una sola plataforma)."""
        out = []
        for q in qs:
            if len(plat[q]) == 1:
                r = recs(q) if recs else recomendar(q, c)
                out.append(np.mean([plat[q] <= plat[v] for v in r]) if r else 0.0)
        return np.array(out)

    def duplicados(qs, c):
        """Fracción de listas con algún duplicado (del consultado o entre sí)."""
        con = 0
        for q in qs:
            r = recomendar(q, c)
            claves = [clave_titulo(productos[i]["titulo"]) for i in [q] + r]
            vecs = img["mobilenet"][[q] + r]
            sim = vecs @ vecs.T
            np.fill_diagonal(sim, 0)
            con += len(set(claves)) < len(claves) or bool((sim > COSENO_DUPLICADO).any())
        return con / len(qs)

    def m_comp(qs, c=None, recs=None):
        return np.array([len(set(recs(q) if recs else recomendar(q, c)) & objetivos[q]) / min(10, len(objetivos[q]))
                         for q in qs])

    def describir(c):
        return f"{c['fusion']} k={c['k']} compras={c['compras']} img={c['img']} c/i/t/cat={c['wc']}/{c['wi']}/{c['wt']}/{c['wcat']}"

    def etapa(nombre, opciones):
        filas = [(c, m_tipo(tipo_val, c).mean(), m_comp(comp_val, c).mean()) for c in opciones]
        bt, bc = max(f[1] for f in filas), max(f[2] for f in filas)
        print(f"\n{nombre} (validación)")
        for c, t, cm in filas:
            print(f"  {describir(c):70s} tipo {t:.3f}  comportamiento {cm:.3f}  puntaje {(t / bt + cm / bc) / 2:.3f}")
        return max(filas, key=lambda f: (f[1] / bt + f[2] / bc) / 2)[0]

    t0 = time.perf_counter()
    PR117 = dict(compras="hoy", img="mobilenet", fusion="max", k=51, wc=1, wi=0.25, wt=1, wcat=0.25)
    e1 = etapa("1. fusión y señal de compras", [dict(PR117, fusion=f, compras=v)
                                               for f in ("max", "rrf") for v in ("hoy", "filtrada")])
    e2 = etapa("2. candidatos por señal", [dict(e1, k=k) for k in (51, 101)])
    elegida = etapa("3. pesos", [dict(e2, wc=wc, wi=wi, wcat=wcat) for wc in (0, 0.25, 0.5, 1, 2)
                                 for wi in (0.25, 0.5) for wcat in (0, 0.25, 1)])

    # 4. Plataforma (con duplicados quitados). Se elige con las mismas dos métricas de antes;
    #    "misma plataforma" es solo un control: la señal y esa métrica usan la misma regex,
    #    así que elegir el peso con ella subiría el número por construcción.
    print("\n4. plataforma, sin duplicados (validación)")
    filas4 = []
    for wplat in (0, 0.25, 0.5, 1):
        c = dict(elegida, dedup=True, wplat=wplat)
        filas4.append((c, m_tipo(tipo_val, c).mean(), m_comp(comp_val, c).mean(),
                       m_plataforma(tipo_val + comp_val, c).mean()))
    mejores = [max(f[j] for f in filas4) for j in (1, 2)]
    for c, *ms in filas4:
        print(f"  plataforma {c['wplat']:<4} tipo {ms[0]:.3f}  comportamiento {ms[1]:.3f}  misma plataforma {ms[2]:.3f}"
              f"  puntaje {np.mean([m / b for m, b in zip(ms[:2], mejores)]):.3f}")
    final = max(filas4, key=lambda f: np.mean([m / b for m, b in zip(f[1:3], mejores)]))[0]

    RRF = dict(PR117, fusion="rrf", wi=0.5)
    finales = {"antes: texto + SIFT, pesos 1,1,1": dict(PR117, img="sift", wi=1, wcat=0),
               "#117: MobileNet 0.25 + categoría 0.25": PR117,
               "#117 + compras de usuarios con 2 a 20": dict(PR117, compras="usuarios"),
               "#117 + compras a 30 días": dict(PR117, compras="hoy_ventana"),
               "#117 + RRF con pesos 1/0.5/1/0.25": RRF,
               "RRF + usuarios 2 a 20 + 30 días, k=51": dict(RRF, compras="filtrada"),
               "elegida": elegida,
               "elegida + sin duplicados": dict(elegida, dedup=True),
               "elegida + solo plataforma": dict(elegida, wplat=final["wplat"]),
               "final: + sin duplicados + plataforma": final}
    bootstrap = np.random.default_rng(0)
    it = bootstrap.integers(0, len(tipo_prueba), (5000, len(tipo_prueba)))
    ic_ = bootstrap.integers(0, len(comp_prueba), (5000, len(comp_prueba)))

    def ic(x, idx):
        m = x[idx].mean(1)
        return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]

    res = {nm: (m_tipo(tipo_prueba, c), m_comp(comp_prueba, c)) for nm, c in finales.items()}
    extra = {nm: (m_plataforma(tipo_prueba + comp_prueba, c), duplicados(tipo_prueba + comp_prueba, c))
             for nm, c in finales.items()}
    ip = bootstrap.integers(0, len(extra["elegida"][0]), (5000, len(extra["elegida"][0])))
    ref_t, ref_c = res["#117: MobileNet 0.25 + categoría 0.25"]
    pop = lambda q: [p for p in populares if p != q][:10]  # noqa: E731
    salida = {"corte": str(np.datetime64(T, "s")), "cobertura": len(objetivos), "productos": n,
              "consultas": {"tipo": [len(tipo_val), len(tipo_prueba)], "comportamiento": [len(comp_val), len(comp_prueba)]},
              "mas_populares": {"tipo": float(m_tipo(tipo_prueba, recs=pop).mean()),
                                "comportamiento": float(m_comp(comp_prueba, recs=pop).mean())},
              "configuraciones": []}
    print(f"\nPRUEBA ({len(tipo_prueba)} consultas de tipo, {len(comp_prueba)} de comportamiento)")
    print(f"  más populares: tipo {salida['mas_populares']['tipo']:.3f}, comportamiento {salida['mas_populares']['comportamiento']:.3f}")
    for nm, (t, cm) in res.items():
        fila = {"nombre": nm, "config": finales[nm], "tipo": float(t.mean()), "tipo_ic": ic(t, it),
                "comportamiento": float(cm.mean()), "comportamiento_ic": ic(cm, ic_),
                "dif_117_tipo_ic": ic(t - ref_t, it), "dif_117_comportamiento_ic": ic(cm - ref_c, ic_),
                "misma_plataforma": float(extra[nm][0].mean()), "misma_plataforma_ic": ic(extra[nm][0], ip),
                "listas_con_duplicados": round(extra[nm][1], 4)}
        salida["configuraciones"].append(fila)
        print(f"  {nm:42s} tipo {fila['tipo']:.3f} {fila['tipo_ic']}  comportamiento {fila['comportamiento']:.3f} "
              f"{fila['comportamiento_ic']}  vs #117 {fila['dif_117_tipo_ic']} / {fila['dif_117_comportamiento_ic']}"
              f"  plataforma {fila['misma_plataforma']:.3f}  listas con duplicados {fila['listas_con_duplicados']:.1%}")
    json.dump(salida, open(SALIDA, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\n{SALIDA} ({time.perf_counter() - t0:.0f} s de evaluación)")


if __name__ == "__main__":
    main()
