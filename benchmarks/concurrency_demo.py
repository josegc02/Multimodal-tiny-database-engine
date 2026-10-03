"""Simulación de concurrencia con hilos sobre el motor real (Parte 1, sección 2.1.4).

Cada hilo es un usuario con su propia sesión SQL (StatementExecutor) que
comparte el Catalog, el LockManager y el TransactionManager. Escenarios:

1. Race condition SIN control de concurrencia: dos hilos hacen
   leer-modificar-escribir directo sobre el archivo y se pierde una
   actualización (lost update).
2. La misma operación con transacciones (BEGIN TRANSACTION ... END TRANSACTION):
   los locks S/SIX la serializan; si dos transacciones se bloquean
   mutuamente, el LockManager detecta el deadlock, aborta (ROLLBACK) a una y
   el cliente la reintenta. El saldo final es exacto.
3. Múltiples transacciones simultáneas insertando claves distintas: corren en
   paralelo (locks IX compatibles) y no se pierde ninguna fila.
4. Lectura sucia evitada: un SELECT espera a que termine la transacción que
   insertó sin confirmar y no ve la fila deshecha por ROLLBACK.
5. Deadlock explícito entre dos transacciones y su resolución.

Uso: python -m benchmarks.concurrency_demo
"""

import os
import random
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.concurrency.lock_manager import DeadlockError, LockManager
from engine.concurrency.transaction_manager import TransactionManager
from engine.query.catalog import Catalog
from engine.query.parser import parse_script
from engine.query.statement_executor import StatementExecutor
from engine.storage.heap_file import HeapFile

_print_lock = threading.Lock()
_t0 = time.perf_counter()
VERBOSE = True


def log(msg: str) -> None:
    """Log con tiempo relativo (ms) para ver el intercalado de los hilos."""
    if VERBOSE:
        with _print_lock:
            print(f"[{(time.perf_counter() - _t0) * 1000:8.1f} ms] {msg}", flush=True)


class Banco:
    """Base de datos de demo: tabla cuentas(id, titular, saldo) en un HeapFile."""

    def __init__(self, cuentas):
        self.dir = tempfile.mkdtemp(prefix="bd2-concurrencia-")
        self.storage = HeapFile(os.path.join(self.dir, "cuentas.db"),
                                [("id", "int"), ("titular", "str", 20), ("saldo", "int")])
        self.catalog = Catalog()
        self.catalog.register_table("cuentas", self.storage)
        self.lock_manager = LockManager()
        self.tm = TransactionManager(self.lock_manager, storage=self.catalog)
        valores = ", ".join(f"({i}, '{titular}', {saldo})" for i, titular, saldo in cuentas)
        self.sql(self.sesion(), f"INSERT INTO cuentas VALUES {valores};")

    def sesion(self):
        """Una sesión por usuario/hilo."""
        return StatementExecutor(self.tm, self.lock_manager, self.catalog)

    @staticmethod
    def sql(sesion, script):
        resultado = None
        for sentencia in parse_script(script):
            resultado = sesion.execute(sentencia)
        return resultado

    def filas(self):
        return sorted((r for _, r in self.storage.scan()), key=lambda r: r["id"])

    def cerrar(self):
        self.storage.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def _hilos(objetivos):
    hilos = [threading.Thread(target=f, name=nombre) for nombre, f in objetivos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return not any(h.is_alive() for h in hilos)


def _resultado(ok, mensaje_ok, mensaje_error):
    log(("  CORRECTO: " + mensaje_ok) if ok else ("  ERROR: " + mensaje_error))
    return ok


# =====================================================================
# Escenario 1: race condition sin control de concurrencia
# =====================================================================

def escenario_race_condition_sin_control():
    log("Escenario 1: dos retiros simultáneos SIN transacciones ni locks")
    banco = Banco([(1, "Ana", 1000)])
    try:
        storage = banco.storage

        def retiro(monto):
            def tarea():
                rid, cuenta = next((rid, r) for rid, r in storage.scan() if r["id"] == 1)
                log(f"  {threading.current_thread().name} lee saldo = {cuenta['saldo']}")
                time.sleep(0.05)  # ambos hilos leen antes de que el otro escriba
                storage.delete(rid)
                storage.insert({**cuenta, "saldo": cuenta["saldo"] - monto})
                log(f"  {threading.current_thread().name} escribe saldo = {cuenta['saldo'] - monto}")
            return tarea

        _hilos([("Retiro-100", retiro(100)), ("Retiro-200", retiro(200))])
        saldos = [r["saldo"] for r in banco.filas()]
        log(f"  Saldo esperado: 700 | filas resultantes: {saldos}")
        # Sin control, el segundo hilo sobrescribe con un saldo calculado sobre un valor viejo.
        hubo_race = saldos != [700]
        log("  RACE CONDITION: se perdió una actualización (lost update)" if hubo_race
            else "  Esta vez los hilos no se intercalaron")
        return hubo_race
    finally:
        banco.cerrar()


# =====================================================================
# Escenario 2: la misma operación con transacciones y locks
# =====================================================================

def escenario_retiros_con_transacciones(hilos=3, retiros_por_hilo=3):
    log(f"Escenario 2: {hilos} usuarios retiran dinero con BEGIN TRANSACTION ... END TRANSACTION")
    banco = Banco([(1, "Ana", 1000)])
    abortos = []
    try:
        def usuario(monto):
            sesion = banco.sesion()

            def tarea():
                nombre = threading.current_thread().name
                for _ in range(retiros_por_hilo):
                    while True:
                        try:
                            banco.sql(sesion, "BEGIN TRANSACTION;")
                            saldo = banco.sql(sesion, "SELECT saldo FROM cuentas WHERE id = 1;")[0]["saldo"]
                            log(f"  {nombre} tx {sesion.current_tx_id}: lee saldo = {saldo}")
                            time.sleep(0.01)
                            banco.sql(sesion, "DELETE FROM cuentas WHERE id = 1;")
                            banco.sql(sesion, f"INSERT INTO cuentas VALUES (1, 'Ana', {saldo - monto});")
                            tx_id = sesion.current_tx_id
                            banco.sql(sesion, "END TRANSACTION;")
                            log(f"  {nombre} tx {tx_id}: escribe {saldo - monto} y confirma")
                            break
                        except DeadlockError as exc:
                            abortos.append(nombre)
                            log(f"  {nombre}: {exc}")
                            time.sleep(random.uniform(0.001, 0.02))  # backoff y reintento
            return tarea

        montos = [10 * (i + 1) for i in range(hilos)]
        terminaron = _hilos([(f"Usuario-{m}", usuario(m)) for m in montos])
        esperado = 1000 - retiros_por_hilo * sum(montos)
        filas = banco.filas()
        log(f"  Saldo esperado: {esperado} | obtenido: {[r['saldo'] for r in filas]} | "
            f"transacciones abortadas por deadlock y reintentadas: {len(abortos)}")
        ok = terminaron and [r["saldo"] for r in filas] == [esperado]
        return _resultado(ok, "ningún retiro se perdió; los conflictos se resolvieron con ROLLBACK y reintento",
                          "el saldo final no coincide")
    finally:
        banco.cerrar()


# =====================================================================
# Escenario 3: múltiples transacciones simultáneas
# =====================================================================

def escenario_transacciones_simultaneas(hilos=4, filas_por_hilo=50):
    log(f"Escenario 3: {hilos} transacciones insertan {filas_por_hilo} cuentas cada una al mismo tiempo")
    banco = Banco([(0, "Banco", 0)])
    intervalos = {}
    try:
        def usuario(base):
            sesion = banco.sesion()

            def tarea():
                nombre = threading.current_thread().name
                banco.sql(sesion, "BEGIN TRANSACTION;")
                inicio = time.perf_counter()
                for i in range(filas_por_hilo):
                    banco.sql(sesion, f"INSERT INTO cuentas VALUES ({base + i}, '{nombre}', 100);")
                banco.sql(sesion, "END TRANSACTION;")
                intervalos[nombre] = (inicio, time.perf_counter())
                log(f"  {nombre}: {filas_por_hilo} inserciones confirmadas")
            return tarea

        terminaron = _hilos([(f"Tx-{k}", usuario(1000 * (k + 1))) for k in range(hilos)])
        total = len(banco.filas()) - 1
        inicio_max = max(i for i, _ in intervalos.values())
        fin_min = min(f for _, f in intervalos.values())
        solapadas = inicio_max < fin_min
        log(f"  Filas esperadas: {hilos * filas_por_hilo} | guardadas: {total} | "
            f"las transacciones se ejecutaron en paralelo: {'sí' if solapadas else 'no'}")
        ok = terminaron and total == hilos * filas_por_hilo
        return _resultado(ok, "ninguna inserción se perdió (locks IX compatibles + latch del archivo)",
                          "se perdieron inserciones")
    finally:
        banco.cerrar()


# =====================================================================
# Escenario 4: lectura sucia evitada
# =====================================================================

def escenario_lectura_sucia():
    log("Escenario 4: un SELECT no ve datos sin confirmar")
    banco = Banco([(1, "Ana", 1000)])
    try:
        escritor, lector = banco.sesion(), banco.sesion()
        visto = []

        def escribir():
            banco.sql(escritor, "BEGIN TRANSACTION; INSERT INTO cuentas VALUES (2, 'Fantasma', 5000);")
            log("  Escritor: insertó la cuenta 2 (sin confirmar)")
            time.sleep(0.2)
            banco.sql(escritor, "ROLLBACK;")
            log("  Escritor: ROLLBACK")

        def leer():
            time.sleep(0.05)
            log("  Lector: SELECT * FROM cuentas ... (espera el lock S)")
            filas = banco.sql(lector, "SELECT id FROM cuentas;")
            visto.extend(r["id"] for r in filas)
            log(f"  Lector: obtuvo ids {visto}")

        terminaron = _hilos([("Escritor", escribir), ("Lector", leer)])
        return _resultado(terminaron and visto == [1],
                          "el lector esperó y nunca vio la cuenta deshecha",
                          f"lectura sucia: el lector vio {visto}")
    finally:
        banco.cerrar()


# =====================================================================
# Escenario 5: deadlock explícito
# =====================================================================

def escenario_deadlock():
    log("Escenario 5: dos transacciones leen la tabla y luego ambas quieren escribir")
    banco = Banco([(1, "Ana", 100), (2, "Beto", 200)])
    try:
        t1, t2 = banco.sesion(), banco.sesion()
        eventos = []

        def transaccion(sesion, nombre, borrar, espera):
            def tarea():
                banco.sql(sesion, "BEGIN TRANSACTION; SELECT * FROM cuentas;")
                log(f"  {nombre}: tiene lock S sobre cuentas")
                time.sleep(espera)
                try:
                    log(f"  {nombre}: DELETE cuenta {borrar} (pide SIX, espera al otro)")
                    banco.sql(sesion, f"DELETE FROM cuentas WHERE id = {borrar};")
                    banco.sql(sesion, "END TRANSACTION;")
                    eventos.append(("confirmada", nombre))
                    log(f"  {nombre}: confirmada")
                except DeadlockError as exc:
                    eventos.append(("abortada", nombre))
                    log(f"  {nombre}: {exc}")
            return tarea

        terminaron = _hilos([("T1", transaccion(t1, "T1", 1, 0.05)),
                             ("T2", transaccion(t2, "T2", 2, 0.15))])
        estados = sorted(e for e, _ in eventos)
        ids = [r["id"] for r in banco.filas()]
        log(f"  Resultado: {eventos} | cuentas restantes: {ids}")
        ok = terminaron and estados == ["abortada", "confirmada"] and len(ids) == 1
        return _resultado(ok, "deadlock detectado; la abortada se deshizo y liberó sus locks",
                          "el deadlock no se resolvió como se esperaba")
    finally:
        banco.cerrar()


ESCENARIOS = (
    ("Race condition sin control de concurrencia", escenario_race_condition_sin_control),
    ("Retiros concurrentes con transacciones", escenario_retiros_con_transacciones),
    ("Múltiples transacciones simultáneas", escenario_transacciones_simultaneas),
    ("Lectura sucia evitada", escenario_lectura_sucia),
    ("Detección de deadlock", escenario_deadlock),
)


def main():
    print("=" * 70)
    print("DEMOSTRACIÓN DE TRANSACCIONES Y CONCURRENCIA")
    print("=" * 70)
    resultados = []
    for titulo, escenario in ESCENARIOS:
        print(f"\n--- {titulo} ---")
        resultados.append((titulo, escenario()))
    print("\n" + "=" * 70)
    for titulo, ok in resultados:
        print(f"{'OK ' if ok else 'X  '} {titulo}")
    return 0 if all(ok for _, ok in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
