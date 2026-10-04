"""Genera el SQL para cargar un CSV (CREATE TABLE sugerido + COPY).

No ejecuta nada: el botón "Cargar CSV..." escribe este SQL en el editor para
que el usuario lo revise (tipos, PK) antes de pulsar Ejecutar.
"""

import csv
import os
import re

from engine.query.lexer import KEYWORDS

FILAS_MUESTRA = 500
DELIMITADORES = ",;\t|"


def _leer_texto(path):
    """Devuelve (texto, encoding). Prueba UTF-8 y, si falla, Latin-1."""
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with open(path, encoding=encoding, newline="") as stream:
                return stream.read(), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("No se pudo leer el archivo como UTF-8 ni Latin-1")


def _identificador(texto, respaldo):
    nombre = re.sub(r"[^0-9a-zA-Z_]+", "_", texto.strip()).strip("_").lower() or respaldo
    if nombre[0].isdigit():
        nombre = "t_" + nombre
    if nombre.upper() in KEYWORDS:
        nombre += "_"
    return nombre


def _es_entero(valor):
    return re.fullmatch(r"[+-]?\d+", valor) is not None


def _es_flotante(valor):
    try:
        float(valor)
        return True
    except ValueError:
        return False


def _tipo(valores):
    valores = [v.strip() for v in valores if v.strip() != ""]
    if valores and all(_es_entero(v) for v in valores):
        return "INT"
    if valores and all(_es_flotante(v) for v in valores):
        return "FLOAT"
    largo = max((len(v) for v in valores), default=1)
    return f"VARCHAR({max(10, -(-largo // 10) * 10)})"


def _ruta_sql(path, base_dir):
    path = os.path.abspath(path)
    if base_dir:
        try:
            relativa = os.path.relpath(path, base_dir)
            if not relativa.startswith(".."):
                path = relativa
        except ValueError:  # otra unidad en Windows
            pass
    return path.replace("\\", "/").replace("'", "''")


def sql_para_csv(path, tablas_existentes=None, base_dir=None):
    """SQL para cargar `path`: COPY y, si la tabla no existe, un CREATE TABLE.

    tablas_existentes: nombres de las tablas ya registradas en el catálogo.
    """
    tablas_existentes = set(tablas_existentes or ())
    texto, encoding = _leer_texto(path)
    if not texto.strip():
        raise ValueError("El archivo está vacío")
    muestra = texto[:65536]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=DELIMITADORES)
        delimitador = dialecto.delimiter
    except csv.Error:
        delimitador = ","
    filas = list(csv.reader(texto.splitlines(), delimiter=delimitador))
    filas = [fila for fila in filas if any(celda.strip() for celda in fila)]
    try:
        encabezado = csv.Sniffer().has_header(muestra)
    except csv.Error:
        encabezado = True
    # Si la primera fila no tiene números pero las demás sí, es encabezado.
    if not encabezado and len(filas) > 1:
        encabezado = (not any(_es_flotante(c) for c in filas[0])
                      and any(_es_flotante(c) for c in filas[1]))

    ancho = max(len(fila) for fila in filas)
    datos = filas[1:] if encabezado else filas
    if encabezado:
        columnas = [_identificador(c, f"col{i + 1}") for i, c in enumerate(filas[0])]
        columnas += [f"col{i + 1}" for i in range(len(columnas), ancho)]
    else:
        columnas = [f"col{i + 1}" for i in range(ancho)]

    tabla = _identificador(os.path.splitext(os.path.basename(path))[0], "tabla_csv")
    opciones = ["FORMAT csv"]
    if encabezado:
        opciones.append("HEADER")
    if delimitador != ",":
        opciones.append("DELIMITER '" + ("\\t" if delimitador == "\t" else delimitador) + "'")
    if encoding == "latin-1":
        opciones.append("ENCODING 'latin-1'")

    lineas = [f"-- Archivo: {os.path.basename(path)} ({len(datos)} filas, {len(columnas)} columnas)"]
    if tabla in tablas_existentes:
        lineas.append(f"-- La tabla {tabla} ya existe: solo se cargan las filas.")
    else:
        muestra_datos = datos[:FILAS_MUESTRA]
        definiciones = []
        for i, columna in enumerate(columnas):
            valores = [fila[i] if i < len(fila) else "" for fila in muestra_datos]
            definiciones.append(f"{columna} {_tipo(valores)}")
        primera = [fila[0].strip() for fila in datos if fila]
        if (definiciones and definiciones[0].endswith(" INT") and primera
                and len(set(primera)) == len(primera)):
            definiciones[0] += " PRIMARY KEY"
        lineas.append("-- Revisa los tipos y la PRIMARY KEY antes de ejecutar.")
        lineas.append(f"CREATE TABLE {tabla} (" + ", ".join(definiciones) + ");")
    lineas.append(f"COPY {tabla} FROM '{_ruta_sql(path, base_dir)}' "
                  f"WITH ({', '.join(opciones)});")
    lineas.append(f"SELECT * FROM {tabla};")
    return "\n".join(lineas) + "\n"
