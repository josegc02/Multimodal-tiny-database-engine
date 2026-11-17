"""Construcción y carga del corpus de papers en el motor (issue #97).

``construir`` lee ``datasets/papers/seleccion.csv`` + los PDFs descargados
(y, opcionalmente, el material del curso en ``datasets/papers/curso/``),
extrae el texto por página, lo fragmenta y escribe en
``datasets/papers/generated/``:

- ``papers.csv`` y ``fragmentos.csv`` (UTF-8, con cabecera, listos para COPY);
- ``cargar_motor.sql``: CREATE TABLE + COPY + índice SPIMI en inglés;
- ``metadata.json``: parámetros, conteos y SHA-256 de los CSV.

``cargar`` ejecuta ese SQL sobre un motor persistente (por defecto
``data/app``, la carpeta de la API) sin abrir la GUI.

Uso::

    python -m rag.corpus construir
    python -m rag.corpus cargar --datos data/app
"""

import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

from rag.arxiv import DATASET_DIR, PDF_DIR, ROOT, SELECCION, leer_seleccion, nombre_pdf
from rag.chunking import MAXIMO, MINIMO, OBJETIVO, extraer_paginas, fragmentar, quitar_referencias

SALIDA = DATASET_DIR / "generated"
CURSO_DIR = DATASET_DIR / "curso"
CAMPOS_PAPERS = ("id", "arxiv_id", "titulo", "autores", "anio", "abstract", "categoria",
                 "fuente", "url", "licencia", "tema")
CAMPOS_FRAGMENTOS = ("id", "paper_id", "orden", "pagina", "pagina_fin", "palabras", "texto")
CAMPOS_CURSO = ("archivo", "titulo", "autores", "anio", "categoria", "licencia")
VERSION = 1


def literal(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def ruta_sql(path):
    """Relativa a la raíz del repo si se puede (COPY resuelve contra ella); si no, absoluta."""
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_sql(papers_csv, fragmentos_csv, papers="papers", fragmentos="fragmentos"):
    return (
        f"CREATE TABLE {papers} (id INT PRIMARY KEY, arxiv_id TEXT, titulo TEXT, autores TEXT, "
        "anio INT, abstract TEXT, categoria TEXT, fuente TEXT, url TEXT, licencia TEXT, tema TEXT);\n"
        f"CREATE TABLE {fragmentos} (id INT PRIMARY KEY, paper_id INT REFERENCES {papers}(id), "
        "orden INT, pagina INT, pagina_fin INT, palabras INT, texto TEXT);\n"
        f"COPY {papers} FROM {literal(ruta_sql(papers_csv))} WITH (FORMAT CSV, HEADER TRUE);\n"
        f"COPY {fragmentos} FROM {literal(ruta_sql(fragmentos_csv))} WITH (FORMAT CSV, HEADER TRUE);\n"
        f"CREATE INDEX {fragmentos}_texto ON {fragmentos} (texto) USING SPIMI WITH (LANGUAGE = 'en');\n"
    )


def leer_curso(curso_dir):
    """Material del curso: PDFs locales descritos en curso.csv (opcional)."""
    manifiesto = Path(curso_dir) / "curso.csv"
    if not manifiesto.is_file():
        return []
    with manifiesto.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CAMPOS_CURSO:
            raise ValueError(f"Cabecera incorrecta en {manifiesto}; se esperaba {CAMPOS_CURSO}")
        filas = list(reader)
    for fila in filas:
        if not fila["anio"].strip().isdigit():
            raise ValueError(f"{manifiesto}: año inválido para {fila['archivo']!r}")
    return filas


def fuentes(seleccion, pdf_dir, curso_dir):
    """(fila_papers_sin_id, ruta_pdf) en orden estable: arXiv primero, luego curso."""
    for fila in seleccion:
        yield ({"arxiv_id": fila["arxiv_id"], "titulo": fila["titulo"], "autores": fila["autores"],
                "anio": fila["anio"], "abstract": fila["abstract"], "categoria": fila["categoria"],
                "fuente": "arxiv", "url": f"https://arxiv.org/abs/{fila['arxiv_id']}{fila['version']}",
                "licencia": fila["licencia"], "tema": fila["tema"]},
               Path(pdf_dir) / nombre_pdf(fila["arxiv_id"]))
    for fila in leer_curso(curso_dir):
        yield ({"arxiv_id": "", "titulo": fila["titulo"], "autores": fila["autores"],
                "anio": fila["anio"].strip(), "abstract": "", "categoria": fila["categoria"],
                "fuente": "curso", "url": "", "licencia": fila["licencia"], "tema": "curso"},
               Path(curso_dir) / fila["archivo"])


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def construir(seleccion=SELECCION, pdf_dir=PDF_DIR, curso_dir=CURSO_DIR, salida=SALIDA,
              minimo=MINIMO, objetivo=OBJETIVO, maximo=MAXIMO, con_referencias=False,
              extraer=extraer_paginas, log=print):
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=False)  # directorio nuevo: no mezclar corridas
    papers_csv, fragmentos_csv = salida / "papers.csv", salida / "fragmentos.csv"
    faltantes, sin_texto, palabras = [], [], []
    paper_id = fragmento_id = 0
    with papers_csv.open("w", encoding="utf-8", newline="") as p_stream, \
            fragmentos_csv.open("w", encoding="utf-8", newline="") as f_stream:
        p_writer = csv.DictWriter(p_stream, fieldnames=CAMPOS_PAPERS)
        f_writer = csv.DictWriter(f_stream, fieldnames=CAMPOS_FRAGMENTOS)
        p_writer.writeheader()
        f_writer.writeheader()
        for paper, pdf in fuentes(leer_seleccion(seleccion), pdf_dir, curso_dir):
            nombre = paper["arxiv_id"] or pdf.name
            if not pdf.is_file():
                faltantes.append(nombre)
                log(f"Aviso: falta el PDF de {nombre} ({pdf})")
                continue
            try:
                paginas = extraer(pdf)
            except Exception as exc:  # PDF corrupto o cifrado
                sin_texto.append(nombre)
                log(f"Aviso: no se pudo leer {nombre}: {exc}")
                continue
            if not con_referencias:
                paginas = quitar_referencias(paginas)
            fragmentos = fragmentar(paginas, minimo, objetivo, maximo)
            if not fragmentos:
                sin_texto.append(nombre)
                log(f"Aviso: {nombre} no tiene texto extraíble (¿PDF escaneado?)")
                continue
            paper_id += 1
            p_writer.writerow({"id": paper_id, **paper})
            for fragmento in fragmentos:
                fragmento_id += 1
                f_writer.writerow({"id": fragmento_id, "paper_id": paper_id, **fragmento})
                palabras.append(fragmento["palabras"])
            if paper_id % 25 == 0:
                log(f"{paper_id} papers, {fragmento_id} fragmentos")
    if not paper_id:
        raise ValueError("No se extrajo ningún paper: ¿se ejecutó 'python -m rag.arxiv descargar'?")
    (salida / "cargar_motor.sql").write_text(load_sql(papers_csv, fragmentos_csv), encoding="utf-8")
    metadata = {
        "version": VERSION,
        "seleccion_sha256": digest(seleccion),
        "parametros": {"minimo": minimo, "objetivo": objetivo, "maximo": maximo,
                       "sin_referencias": not con_referencias, "extractor": "pypdf"},
        "papers": paper_id,
        "fragmentos": fragmento_id,
        "palabras": {"min": min(palabras), "max": max(palabras),
                     "media": round(statistics.mean(palabras), 1), "mediana": statistics.median(palabras),
                     "bajo_minimo": sum(1 for n in palabras if n < minimo)},
        "pdf_faltantes": faltantes,
        "sin_texto": sin_texto,
        "archivos": {path.name: digest(path) for path in (papers_csv, fragmentos_csv)},
    }
    (salida / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return metadata


def cargar(salida=SALIDA, datos=ROOT / "data" / "app"):
    """Ejecuta cargar_motor.sql sobre un motor persistente (el que usa la API)."""
    from frontend.motor import Motor

    sql = (Path(salida) / "cargar_motor.sql").read_text(encoding="utf-8")
    motor = Motor(directorio=str(datos), modo_demo=False)
    try:
        if "papers" in motor.catalog.tables or "fragmentos" in motor.catalog.tables:
            raise ValueError(f"{datos} ya tiene las tablas papers/fragmentos; use otra carpeta")
        resultado = motor.ejecutar(sql)
        if resultado.tiene_error:
            raise ValueError(resultado.error)
        conteo = motor.ejecutar("SELECT COUNT(*) FROM fragmentos")
        return {"datos": str(Path(datos).resolve()), "fragmentos": conteo.filas[0][0]}
    finally:
        motor.cerrar()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Corpus de papers para RAG (issue #97)")
    sub = parser.add_subparsers(dest="comando", required=True)
    con = sub.add_parser("construir", help="PDF -> fragmentos -> CSV + SQL")
    con.add_argument("--seleccion", type=Path, default=SELECCION)
    con.add_argument("--pdf", type=Path, default=PDF_DIR)
    con.add_argument("--curso", type=Path, default=CURSO_DIR)
    con.add_argument("--salida", type=Path, default=SALIDA)
    con.add_argument("--minimo", type=int, default=MINIMO)
    con.add_argument("--objetivo", type=int, default=OBJETIVO)
    con.add_argument("--maximo", type=int, default=MAXIMO)
    con.add_argument("--con-referencias", action="store_true", help="no recortar la bibliografía")
    car = sub.add_parser("cargar", help="ejecuta cargar_motor.sql en un motor persistente")
    car.add_argument("--salida", type=Path, default=SALIDA)
    car.add_argument("--datos", type=Path, default=ROOT / "data" / "app")
    args = parser.parse_args(argv)
    try:
        if args.comando == "construir":
            resultado = construir(args.seleccion, args.pdf, args.curso, args.salida, args.minimo,
                                  args.objetivo, args.maximo, args.con_referencias)
        else:
            resultado = cargar(args.salida, args.datos)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())