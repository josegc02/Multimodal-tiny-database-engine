import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from engine.query.parser import parse
from frontend.motor import Motor


class ForeignKeyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("frontend.motor.DEMO_DIR", os.path.join(self.tmp.name, "demo"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)
        self.run_sql("CREATE TABLE carreras (cid INT PRIMARY KEY, nombre VARCHAR(10))")
        self.run_sql("CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(10), "
                     "carrera_id INT REFERENCES carreras(cid) ON DELETE CASCADE)")
        self.run_sql("CREATE TABLE notas (alumno_id INT, nota INT, "
                     "FOREIGN KEY (alumno_id) REFERENCES alumnos ON DELETE CASCADE)")
        self.run_sql("CREATE TABLE becas (alumno_id INT REFERENCES alumnos(id), monto INT)")
        self.run_sql("INSERT INTO carreras VALUES (1, 'CS'), (2, 'Bio')")
        self.run_sql("INSERT INTO alumnos VALUES (10, 'Ana', 1), (11, 'Bob', 1), (12, 'Eva', 2)")
        self.run_sql("INSERT INTO notas VALUES (10, 18), (10, 15), (11, 12), (12, 20)")

    def run_sql(self, sql, motor=None):
        result = (motor or self.motor).ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def error(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertTrue(result.tiene_error, f"se esperaba un error en: {sql}")
        return result.error

    def ids(self, table, column):
        return sorted(row[0] for row in self.run_sql(f"SELECT {column} FROM {table}").filas)


class TestSyntaxAndDefinition(ForeignKeyTestCase):
    def test_parser_accepts_column_and_table_constraints(self):
        statement = parse("CREATE TABLE t (a INT REFERENCES p(id) ON DELETE NO ACTION, b INT, "
                          "FOREIGN KEY (b) REFERENCES q ON DELETE CASCADE)")
        self.assertEqual([(fk.column, fk.ref_table, fk.ref_column, fk.on_delete) for fk in statement.foreign_keys],
                         [("a", "p", "id", "RESTRICT"), ("b", "q", None, "CASCADE")])

    def test_invalid_definitions_are_rejected_without_leaving_files(self):
        self.assertIn("no existe", self.error("CREATE TABLE x (a INT REFERENCES nada(id))"))
        self.assertIn("tipos distintos", self.error("CREATE TABLE x (a VARCHAR(5) REFERENCES carreras(cid))"))
        self.assertIn("clave primaria", self.error("CREATE TABLE x (a INT REFERENCES carreras(nombre))"))
        self.run_sql("CREATE TABLE x (a INT)")

    def test_child_column_gets_an_automatic_index(self):
        binding = self.motor.catalog.table("alumnos")
        self.assertEqual(binding.indexes["carrera_id"].metadata.name, "alumnos_carrera_id_fkey_idx")
        self.assertEqual([fk.name for fk in binding.foreign_keys], ["alumnos_carrera_id_fkey"])


class TestInsertChecks(ForeignKeyTestCase):
    def test_missing_parent_rejects_insert_and_copy_atomically(self):
        message = self.error("INSERT INTO alumnos VALUES (13, 'Zoe', 1), (14, 'Leo', 9)")
        self.assertIn('viola la llave foránea "alumnos_carrera_id_fkey"', message)
        self.assertIn("(carrera_id)=(9)", message)
        self.assertEqual(self.ids("alumnos", "id"), [10, 11, 12])
        path = os.path.join(self.tmp.name, "a.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("13,Zoe,1\n14,Leo,9\n")
        self.assertIn("alumnos_carrera_id_fkey", self.error(f"COPY alumnos FROM '{path}'"))
        self.assertEqual(self.ids("alumnos", "id"), [10, 11, 12])

    def test_failed_statement_inside_transaction_is_undone_alone(self):
        self.run_sql("BEGIN")
        self.run_sql("INSERT INTO carreras VALUES (3, 'Mat')")
        self.error("INSERT INTO alumnos VALUES (20, 'A', 3), (21, 'B', 7)")
        self.assertEqual(self.ids("alumnos", "id"), [10, 11, 12])  # la sentencia es atómica
        self.run_sql("INSERT INTO alumnos VALUES (20, 'A', 3)")    # la transacción sigue viva
        self.run_sql("COMMIT")
        self.assertEqual(self.ids("alumnos", "id"), [10, 11, 12, 20])


class TestDeleteActions(ForeignKeyTestCase):
    def test_restrict_blocks_delete_even_through_a_cascade(self):
        self.run_sql("INSERT INTO becas VALUES (12, 500)")
        message = self.error("DELETE FROM carreras WHERE cid = 2")
        self.assertIn('llave foránea "becas_alumno_id_fkey"', message)
        self.assertEqual(self.ids("carreras", "cid"), [1, 2])
        self.assertEqual(self.ids("alumnos", "id"), [10, 11, 12])

    def test_cascade_deletes_descendants_and_rollback_restores_them(self):
        self.run_sql("BEGIN")
        self.run_sql("DELETE FROM carreras WHERE cid = 1")
        self.assertEqual(self.ids("alumnos", "id"), [12])
        # notas no tiene clave primaria y tiene dos filas del alumno 10: deben borrarse todas.
        self.assertEqual(self.ids("notas", "alumno_id"), [12])
        self.run_sql("ROLLBACK")
        self.assertEqual(self.ids("alumnos", "id"), [10, 11, 12])
        self.assertEqual(self.ids("notas", "alumno_id"), [10, 10, 11, 12])
        self.run_sql("DELETE FROM carreras WHERE cid = 1")
        self.assertEqual(self.ids("notas", "alumno_id"), [12])

    def test_self_referencing_cascade_terminates(self):
        self.run_sql("CREATE TABLE emp (id INT PRIMARY KEY, jefe INT REFERENCES emp(id) ON DELETE CASCADE)")
        self.run_sql("INSERT INTO emp VALUES (1, 1), (2, 1), (3, 2), (4, 4)")
        self.run_sql("DELETE FROM emp WHERE id = 1")
        self.assertEqual(self.ids("emp", "id"), [4])

    def test_child_insert_and_parent_delete_are_serialized(self):
        writer = self.motor.statement_executor
        from engine.query.statement_executor import StatementExecutor
        other = StatementExecutor(self.motor.transaction_manager, self.motor.lock_manager, self.motor.catalog)
        from engine.query.parser import parse_script
        writer.execute(parse_script("BEGIN")[0])
        writer.execute(parse_script("INSERT INTO alumnos VALUES (30, 'Nuevo', 2)")[0])
        result = []
        thread = threading.Thread(target=lambda: result.append(
            other.execute(parse_script("DELETE FROM carreras WHERE cid = 2")[0])))
        thread.start()
        time.sleep(0.2)
        self.assertTrue(thread.is_alive(), "el DELETE del padre debió esperar al INSERT del hijo")
        writer.execute(parse_script("COMMIT")[0])
        thread.join(timeout=5)
        self.assertEqual(result, ["1 registro(s) eliminado(s)"])
        # El CASCADE vio al alumno 30 ya confirmado y lo eliminó.
        self.assertEqual(self.ids("alumnos", "id"), [10, 11])


if __name__ == "__main__":
    unittest.main()
