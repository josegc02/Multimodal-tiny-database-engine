"""Pushdown de selección en JOIN y fusión RRF de la tienda."""
import gzip
import json

from frontend.motor import Motor
from tienda.recomendaciones import fusionar

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


def test_rrf_no_depende_de_la_escala():
    # BM25 sin tope frente a cosenos juntos: con RRF solo cuenta la posición.
    senales = {"texto": {1: 900.0, 2: 3.0, 3: 2.0}, "imagen": {3: 0.91, 2: 0.90, 1: 0.10}}
    filas = fusionar(0, senales, {"texto": 1, "imagen": 1})
    assert [f["id"] for f in filas] == [1, 3, 2]
    maximo = fusionar(0, senales, {"texto": 1, "imagen": 1}, metodo="max")
    assert maximo[0]["id"] == 1 and maximo[0]["puntaje"] > 0.5


def test_rrf_empates_por_id_y_bono_de_categoria():
    senales = {"compras": {7: 1, 4: 1, 9: 2}, "categoria": {7: 1}}
    filas = fusionar(0, senales, {"compras": 1, "categoria": 0})
    assert [f["id"] for f in filas] == [9, 4, 7]  # empate 4 y 7: primero el id menor
    filas = fusionar(0, senales, {"compras": 1, "categoria": 0.25})
    assert [f["id"] for f in filas][:2] == [7, 9]  # el bono suma sin posición
    assert filas[1]["senales"]["categoria"] == 0


def test_compras_solo_usuarios_de_2_a_20(tmp_path):
    from tienda.amazon import compras
    resenas = tmp_path / "r.jsonl.gz"
    lineas = [{"user_id": "uno", "parent_asin": "A", "verified_purchase": True, "timestamp": 1000}]
    lineas += [{"user_id": "dos", "parent_asin": a, "verified_purchase": True, "timestamp": 2000} for a in "AB"]
    lineas += [{"user_id": "muchos", "parent_asin": f"P{i}", "verified_purchase": True, "timestamp": 3000}
               for i in range(21)]
    lineas += [{"user_id": "dos", "parent_asin": "C", "verified_purchase": False, "timestamp": 2000}]
    with gzip.open(resenas, "wt", encoding="utf-8") as f:
        f.writelines(json.dumps(x) + "\n" for x in lineas)
    productos = [{"asin": a, "id": i} for i, a in enumerate(["A", "B", "C"] + [f"P{i}" for i in range(21)], 1)]
    filas = compras(resenas, productos)
    assert {(f["usuario"], f["producto_id"]) for f in filas} == {("dos", 1), ("dos", 2)}
    assert all(f["fecha"] == 2 for f in filas)  # milisegundos -> segundos


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
