"""Pushdown de selección en JOIN y valores distintos con KMV."""
import random

import pytest

from engine.query.logical_plan import LogicalPlanner
from frontend.motor import Motor

CONSULTA = ("SELECT b.producto_id AS id, COUNT(*) AS n FROM compras a JOIN compras b ON a.usuario = b.usuario "
            "WHERE a.producto_id = 5 AND b.producto_id <> 5 GROUP BY b.producto_id ORDER BY id")


def _motor(tmp_path, filas=2000):
    motor = Motor(directorio=str(tmp_path), modo_demo=False)
    motor.ejecutar("CREATE TABLE compras (id INT PRIMARY KEY, usuario VARCHAR(20), producto_id INT)")
    valores = ", ".join(f"({i}, 'u{i % 300}', {i % 80})" for i in range(filas))
    motor.ejecutar(f"INSERT INTO compras VALUES {valores}")
    motor.ejecutar("CREATE INDEX compras_usuario ON compras (usuario) USING HASH")
    return motor


def _esperado(filas=2000):
    compras = [(f"u{i % 300}", i % 80) for i in range(filas)]
    usuarios = [u for u, p in compras if p == 5]
    cuenta = {}
    for u in usuarios:
        for v, p in compras:
            if v == u and p != 5:
                cuenta[p] = cuenta.get(p, 0) + 1
    return sorted(cuenta.items())


def test_pushdown_no_cambia_el_resultado(tmp_path):
    motor = _motor(tmp_path)
    r = motor.ejecutar(CONSULTA)
    assert not r.tiene_error, r.error
    assert r.filas == _esperado()
    motor.cerrar()


def test_pushdown_baja_el_filtro_y_usa_el_indice(tmp_path):
    motor = _motor(tmp_path)
    motor.ejecutar("CREATE INDEX compras_producto ON compras (producto_id) USING HASH")
    plan = "\n".join(str(f[0]) for f in motor.ejecutar("EXPLAIN " + CONSULTA).filas)
    # Antes: Seq Scan de toda la tabla a y el filtro recién después del join.
    assert "Index Cond: (a.producto_id = 5)" in plan, plan
    assert "rows=25)" in plan.split("compras a")[1].split("\n")[0], plan  # el join estima 25 filas, no 2000
    assert motor.ejecutar(CONSULTA).filas == _esperado()
    motor.cerrar()


def test_pushdown_no_baja_terminos_de_la_otra_tabla(tmp_path):
    motor = _motor(tmp_path)
    sql = CONSULTA.replace("a.producto_id = 5 AND", "a.producto_id = 5 AND b.producto_id < 40 AND")
    filas = motor.ejecutar(sql).filas
    assert filas == [(p, n) for p, n in _esperado() if p < 40]
    motor.cerrar()


# Mismas filas con y sin pushdown: filtros de una tabla, de las dos, OR entre tablas,
# NOT, BETWEEN, tres tablas, alias, sin alias y sin WHERE (el storage no admite NULL).
EQUIVALENCIA = [
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE a.x = 3 ORDER BY a.id, b.id",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE a.x = 3 AND b.y > 4 ORDER BY a.id, b.id",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE a.x = 3 OR b.y = 2 ORDER BY a.id, b.id",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE a.x > b.y ORDER BY a.id, b.id",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE a.x < 5 AND a.id > 100 AND b.y = a.x "
    "ORDER BY a.id, b.id",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE b.y = 7 ORDER BY a.id, b.id",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k WHERE (a.x = 1 OR a.x = 2) AND NOT b.y = 3 "
    "ORDER BY a.id, b.id",
    "SELECT a.id, b.id, c.id FROM t a JOIN u b ON a.k = b.k JOIN t c ON b.k = c.k "
    "WHERE a.x = 4 AND c.x <> 4 ORDER BY a.id, b.id, c.id",
    "SELECT t.id, u.id FROM t JOIN u ON t.k = u.k WHERE t.x = 2 ORDER BY t.id, u.id",
    "SELECT a.k, COUNT(*) FROM t a JOIN u b ON a.k = b.k WHERE a.x BETWEEN 2 AND 6 GROUP BY a.k ORDER BY a.k",
    "SELECT a.id, b.id FROM t a JOIN u b ON a.k = b.k ORDER BY a.id, b.id",
]


@pytest.fixture
def tablas(tmp_path):
    motor = Motor(directorio=str(tmp_path), modo_demo=False)
    motor.ejecutar("CREATE TABLE t (id INT PRIMARY KEY, k INT, x INT)")
    motor.ejecutar("CREATE TABLE u (id INT PRIMARY KEY, k INT, y INT)")
    rnd = random.Random(7)
    for tabla, filas in (("t", 400), ("u", 300)):
        valores = ", ".join(f"({i}, {rnd.randint(0, 30)}, {rnd.randint(0, 9)})" for i in range(filas))
        r = motor.ejecutar(f"INSERT INTO {tabla} VALUES {valores}")
        assert not r.tiene_error, r.error
    motor.ejecutar("CREATE INDEX t_x ON t (x) USING HASH")
    motor.ejecutar("CREATE INDEX u_k ON u (k) USING HASH")
    yield motor
    motor.cerrar()


@pytest.mark.parametrize("sql", EQUIVALENCIA)
def test_mismas_filas_con_y_sin_pushdown(tablas, sql, monkeypatch):
    con = tablas.ejecutar(sql)
    assert not con.tiene_error, con.error
    monkeypatch.setattr(LogicalPlanner, "_pushdown", staticmethod(lambda where, statement: None))
    sin = tablas.ejecutar(sql)
    assert not sin.tiene_error, sin.error
    assert con.filas == sin.filas
    assert con.filas  # la consulta devuelve filas: la comparación dice algo


def test_left_join_no_existe_en_el_parser(tablas):
    # El pushdown asume INNER JOIN; si se agrega LEFT/RIGHT, la guarda de _pushdown lo apaga.
    assert tablas.ejecutar("SELECT a.id FROM t a LEFT JOIN u b ON a.k = b.k WHERE a.x = 1").tiene_error


def test_distintos_kmv_exacto_y_estimado():
    from engine.query.catalog import DistintosKMV
    pocos = DistintosKMV()
    for i in range(3000):
        pocos.agregar(f"u{i % 700}")
    assert pocos.estimar() == 700  # menos de k distintos: exacto
    muchos = DistintosKMV()
    for i in range(200_000):
        muchos.agregar(i % 50_000)  # enteros consecutivos: el hash se mezcla antes
    assert abs(muchos.estimar() - 50_000) / 50_000 < 0.1


def test_estadisticas_con_mas_de_1024_distintos(tmp_path):
    motor = Motor(directorio=str(tmp_path), modo_demo=False)
    motor.ejecutar("CREATE TABLE c (id INT PRIMARY KEY, usuario VARCHAR(20))")
    for inicio in range(0, 6000, 1000):
        motor.ejecutar("INSERT INTO c VALUES " + ", ".join(f"({i}, 'u{i // 2}')" for i in range(inicio, inicio + 1000)))
    tabla = motor.catalog.table("c")
    tabla.analyze()
    assert abs(tabla.statistics.distinct_values["usuario"] - 3000) / 3000 < 0.1  # antes: 1024
    motor.cerrar()
