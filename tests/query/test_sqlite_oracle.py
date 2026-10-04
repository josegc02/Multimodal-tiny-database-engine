"""Prueba diferencial: el motor debe devolver lo mismo que SQLite.

Se cargan los mismos datos en el motor (heap con índices hash y B+,
archivo secuencial y tabla B+ agrupada) y en SQLite en memoria, y se
comparan los resultados de consultas con filtros, expresiones, ORDER BY,
LIMIT/OFFSET, GROUP BY/HAVING, DISTINCT, agregados DISTINCT y JOIN.
"""

import os
import random
import sqlite3
import tempfile
import unittest

from engine.indexes import ExtendibleHash
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.query.catalog import Catalog
from engine.query.planner import IndexInfo
from engine.query.sql_executor import SQLExecutor
from engine.storage.clustered_file import ClusteredBPlusFile
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile

EMP = [("id", "int"), ("nombre", "str", 12), ("depto", "int"), ("salario", "float"), ("edad", "int")]
DEP = [("did", "int"), ("dnombre", "str", 12), ("piso", "int")]

QUERIES = [
    "SELECT * FROM emp WHERE id = 17",
    "SELECT id, nombre FROM emp WHERE depto = 3 AND edad > 40",
    "SELECT id FROM emp WHERE depto = 1 OR depto = 2",
    "SELECT id FROM emp WHERE NOT (depto = 1 OR edad < 30)",
    "SELECT id FROM emp WHERE (depto = 1 OR depto = 2) AND (edad BETWEEN 30 AND 40)",
    "SELECT id FROM emp WHERE edad NOT BETWEEN 20 AND 60",
    "SELECT id FROM emp WHERE depto IN (0, 4)",
    "SELECT id FROM emp WHERE depto NOT IN (0, 1, 2)",
    "SELECT id FROM emp WHERE nombre LIKE 'ana%'",
    "SELECT id FROM emp WHERE nombre LIKE '%3'",
    "SELECT id FROM emp WHERE nombre LIKE '_ob%'",
    "SELECT id FROM emp WHERE nombre NOT LIKE '%a%'",
    "SELECT id FROM emp WHERE salario > 500.5 AND salario <= 700",
    "SELECT id FROM emp WHERE salario BETWEEN 200 AND 210",
    "SELECT id FROM emp WHERE id >= 290",
    "SELECT id FROM emp WHERE 10 > id",
    "SELECT id FROM emp WHERE id > -5 AND id < 3",
    "SELECT id, edad + 1 AS e1, salario * 2 AS s2 FROM emp WHERE id < 5",
    "SELECT id, edad - depto * 2 AS x FROM emp WHERE id < 10",
    "SELECT id FROM emp WHERE edad + depto > 60",
    "SELECT id, nombre FROM emp ORDER BY nombre, id DESC LIMIT 15",
    "SELECT id FROM emp ORDER BY salario DESC LIMIT 5",
    "SELECT id FROM emp ORDER BY edad ASC, salario DESC LIMIT 10 OFFSET 5",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY 1 DESC LIMIT 3",
    "SELECT id AS k FROM emp ORDER BY k DESC LIMIT 3",
    "SELECT COUNT(*) AS n FROM emp",
    "SELECT COUNT(*) AS n FROM emp WHERE edad > 100",
    "SELECT SUM(edad) AS s, MIN(salario) AS mn, MAX(salario) AS mx FROM emp",
    "SELECT AVG(edad) AS a FROM emp",
    "SELECT depto, COUNT(*) AS n FROM emp GROUP BY depto",
    "SELECT depto, COUNT(*) AS n, AVG(salario) AS a FROM emp GROUP BY depto ORDER BY depto",
    "SELECT depto, COUNT(*) AS n FROM emp GROUP BY depto HAVING COUNT(*) > 50",
    "SELECT depto, MAX(edad) AS m FROM emp WHERE edad < 50 GROUP BY depto HAVING MAX(edad) >= 45 ORDER BY m DESC",
    "SELECT depto, edad, COUNT(*) AS n FROM emp GROUP BY depto, edad ORDER BY depto, edad LIMIT 10",
    "SELECT depto, SUM(salario) AS s FROM emp GROUP BY depto ORDER BY s DESC LIMIT 2",
    "SELECT DISTINCT depto FROM emp",
    "SELECT DISTINCT depto, edad FROM emp WHERE edad > 60",
    "SELECT COUNT(DISTINCT depto) AS n FROM emp",
    "SELECT COUNT(*) AS n, COUNT(DISTINCT depto) AS d, SUM(DISTINCT depto) AS s FROM emp",
    "SELECT depto, COUNT(DISTINCT edad) AS e, COUNT(*) AS n FROM emp GROUP BY depto ORDER BY depto",
    "SELECT depto, AVG(DISTINCT edad) AS a FROM emp GROUP BY depto HAVING COUNT(DISTINCT edad) > 30 ORDER BY depto",
    "SELECT COUNT(DISTINCT depto) AS n, MIN(edad) AS m FROM emp WHERE edad > 100",
    "SELECT d.piso, COUNT(DISTINCT e.depto) AS n FROM emp e JOIN dep d ON e.depto = d.did GROUP BY d.piso ORDER BY d.piso",
    "SELECT e.id, d.dnombre FROM emp e JOIN dep d ON e.depto = d.did WHERE e.id < 20",
    "SELECT e.id, d.dnombre FROM emp AS e INNER JOIN dep AS d ON d.did = e.depto WHERE d.piso = 2 AND e.edad > 50",
    "SELECT d.dnombre, COUNT(*) AS n FROM emp e JOIN dep d ON e.depto = d.did GROUP BY d.dnombre ORDER BY d.dnombre",
    "SELECT d.piso, AVG(e.salario) AS a FROM emp e JOIN dep d ON e.depto = d.did GROUP BY d.piso HAVING COUNT(*) > 10",
    "SELECT e.id FROM emp e JOIN dep d ON e.depto = d.did ORDER BY e.salario DESC LIMIT 4",
    "SELECT COUNT(*) AS n FROM emp e JOIN dep d ON e.depto = d.did",
    "SELECT emp.id FROM emp WHERE emp.depto = 2 AND emp.id < 50",
    "SELECT id FROM emp WHERE depto = 9",
    "SELECT nombre FROM emp WHERE nombre = 'bob1'",
    "SELECT id FROM emp WHERE nombre > 'eva' AND nombre < 'fer'",
    "SELECT id FROM emp WHERE id = 1.0",
    "SELECT id FROM emp WHERE salario = 0",
    "SELECT MIN(nombre) AS a, MAX(nombre) AS b FROM emp",
    "SELECT depto FROM emp GROUP BY depto HAVING SUM(edad) > 2000 ORDER BY depto",
    "SELECT id FROM emp WHERE edad % 10 = 0 ORDER BY id LIMIT 8",
]


# Consultas cuyo ORDER BY no admite empates: el orden debe ser idéntico.
TOTAL_ORDER = {sql for sql in QUERIES if sql.endswith((
    "ORDER BY nombre, id DESC LIMIT 15", "ORDER BY id LIMIT 0", "ORDER BY 1 DESC LIMIT 3",
    "ORDER BY k DESC LIMIT 3", "GROUP BY depto ORDER BY depto", "GROUP BY d.dnombre ORDER BY d.dnombre",
    "ORDER BY depto, edad LIMIT 10", "HAVING SUM(edad) > 2000 ORDER BY depto", "edad % 10 = 0 ORDER BY id LIMIT 8",
    "GROUP BY depto ORDER BY depto", "GROUP BY d.piso ORDER BY d.piso"))}


def normalize(value):
    return round(value, 6) if isinstance(value, float) else value


class TestAgainstSQLite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(1)
        cls.emps = [{"id": i, "nombre": rng.choice(["ana", "bob", "carla", "dan", "eva", "fer"]) + str(i % 7),
                     "depto": rng.randrange(6), "salario": round(rng.uniform(100, 900), 2),
                     "edad": rng.randrange(18, 65)} for i in range(300)]
        cls.deps = [{"did": i, "dnombre": f"d{i}", "piso": rng.randrange(1, 4)} for i in range(5)]
        cls.sqlite = sqlite3.connect(":memory:")
        cls.sqlite.execute("CREATE TABLE emp (id INT, nombre TEXT, depto INT, salario REAL, edad INT)")
        cls.sqlite.execute("CREATE TABLE dep (did INT, dnombre TEXT, piso INT)")
        cls.sqlite.executemany("INSERT INTO emp VALUES (?,?,?,?,?)", [tuple(e.values()) for e in cls.emps])
        cls.sqlite.executemany("INSERT INTO dep VALUES (?,?,?)", [tuple(d.values()) for d in cls.deps])
        cls.dir = tempfile.mkdtemp()
        cls.closables = []

    @classmethod
    def tearDownClass(cls):
        for item in cls.closables:
            item.close()
        cls.sqlite.close()

    def engine(self, kind):
        path = os.path.join(self.dir, kind)
        if kind == "heap":
            emp = HeapFile(path + "_emp.heap", EMP, page_size=512)
        elif kind == "sequential":
            emp = SequentialFile(path + ".main", path + ".aux", EMP, "id", page_size=512)
        else:
            emp = ClusteredBPlusFile(path + ".bpt", EMP, "id", page_size=1024)
        dep = HeapFile(path + "_dep.heap", DEP)
        self.closables += [emp, dep]
        for record in self.emps:
            emp.insert(record)
        for record in self.deps:
            dep.insert(record)
        catalog = Catalog()
        catalog.register_table("emp", emp, {"id": emp.primary_index_info("emp_pk")} if kind == "btree" else None)
        catalog.register_table("dep", dep)
        if kind == "heap":
            depto = ExtendibleHash()
            salario = BPlusTreeUnclustered(path + "_salario.bpt", "float", order=16)
            did = ExtendibleHash()
            self.closables.append(salario)
            catalog.register_index("emp", "depto", depto, IndexInfo("e_depto", "depto", depto))
            catalog.register_index("emp", "salario", salario, IndexInfo("e_salario", "salario", salario, ordered=True))
            catalog.register_index("dep", "did", did, IndexInfo("d_did", "did", did))
        return SQLExecutor(catalog)

    def test_queries_match_sqlite(self):
        for kind in ("heap", "sequential", "btree"):
            executor = self.engine(kind)
            for sql in QUERIES:
                with self.subTest(storage=kind, sql=sql):
                    ours = [tuple(normalize(v) for v in row.values()) for row in executor.execute(sql)]
                    expected = [tuple(normalize(v) for v in row) for row in self.sqlite.execute(sql)]
                    if sql in TOTAL_ORDER:
                        self.assertEqual(ours, expected)
                    else:
                        # Sin ORDER BY no hay orden definido; con empates en el
                        # ORDER BY el orden entre filas empatadas puede variar.
                        self.assertCountEqual(ours, expected)


if __name__ == "__main__":
    unittest.main()
