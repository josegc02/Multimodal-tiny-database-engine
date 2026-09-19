import tempfile
import unittest
from unittest.mock import patch

from frontend.motor import Motor
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile


class TestMotorDDL(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch_demo_dir = patch("frontend.motor.DEMO_DIR", self.temp_dir.name)
        self.patch_demo_dir.start()
        self.motor = Motor()

    def tearDown(self):
        self.motor.cerrar()
        self.patch_demo_dir.stop()
        self.temp_dir.cleanup()

    def execute(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def test_create_table_insert_and_select(self):
        self.execute("CREATE TABLE empleados (id INT, nombre VARCHAR(20), salario FLOAT)")
        self.assertIsInstance(self.motor.catalog.table("empleados").storage, HeapFile)
        self.execute("INSERT INTO empleados VALUES (1, 'Ana', 100.0)")

        result = self.execute("SELECT id, nombre, salario FROM empleados")
        self.assertEqual(result.filas, [(1, "Ana", 100.0)])

    def test_create_table_using_sequential_file(self):
        self.execute("CREATE TABLE empleados_seq (id INT, nombre VARCHAR(20)) USING SEQUENTIAL")
        self.assertIsInstance(self.motor.catalog.table("empleados_seq").storage, SequentialFile)
        self.execute("INSERT INTO empleados_seq VALUES (2, 'Bob'), (1, 'Ana')")
        result = self.execute("SELECT id, nombre FROM empleados_seq")
        self.assertEqual(sorted(result.filas), [(1, "Ana"), (2, "Bob")])
        self.assertEqual(
            self.motor.ejecutar("SELECT * FROM empleados_seq").plan["children"][0]["storage"],
            "SequentialFile",
        )

    def test_execution_plan_reports_heap_storage(self):
        result = self.execute("SELECT * FROM cuentas")
        self.assertEqual(result.plan["children"][0]["storage"], "HeapFile")

    def test_create_table_storage_method_is_preserved_in_ast_result(self):
        result = self.motor.ejecutar("CREATE TABLE empleados_seq_2 (id INT) USING SEQUENTIAL")
        self.assertFalse(result.tiene_error, result.error)
        storage = self.motor.catalog.table("empleados_seq_2").storage
        self.assertEqual(type(storage).__name__, "SequentialFile")

    def test_create_hash_index_is_used_for_select(self):
        self.execute("CREATE TABLE cuentas_nuevas (id INT, saldo INT)")
        self.execute("INSERT INTO cuentas_nuevas VALUES (1, 100), (2, 200)")
        self.execute("CREATE INDEX cuentas_hash ON cuentas_nuevas (id) USING HASH")

        binding = self.motor.catalog.table("cuentas_nuevas")
        self.assertIn("id", binding.indexes)
        self.assertEqual(binding.indexes["id"].metadata.name, "cuentas_hash")
        result = self.execute("SELECT id, saldo FROM cuentas_nuevas WHERE id = 2")
        self.assertEqual(result.filas, [(2, 200)])

    def test_create_btree_index_supports_ordered_queries(self):
        self.execute("CREATE TABLE salarios (id INT, salario INT)")
        self.execute("INSERT INTO salarios VALUES (1, 300), (2, 100), (3, 200)")
        self.execute("CREATE INDEX salarios_btree ON salarios USING BTREE (salario)")

        binding = self.motor.catalog.table("salarios")
        self.assertTrue(binding.indexes["salario"].metadata.ordered)
        result = self.execute("SELECT salario FROM salarios ORDER BY salario")
        self.assertEqual(result.filas, [(100,), (200,), (300,)])

    def test_ddl_rejects_duplicate_table_and_index_column(self):
        self.execute("CREATE TABLE t (id INT)")
        self.assertTrue(self.motor.ejecutar("CREATE TABLE t (id INT)").tiene_error)
        self.execute("CREATE INDEX t_id ON t (id) USING HASH")
        self.assertTrue(self.motor.ejecutar("CREATE INDEX t_id_2 ON t (id) USING BTREE").tiene_error)

    def test_ddl_rejects_duplicate_index_name(self):
        self.execute("CREATE TABLE first_table (id INT)")
        self.execute("CREATE TABLE second_table (id INT)")
        self.execute("CREATE INDEX shared_name ON first_table (id) USING HASH")
        self.assertTrue(self.motor.ejecutar(
            "CREATE INDEX shared_name ON second_table (id) USING HASH"
        ).tiene_error)


if __name__ == "__main__":
    unittest.main()