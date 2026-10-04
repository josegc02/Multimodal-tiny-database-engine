import os
import random
import tempfile
import threading
import time
import unittest

from engine.concurrency.lock_manager import DeadlockError, LockManager, LockMode
from engine.concurrency.transaction_manager import TransactionManager
from engine.indexes import ExtendibleHash
from engine.query.catalog import Catalog
from engine.query.errors import SQLSemanticError
from engine.query.parser import parse_script
from engine.query.planner import IndexInfo
from engine.query.statement_executor import StatementExecutor
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile

SCHEMA = [("id", "int"), ("saldo", "int")]


def run(session, sql):
    """Ejecuta un script y devuelve el resultado de la última sentencia."""
    result = None
    for statement in parse_script(sql):
        result = session.execute(statement)
    return result


class Engine:
    """Catálogo + LockManager + TransactionManager compartidos por varias sesiones."""

    def __init__(self, storage_kind="heap", page_size=4096):
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "cuentas")
        if storage_kind == "heap":
            storage = HeapFile(path + ".db", SCHEMA, page_size=page_size)
        else:
            storage = SequentialFile(path + ".main", path + ".aux", SCHEMA, "id", page_size=page_size)
        self.storage = storage
        self.catalog = Catalog()
        self.catalog.register_table("cuentas", storage)
        self.lm = LockManager()
        self.tm = TransactionManager(self.lm, storage=self.catalog)

    def session(self):
        return StatementExecutor(self.tm, self.lm, self.catalog)

    def ids(self):
        return sorted(record["id"] for _, record in self.storage.scan())

    def close(self):
        self.storage.close()


class TestLockModes(unittest.TestCase):
    def test_intention_locks_allow_concurrent_writers(self):
        lm = LockManager()
        self.assertTrue(lm.acquire(1, "t", LockMode.INTENTION_EXCLUSIVE))
        self.assertTrue(lm.acquire(2, "t", LockMode.INTENTION_EXCLUSIVE, timeout=0.05))

    def test_shared_table_lock_waits_for_writer(self):
        lm = LockManager()
        lm.acquire(1, "t", LockMode.INTENTION_EXCLUSIVE)
        self.assertFalse(lm.acquire(2, "t", LockMode.SHARED, timeout=0.05))
        lm.release_all(1)
        self.assertTrue(lm.acquire(2, "t", LockMode.SHARED, timeout=0.05))

    def test_read_then_write_upgrades_to_six(self):
        lm = LockManager()
        lm.acquire(1, "t", LockMode.SHARED)
        lm.acquire(1, "t", LockMode.INTENTION_EXCLUSIVE)
        self.assertEqual(lm.get_locks(1), [("t", LockMode.SHARED_INTENTION_EXCLUSIVE)])
        self.assertFalse(lm.acquire(2, "t", LockMode.SHARED, timeout=0.05))
        self.assertTrue(lm.acquire(2, "t", LockMode.INTENTION_SHARED, timeout=0.05))

    def test_exclusive_covers_weaker_modes(self):
        lm = LockManager()
        lm.acquire(1, "r", LockMode.EXCLUSIVE)
        self.assertTrue(lm.acquire(1, "r", LockMode.SHARED))
        self.assertEqual(lm.get_locks(1), [("r", LockMode.EXCLUSIVE)])


class TestRollback(unittest.TestCase):
    def test_sequential_rollback_removes_only_its_inserts(self):
        # Los slots del secuencial se desplazan: el undo no puede confiar en el RID.
        engine = Engine("sequential")
        try:
            session = engine.session()
            run(session, "INSERT INTO cuentas VALUES (10, 1);")
            run(session, "BEGIN TRANSACTION; INSERT INTO cuentas VALUES (20, 2); "
                         "INSERT INTO cuentas VALUES (5, 3); ROLLBACK;")
            self.assertEqual(engine.ids(), [10])
        finally:
            engine.close()

    def test_sequential_rollback_survives_auto_reorganization(self):
        engine = Engine("sequential", page_size=128)
        try:
            session = engine.session()
            run(session, "INSERT INTO cuentas VALUES " + ", ".join(f"({i}, 0)" for i in range(0, 40, 2)) + ";")
            run(session, "BEGIN;")
            for i in range(1, 40, 2):
                run(session, f"INSERT INTO cuentas VALUES ({i}, 0);")
            run(session, "ROLLBACK;")
            self.assertEqual(engine.ids(), list(range(0, 40, 2)))
        finally:
            engine.close()

    def test_rollback_restores_deleted_rows_and_refreshes_indexes(self):
        engine = Engine("heap")
        try:
            index = ExtendibleHash()
            engine.catalog.register_index("cuentas", "id", index, IndexInfo("cuentas_id", "id", index))
            session = engine.session()
            run(session, "INSERT INTO cuentas VALUES (1, 100), (2, 50);")
            run(session, "BEGIN; DELETE FROM cuentas WHERE cuentas.id = 2; INSERT INTO cuentas VALUES (3, 7);")
            run(session, "ROLLBACK;")
            self.assertEqual(engine.ids(), [1, 2])
            self.assertEqual(run(session, "SELECT saldo FROM cuentas WHERE id = 2;"), [{"saldo": 50}])
            self.assertEqual(run(session, "SELECT * FROM cuentas WHERE id = 3;"), [])
            self.assertEqual(len(index.search(2)), 1)
            self.assertEqual(engine.lm.lock_table, {})
        finally:
            engine.close()

    def test_invalid_insert_writes_nothing_and_leaves_no_transaction(self):
        engine = Engine("heap")
        try:
            session = engine.session()
            with self.assertRaises(SQLSemanticError):
                run(session, "INSERT INTO cuentas (id) VALUES (7);")
            with self.assertRaises(SQLSemanticError):
                run(session, "INSERT INTO cuentas VALUES (8, 'texto');")
            self.assertEqual(engine.ids(), [])
            self.assertFalse(session.in_transaction)
            self.assertEqual(engine.tm.active_count(), 0)
        finally:
            engine.close()


class TestConcurrency(unittest.TestCase):
    def _parallel(self, workers):
        errors = []

        def wrap(target):
            def runner():
                try:
                    target()
                except Exception as exc:  # pragma: no cover - se reporta abajo
                    errors.append(exc)
            return runner

        threads = [threading.Thread(target=wrap(w)) for w in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertFalse(any(t.is_alive() for t in threads), "algún hilo quedó bloqueado")
        self.assertEqual(errors, [])

    def test_concurrent_inserts_lose_no_rows(self):
        for kind in ("heap", "sequential"):
            with self.subTest(storage=kind):
                engine = Engine(kind, page_size=256)
                try:
                    def worker(base):
                        session = engine.session()
                        return lambda: [run(session, f"INSERT INTO cuentas VALUES ({base + i}, 0);")
                                        for i in range(100)]
                    self._parallel([worker(k * 1000) for k in range(4)])
                    expected = sorted(k * 1000 + i for k in range(4) for i in range(100))
                    self.assertEqual(engine.ids(), expected)
                finally:
                    engine.close()

    def test_transaction_ids_are_unique_across_threads(self):
        tm = TransactionManager(LockManager())
        ids = []
        lock = threading.Lock()

        def worker():
            for _ in range(200):
                tx_id = tm.begin()
                with lock:
                    ids.append(tx_id)
                tm.commit(tx_id)
        self._parallel([worker] * 4)
        self.assertEqual(len(ids), len(set(ids)))

    def test_reader_does_not_see_uncommitted_rows(self):
        engine = Engine("heap")
        try:
            writer, reader = engine.session(), engine.session()
            run(writer, "INSERT INTO cuentas VALUES (1, 100);")
            run(writer, "BEGIN; INSERT INTO cuentas VALUES (99, 1);")
            seen = []
            thread = threading.Thread(target=lambda: seen.append(run(reader, "SELECT id FROM cuentas;")))
            thread.start()
            time.sleep(0.2)
            self.assertTrue(thread.is_alive(), "el SELECT debió esperar al escritor")
            run(writer, "ROLLBACK;")
            thread.join(timeout=5)
            self.assertEqual(seen, [[{"id": 1}]])
        finally:
            engine.close()

    def test_concurrent_withdrawals_do_not_lose_updates(self):
        # Leer-modificar-escribir: sin locks se perderían retiros (lost update).
        engine = Engine("heap")
        try:
            run(engine.session(), "INSERT INTO cuentas VALUES (1, 1000);")
            aborted = []

            def withdraw(amount, times):
                session = engine.session()

                def task():
                    for _ in range(times):
                        while True:
                            try:
                                run(session, "BEGIN;")
                                saldo = run(session, "SELECT saldo FROM cuentas WHERE id = 1;")[0]["saldo"]
                                time.sleep(0.005)
                                run(session, "DELETE FROM cuentas WHERE id = 1;")
                                run(session, f"INSERT INTO cuentas VALUES (1, {saldo - amount});")
                                run(session, "END TRANSACTION;")
                                break
                            except DeadlockError:
                                # Ya fue deshecha: esperar un tiempo aleatorio y reintentar.
                                aborted.append(amount)
                                time.sleep(random.uniform(0.001, 0.02))
                return task

            self._parallel([withdraw(10, 3), withdraw(20, 3), withdraw(30, 3)])
            rows = [record for _, record in engine.storage.scan()]
            self.assertEqual(rows, [{"id": 1, "saldo": 1000 - 3 * (10 + 20 + 30)}])
            self.assertEqual(engine.lm.lock_table, {})
        finally:
            engine.close()

    def test_deadlock_aborts_one_transaction_and_releases_its_locks(self):
        engine = Engine("heap")
        try:
            run(engine.session(), "INSERT INTO cuentas VALUES (1, 10), (2, 20), (3, 30);")
            t1, t2 = engine.session(), engine.session()
            # Ambas leen la tabla (S) y después quieren escribir (S -> SIX).
            run(t1, "BEGIN TRANSACTION; SELECT * FROM cuentas;")
            run(t2, "BEGIN TRANSACTION; SELECT * FROM cuentas;")
            done = []
            thread = threading.Thread(target=lambda: done.append(run(t1, "DELETE FROM cuentas WHERE id = 1;")))
            thread.start()
            time.sleep(0.2)  # t1 espera a que t2 suelte su S
            self.assertTrue(thread.is_alive())
            with self.assertRaises(DeadlockError):
                run(t2, "DELETE FROM cuentas WHERE id = 2;")
            self.assertFalse(t2.in_transaction)
            thread.join(timeout=5)
            self.assertEqual(done, ["1 registro(s) eliminado(s)"])
            run(t1, "END TRANSACTION;")
            self.assertEqual(engine.ids(), [2, 3])
            self.assertEqual(engine.lm.lock_table, {})
        finally:
            engine.close()

    def test_delete_does_not_skip_rows_deleted_by_uncommitted_transaction(self):
        engine = Engine("heap")
        try:
            run(engine.session(), "INSERT INTO cuentas VALUES (1, 10), (2, 20);")
            t1, t2 = engine.session(), engine.session()
            run(t1, "BEGIN; DELETE FROM cuentas WHERE id = 1;")
            result = []
            thread = threading.Thread(target=lambda: result.append(run(t2, "DELETE FROM cuentas WHERE id = 1;")))
            thread.start()
            time.sleep(0.2)
            self.assertTrue(thread.is_alive(), "el segundo DELETE debió esperar")
            run(t1, "ROLLBACK;")  # la fila 1 vuelve a existir
            thread.join(timeout=5)
            self.assertEqual(result, ["1 registro(s) eliminado(s)"])
            self.assertEqual(engine.ids(), [2])
        finally:
            engine.close()

class TestConcurrencyDemo(unittest.TestCase):
    """La demo obligatoria (enunciado 2.1.4) debe mostrar la race condition y resolverla."""

    def test_all_demo_scenarios_succeed(self):
        from benchmarks import concurrency_demo
        concurrency_demo.VERBOSE = False
        try:
            for title, scenario in concurrency_demo.ESCENARIOS:
                with self.subTest(escenario=title):
                    self.assertTrue(scenario())
        finally:
            concurrency_demo.VERBOSE = True


if __name__ == "__main__":
    unittest.main()
