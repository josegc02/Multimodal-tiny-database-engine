"""Gráficos del informe para la Parte 5 (y el cierre de la Parte 4).

Uso, desde la raíz::

    python -m benchmarks.graficos_parte5

Lee los resultados ya medidos (benchmarks/tienda/*.json, benchmarks/asistente/README.md,
docs/sql_parser.md, benchmarks/results/multimedia) y escribe PNG en
benchmarks/results/parte5/ (y una copia en docs/overleaf/images/ si existe).
Paleta validada para daltonismo: azul = la app / lo nuevo, naranja oscuro = la
alternativa, gris = el antes o la referencia (siempre rotulado).
"""
import json
import re
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "benchmarks" / "results" / "parte5"
OVERLEAF = RAIZ / "docs" / "overleaf" / "images"
AZUL, NARANJA, GRIS = "#1f77b4", "#d95f02", "#8c8c8c"
TINTA, TINTA2 = "#1a1a1a", "#555555"

plt.rcParams.update({
    "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10, "axes.edgecolor": "#bbbbbb",
    "axes.labelcolor": TINTA2, "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.8,
    "axes.axisbelow": True, "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight",
})


def guardar(fig, nombre):
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / nombre
    fig.savefig(ruta, dpi=200)
    plt.close(fig)
    if OVERLEAF.exists():
        shutil.copy(ruta, OVERLEAF / nombre)
    print(ruta.relative_to(RAIZ))


def etiquetar(ax, barras, formato="{:.1f}", dentro=False):
    for b in barras:
        valor = b.get_width() if b.get_width() > b.get_height() and b.get_y() != 0 else b.get_height()
        horizontal = getattr(b, "_horizontal", False)
        if horizontal:
            ax.annotate(formato.format(b.get_width()), (b.get_width(), b.get_y() + b.get_height() / 2),
                        xytext=(3, 0), textcoords="offset points", va="center", fontsize=8.5, color=TINTA)
        else:
            ax.annotate(formato.format(valor), (b.get_x() + b.get_width() / 2, b.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8.5, color=TINTA)


# 1. Asistente: precisión de las fuentes por versión y BM25 contra TF-IDF ------------------
def asistente():
    texto = (RAIZ / "benchmarks" / "asistente" / "README.md").read_text(encoding="utf-8")
    versiones = [("Inicio", 0.767, 0.644), ("5 palabras en inglés,\numbral 60 %", 0.919, None),
                 ("+ cognados,\numbral 70 %", 0.962, 0.875)]
    assert "0.767" in texto and "0.962" in texto and "0.875" in texto
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [1.15, 1]})
    x = range(len(versiones))
    con = a.bar([i - 0.19 for i in x], [v[1] for v in versiones], 0.36, color=AZUL, label="Con LLM (Gemini)")
    sin_x = [i + 0.19 for i, v in zip(x, versiones) if v[2] is not None]
    sin = a.bar(sin_x, [v[2] for v in versiones if v[2] is not None], 0.36, color=GRIS, label="Sin LLM")
    etiquetar(a, con, "{:.3f}")
    etiquetar(a, sin, "{:.3f}")
    a.set_xticks(list(x), [v[0] for v in versiones])
    a.set_ylim(0, 1.2)
    a.set_ylabel("Precisión de las fuentes")
    a.set_title("Asistente: precisión por versión", loc="left")
    a.legend(loc="upper left", ncol=2)
    umbrales = ["Sin umbral", "60 %", "70 %"]
    bm25, tfidf = [0.878, 0.919, 0.949], [0.844, 0.852, 0.886]
    assert all(f"{v:.3f}" in texto for v in bm25 + tfidf)
    xs = range(3)
    b1 = b.bar([i - 0.19 for i in xs], bm25, 0.36, color=AZUL, label="BM25")
    b2 = b.bar([i + 0.19 for i in xs], tfidf, 0.36, color=NARANJA, label="TF-IDF (coseno)")
    etiquetar(b, b1, "{:.3f}")
    etiquetar(b, b2, "{:.3f}")
    b.set_xticks(list(xs), umbrales)
    b.set_ylim(0.7, 1.0)
    b.set_xlabel("Umbral relativo al mejor fragmento")
    b.set_title("BM25 contra TF-IDF (mismas palabras clave)", loc="left")
    b.legend(loc="upper left", ncol=2)
    guardar(fig, "asistente_precision.png")


# 2 y 3. Tienda: las dos métricas y la ablación -------------------------------------------
def tienda():
    datos = json.load(open(RAIZ / "benchmarks" / "tienda" / "resultados.json", encoding="utf-8"))
    filas = {f["nombre"]: f for f in datos["configuraciones"]}
    elegidas = [("Antes\n(texto + SIFT)", "antes: texto + SIFT, pesos 1,1,1", GRIS),
                ("#117 inicial\n(MobileNet)", "#117: MobileNet 0.25 + categoría 0.25", NARANJA),
                ("La app", "app: RRF 1/0.5/1, categoría 0.25, consola 0.5, sin duplicados", AZUL)]
    fig, ejes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, clave, titulo, base in ((ejes[0], "tipo", "Mismo tipo de producto (P@10)", datos["mas_populares"]["tipo"]),
                                    (ejes[1], "comportamiento", "Compró después (recall@10)",
                                     datos["mas_populares"]["comportamiento"])):
        valores = [filas[n][clave] * 100 for _, n, _ in elegidas]
        ic = [filas[n][f"{clave}_ic"] for _, n, _ in elegidas]
        errores = [[v - lo * 100 for v, (lo, _) in zip(valores, ic)], [hi * 100 - v for v, (_, hi) in zip(valores, ic)]]
        barras = ax.bar(range(3), valores, 0.6, color=[c for *_, c in elegidas], yerr=errores, capsize=4,
                        error_kw={"elinewidth": 1, "ecolor": TINTA2})
        for b, v in zip(barras, valores):
            ax.annotate(f"{v:.1f} %", (b.get_x() + b.get_width() / 2, v), xytext=(10, 4), textcoords="offset points",
                        fontsize=8.5, color=TINTA)
        ax.axhline(base * 100, color=TINTA2, linewidth=1, linestyle=(0, (4, 3)))
        ax.annotate(f"Recomendar los más populares: {base * 100:.1f} %", (-0.38, base * 100), xytext=(0, 3),
                    textcoords="offset points", ha="left", fontsize=8, color=TINTA2)
        ax.set_xticks(range(3), [e for e, *_ in elegidas])
        ax.set_ylabel("%")
        ax.set_title(titulo, loc="left")
    fig.text(0.01, -0.04, f"{datos['consultas']['tipo'][1]} y {datos['consultas']['comportamiento'][1]} consultas de prueba; "
             "barras de error: IC 95 % por bootstrap.", fontsize=8, color=TINTA2)
    guardar(fig, "tienda_metricas.png")

    cambios = [("Solo compras de usuarios con 2 a 20", "#117 + compras de usuarios con 2 a 20"),
               ("Solo compras a 30 días", "#117 + compras a 30 días"),
               ("Solo RRF con pesos 1/0.5/1", "#117 + RRF con pesos 1/0.5/1/0.25"),
               ("RRF + compras filtradas", "RRF + usuarios 2 a 20 + 30 días, k=51"),
               ("La app (todo)", "app: RRF 1/0.5/1, categoría 0.25, consola 0.5, sin duplicados")]
    ref = filas["#117: MobileNet 0.25 + categoría 0.25"]
    fig, ejes = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True)
    for ax, clave, titulo in ((ejes[0], "tipo", "Mismo tipo (puntos)"), (ejes[1], "comportamiento", "Compró después (puntos)")):
        difs = [(filas[n][clave] - ref[clave]) * 100 for _, n in cambios]
        ics = [filas[n][f"dif_117_{clave}_ic"] for _, n in cambios]
        err = [[d - lo * 100 for d, (lo, _) in zip(difs, ics)], [hi * 100 - d for d, (_, hi) in zip(difs, ics)]]
        colores = [AZUL if lo > 0 else GRIS for lo, _ in ics]
        ax.barh(range(len(cambios)), difs, 0.6, color=colores, xerr=err, capsize=3, error_kw={"elinewidth": 1, "ecolor": TINTA2})
        ax.axvline(0, color=TINTA2, linewidth=1)
        for i, d in enumerate(difs):
            ax.annotate(f"{d:+.1f}", (max(d, 0), i), xytext=(4, -9), textcoords="offset points", fontsize=8.5, color=TINTA)
        ax.set_title(titulo, loc="left")
    ejes[0].invert_yaxis()  # el eje y es compartido: invertirlo una sola vez
    ejes[0].set_yticks(range(len(cambios)), [c for c, _ in cambios])
    fig.text(0.01, -0.05, "Diferencia con #117 inicial en prueba. Azul: el IC 95 % no toca el cero; gris: no significativo.",
             fontsize=8, color=TINTA2)
    guardar(fig, "tienda_ablacion.png")


# 4. Búsqueda en español --------------------------------------------------------------
def busqueda():
    datos = json.load(open(RAIZ / "benchmarks" / "tienda" / "busqueda_es.json", encoding="utf-8"))
    filas = datos["busquedas"]
    fig, ax = plt.subplots(figsize=(8, 6.2))
    y = range(len(filas))
    ax.barh([i + 0.2 for i in y], [f[1] for f in filas], 0.38, color=GRIS, label=f"Tal cual ({datos['p10']['tal cual'] * 100:.0f} %)")
    ax.barh([i - 0.2 for i in y], [f[2] for f in filas], 0.38, color=AZUL, label=f"Ampliada al inglés ({datos['p10']['ampliada'] * 100:.0f} %)")
    for i, f in enumerate(filas):  # un cero no dibuja barra: se rotula para que no parezca un dato faltante
        for valor, dy in ((f[1], 0.2), (f[2], -0.2)):
            if valor == 0:
                ax.annotate("0", (0, i + dy), xytext=(3, 0), textcoords="offset points", va="center", fontsize=7.5, color=TINTA2)
    ax.set_yticks(list(y), [f[0] for f in filas])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("Fracción de los 10 primeros resultados del tipo pedido")
    ax.set_title("Búsqueda en español sobre descripciones en inglés", loc="left")
    ax.legend(loc="lower right")
    guardar(fig, "tienda_busqueda_es.png")


# 5 y 6. HNSW frente a búsqueda exacta --------------------------------------------------
def hnsw():
    escala = json.load(open(RAIZ / "benchmarks" / "tienda" / "hnsw_escala.json", encoding="utf-8"))["filas"]
    filas = [f for f in escala if f["k"] == 102]
    n = [f["n"] / 1000 for f in filas]
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.6))
    a.plot(n, [f["ms_hnsw"] for f in filas], "-o", color=AZUL, linewidth=2, markersize=6, label="HNSW del motor (Python)")
    a.plot(n, [f["ms_exacta_numpy"] for f in filas], "-s", color=NARANJA, linewidth=2, markersize=6, label="Exacta vectorizada (numpy)")
    a.plot(n, [f["ms_exacta_fila_por_fila"] for f in filas], "--^", color=GRIS, linewidth=2, markersize=6, label="Exacta fila por fila")
    a.set_xlabel("Productos (miles)")
    a.set_ylabel("ms por consulta (k = 102)")
    a.set_title("Latencia según el tamaño del catálogo", loc="left")
    a.legend(loc="center right")
    a.set_xticks(n)
    b.plot(n, [f["recall"] for f in filas], "-o", color=AZUL, linewidth=2, markersize=6)
    for x, f in zip(n, filas):
        b.annotate(f"{f['recall']:.3f}\n{f['visitados_pct'] * 100:.1f} % visitado", (x, f["recall"]), xytext=(0, 8),
                   textcoords="offset points", ha="center", fontsize=8, color=TINTA)
    b.set_ylim(0.85, 0.97)
    b.set_xticks(n)
    b.set_xlabel("Productos (miles)")
    b.set_ylabel("Recall@102 frente a la exacta")
    b.set_title("Recall del HNSW (M = 8, ef_search = 102)", loc="left")
    guardar(fig, "tienda_hnsw_escala.png")

    datos = json.load(open(RAIZ / "benchmarks" / "tienda" / "hnsw.json", encoding="utf-8"))["filas"]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    for vector, color, nombre in (("mobilenet", AZUL, "MobileNet (1280 dim.)"), ("sift_bovw", NARANJA, "SIFT + BoVW (1024 dim.)")):
        puntos = sorted((f["ms_hnsw"], f["recall"]) for f in datos if f["vector"] == vector and f["M"] == 8 and f["k"] == 10)
        ax.plot([p[0] for p in puntos], [p[1] for p in puntos], "-o", color=color, linewidth=2, markersize=6, label=nombre)
    ax.set_xlabel("ms por consulta (ef_search = 10, 50, 100, 200)")
    ax.set_ylabel("Recall@10")
    ax.set_title("Recall contra latencia al subir ef_search (M = 8)", loc="left")
    ax.legend(loc="lower right")
    guardar(fig, "tienda_hnsw_ef.png")


# 7. Optimizador: JOIN antes y después ---------------------------------------------------
def optimizador():
    texto = (RAIZ / "docs" / "sql_parser.md").read_text(encoding="utf-8")
    filas = re.findall(r"^\| `(SELECT [^`]*JOIN[^`]*)` \| ([\d,\.]+) \| ([\d,\.]+) \|$", texto, re.M)
    etiquetas = ["Cliente por correo", "Clientes de una ciudad", "Pedidos de un producto", "Pedidos en 3 días",
                 "Ciudades de clientes jóvenes", "También compraron (self-JOIN)"]
    assert len(filas) == len(etiquetas), len(filas)
    antes = [float(a.replace(",", "")) for _, a, _ in filas]
    despues = [float(d.replace(",", "")) for _, _, d in filas]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = range(len(filas))
    ax.barh([i + 0.2 for i in y], antes, 0.38, color=GRIS, label="Antes")
    ax.barh([i - 0.2 for i in y], despues, 0.38, color=AZUL, label="Pushdown + KMV")
    ax.set_xscale("log")
    for i, (a, d) in enumerate(zip(antes, despues)):
        ax.annotate(f"{a:,.0f} ms", (a, i + 0.2), xytext=(3, 0), textcoords="offset points", va="center", fontsize=8, color=TINTA2)
        ax.annotate(f"{d:,.1f} ms", (d, i - 0.2), xytext=(3, 0), textcoords="offset points", va="center", fontsize=8, color=TINTA)
    ax.set_yticks(list(y), etiquetas)
    ax.invert_yaxis()
    ax.set_xlabel("ms (escala logarítmica)")
    ax.set_title("Consultas con JOIN antes y después del optimizador", loc="left")
    ax.set_xlim(right=2e5)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    guardar(fig, "optimizador_join.png")


# 8. Parte 4 → 5: extractores sobre COCO 1K ---------------------------------------------
def extractores():
    datos = [("Azar", 4.0, GRIS), ("SIFT + BoVW\n(Parte 4)", 6.3, NARANJA), ("MobileNetV2", 33.2, AZUL),
             ("MobileNet,\nprob. de clase", 35.6, AZUL), ("CLIP ViT-B/32", 37.8, AZUL)]
    fig, ax = plt.subplots(figsize=(7, 3.4))
    barras = ax.bar(range(len(datos)), [d[1] for d in datos], 0.6, color=[d[2] for d in datos])
    for b, (_, v, _) in zip(barras, datos):
        ax.annotate(f"{v:.1f} %", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8.5, color=TINTA)
    ax.set_xticks(range(len(datos)), [d[0] for d in datos])
    ax.set_ylabel("P@10 de la misma categoría (%)")
    ax.set_title("COCO 1K: vecinos de la misma categoría según el extractor", loc="left")
    guardar(fig, "coco_extractores.png")


if __name__ == "__main__":
    asistente()
    tienda()
    busqueda()
    hnsw()
    optimizador()
    extractores()
