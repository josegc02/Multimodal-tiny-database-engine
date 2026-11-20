"""Planes, filas y tiempos de un conjunto de consultas del optimizador.

Uso, desde la raíz del repositorio::

    python -m benchmarks.bench_optimizador benchmarks/results/optimizador.json

Para comparar dos versiones del motor, se corre en cada una y se comparan los JSON
(plan, cantidad de filas, hash de las filas y el menor de 3 tiempos).
Tablas con columnas de pocos y de muchos valores distintos (más de 1024), índices hash
y B+; consultas de igualdad, rango, ORDER BY, GROUP BY y JOIN.
"""
import json
import random
import sys
import tempfile
import time

from frontend.motor import Motor

m = Motor(directorio=tempfile.mkdtemp(), modo_demo=False)
rnd = random.Random(3)
m.ejecutar("CREATE TABLE clientes (id INT PRIMARY KEY, ciudad VARCHAR(20), correo VARCHAR(40), edad INT)")
m.ejecutar("CREATE TABLE pedidos (id INT PRIMARY KEY, cliente INT, producto INT, monto FLOAT, dia INT)")
for inicio in range(0, 20000, 2000):
    m.ejecutar("INSERT INTO clientes VALUES " + ", ".join(
        f"({i}, 'c{rnd.randint(0, 40)}', 'u{i}@x', {rnd.randint(18, 80)})" for i in range(inicio, inicio + 2000)))
for inicio in range(0, 60000, 3000):
    m.ejecutar("INSERT INTO pedidos VALUES " + ", ".join(
        f"({i}, {rnd.randint(0, 19999)}, {rnd.randint(0, 5000)}, {rnd.random() * 100:.2f}, {rnd.randint(0, 3650)})"
        for i in range(inicio, inicio + 3000)))
for sql in ("CREATE INDEX cl_ciudad ON clientes (ciudad) USING HASH",
            "CREATE INDEX cl_correo ON clientes (correo) USING HASH",
            "CREATE INDEX cl_edad ON clientes (edad) USING BTREE",
            "CREATE INDEX pe_cliente ON pedidos (cliente) USING HASH",
            "CREATE INDEX pe_producto ON pedidos (producto) USING HASH",
            "CREATE INDEX pe_dia ON pedidos (dia) USING BTREE"):
    r = m.ejecutar(sql)
    assert not r.tiene_error, r.error
for t in ("clientes", "pedidos"):
    m.catalog.table(t).analyze()

CONSULTAS = [
    "SELECT * FROM clientes WHERE correo = 'u777@x'",
    "SELECT * FROM clientes WHERE ciudad = 'c7'",
    "SELECT * FROM pedidos WHERE producto = 1234",
    "SELECT * FROM pedidos WHERE cliente = 42",
    "SELECT * FROM pedidos WHERE dia BETWEEN 100 AND 110",
    "SELECT * FROM pedidos WHERE dia BETWEEN 100 AND 2000",
    "SELECT id FROM pedidos ORDER BY dia LIMIT 10",
    "SELECT producto, COUNT(*) FROM pedidos GROUP BY producto ORDER BY producto LIMIT 5",
    "SELECT ciudad, COUNT(*) FROM clientes GROUP BY ciudad ORDER BY ciudad",
    "SELECT c.id, p.id FROM clientes c JOIN pedidos p ON c.id = p.cliente WHERE c.correo = 'u77@x' ORDER BY p.id",
    "SELECT c.id, p.id FROM clientes c JOIN pedidos p ON c.id = p.cliente WHERE c.ciudad = 'c3' AND p.monto > 90 ORDER BY p.id",
    "SELECT p.id, c.id FROM pedidos p JOIN clientes c ON p.cliente = c.id WHERE p.producto = 99 ORDER BY p.id",
    "SELECT p.id, c.id FROM pedidos p JOIN clientes c ON p.cliente = c.id WHERE p.dia BETWEEN 10 AND 12 ORDER BY p.id",
    "SELECT c.ciudad, COUNT(*) FROM clientes c JOIN pedidos p ON c.id = p.cliente WHERE c.edad < 20 GROUP BY c.ciudad ORDER BY c.ciudad",
    "SELECT a.id, b.id FROM pedidos a JOIN pedidos b ON a.cliente = b.cliente WHERE a.producto = 7 AND b.producto <> 7 ORDER BY a.id, b.id",
]
salida = []
for sql in CONSULTAS:
    plan = [str(f[0]) for f in m.ejecutar("EXPLAIN " + sql).filas]
    tiempos = []
    for _ in range(3):
        t = time.perf_counter()
        r = m.ejecutar(sql)
        tiempos.append(time.perf_counter() - t)
        assert not r.tiene_error, (sql, r.error)
    salida.append({"sql": sql, "plan": plan, "filas": len(r.filas), "hash_filas": hash(tuple(map(tuple, r.filas))),
                   "ms": round(min(tiempos) * 1000, 1)})
    print(f"{min(tiempos) * 1000:9.1f} ms  {len(r.filas):6d} filas  {sql[:90]}", flush=True)
json.dump(salida, open(sys.argv[1], "w"), indent=1)
m.cerrar()
