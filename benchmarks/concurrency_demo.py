"""Simulacion de concurrencia con hilos.

Demuestra:
1. Race condition sin locks
2. Correccion con locks
3. Transacciones concurrentes sobre el mismo registro
4. Deteccion de deadlocks
"""

import os
import sys
import tempfile
import threading
import time

from engine.concurrency.lock_manager import LockManager, LockMode
from engine.concurrency.transaction_manager import TransactionManager
from engine.query.catalog import Catalog
from engine.storage.heap_file import HeapFile


def _timestamp() -> str:
    """Marca de tiempo legible para los logs."""
    return time.strftime("%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"


def log(msg: str) -> None:
    """Log con timestamp para ver la concurrencia."""
    print(f"[{_timestamp()}] {msg}")


# =====================================================================
# Escenario 1: race condition sin locks
# =====================================================================

class ContadorSinLocks:
    """Contador compartido SIN proteccion. Va a fallar."""

    def __init__(self):
        self.valor = 0

    def incrementar(self):
        v = self.valor
        time.sleep(0.00001)
        self.valor = v + 1


def demo_race_condition_sin_locks():
    """Dos hilos incrementan el mismo contador sin locks."""
    log("Iniciando escenario 1: race condition sin locks")
    contador = ContadorSinLocks()
    ITERACIONES = 1000

    def worker(nombre):
        log(f"  {nombre} comienza")
        for _ in range(ITERACIONES):
            contador.incrementar()
        time.sleep(0.001)
        log(f"  {nombre} termina")

    t1 = threading.Thread(target=worker, args=("Hilo-1",))
    t2 = threading.Thread(target=worker, args=("Hilo-2",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    esperado = ITERACIONES * 2
    obtenido = contador.valor

    log(f"  Iteraciones por hilo: {ITERACIONES}")
    log(f"  Esperado: {esperado}")
    log(f"  Obtenido: {obtenido}")
    log(f"  Perdidas: {esperado - obtenido}")
    if obtenido < esperado:
        log(f"  RACE CONDITION DETECTADA (perdidas: {esperado - obtenido})")
    else:
        log(f"  Esta vez no hubo race condition (suerte).")


# =====================================================================
# Escenario 2: misma race condition, pero con LockManager
# =====================================================================

class ContadorConLocks:
    """Contador compartido PROTEGIDO con LockManager."""

    def __init__(self, lock_manager: LockManager):
        self.valor = 0
        self.lm = lock_manager

    def incrementar(self, tx_id: int):
        self.lm.acquire(tx_id, "contador", LockMode.EXCLUSIVE)
        try:
            v = self.valor
            time.sleep(0.00001)
            self.valor = v + 1
        finally:
            self.lm.release(tx_id, "contador")


def demo_race_condition_con_locks():
    """Misma race condition, pero con LockManager."""
    log("Iniciando escenario 2: correccion con locks")
    lm = LockManager()
    contador = ContadorConLocks(lm)
    ITERACIONES = 1000

    def worker(nombre, tx_id):
        log(f"  {nombre} comienza")
        for _ in range(ITERACIONES):
            contador.incrementar(tx_id)
        log(f"  {nombre} termina")

    t1 = threading.Thread(target=worker, args=("Hilo-1", 1), daemon=True)
    t2 = threading.Thread(target=worker, args=("Hilo-2", 2), daemon=True)

    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    esperado = ITERACIONES * 2
    obtenido = contador.valor

    log(f"  Iteraciones por hilo: {ITERACIONES}")
    log(f"  Esperado: {esperado}")
    log(f"  Obtenido: {obtenido}")
    log(f"  Perdidas: {esperado - obtenido}")
    if obtenido == esperado:
        log(f"  SIN PERDIDAS: los locks funcionaron")
    else:
        log(f"  ERROR: se perdieron {esperado - obtenido} incrementos")


# =====================================================================
# Escenario 3: transacciones concurrentes sobre el mismo registro
# =====================================================================

def demo_transacciones_concurrentes():
    """Dos transacciones reales modifican el mismo registro en un HeapFile.

    Cada transaccion:
    1. Abre una transaccion (BEGIN).
    2. Adquiere lock exclusivo sobre el registro.
    3. Lee el saldo actual.
    4. Simula un poco de trabajo.
    5. Escribe el saldo actualizado.
    6. Hace commit.

    Con locks, el saldo final debe ser exactamente 700.
    Sin locks, habria lost update.
    """
    log("Iniciando escenario 3: transacciones concurrentes")

    # 1. Crear storage limpio
    db_path = os.path.join(tempfile.gettempdir(), "demo_concurrente.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    schema = [("id", "int"), ("saldo", "int")]
    storage = HeapFile(db_path, schema)
    storage.insert({"id": 1, "saldo": 1000})

    catalog = Catalog()
    catalog.register_table("cuentas", storage)

    lm = LockManager()
    tm = TransactionManager(lm, storage=catalog)

    # 2. Funcion de una transaccion
    def transaccion(monto, nombre):
        tx_id = tm.begin()
        log(f"  {nombre} inicia tx {tx_id}")

        # Lock exclusivo sobre el registro
        lm.acquire(tx_id, "cuentas:1", LockMode.EXCLUSIVE)
        tx = tm.get_transaction(tx_id)
        tx.add_lock("cuentas:1", LockMode.EXCLUSIVE)

        # Leer saldo actual
        filas = list(storage.scan())
        rid = filas[0][0]
        saldo_actual = filas[0][1]["saldo"]
        log(f"  {nombre} lee saldo = {saldo_actual}")

        # Simular trabajo (esto fuerza la race condition si no hay lock)
        time.sleep(0.05)

        # Escribir saldo actualizado
        storage.delete(rid)
        storage.insert({"id": 1, "saldo": saldo_actual - monto})
        log(f"  {nombre} escribe saldo = {saldo_actual - monto}")

        # Registrar en undo_log para rollback
        tx.add_operation({
            "op": "UPDATE",
            "table": "cuentas",
            "rid": rid,
            "old": {"id": 1, "saldo": saldo_actual},
        })

        tm.commit(tx_id)
        log(f"  {nombre} confirma tx {tx_id}")

    # 3. Lanzar dos transacciones concurrentes
    t1 = threading.Thread(target=transaccion, args=(100, "T1"), daemon=True)
    t2 = threading.Thread(target=transaccion, args=(200, "T2"), daemon=True)

    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    if t1.is_alive() or t2.is_alive():
        log("  TIMEOUT: alguna transaccion se quedo colgada")
        storage.close()
        return

    # 4. Verificar saldo final
    filas = list(storage.scan())
    saldo_final = filas[0][1]["saldo"]
    esperado = 1000 - 100 - 200

    log(f"  Saldo esperado: {esperado}")
    log(f"  Saldo obtenido: {saldo_final}")

    if saldo_final == esperado:
        log(f"  CORRECTO: las transacciones se serializaron bien")
    else:
        log(f"  ERROR: lost update detectado (diferencia: {saldo_final - esperado})")

    storage.close()
    if os.path.exists(db_path):
        os.remove(db_path)


# =====================================================================
# Escenario 4: deteccion de deadlocks
# =====================================================================

def demo_deadlock():
    """Dos transacciones se esperan mutuamente.

    T1 tiene A, quiere B.
    T2 tiene B, quiere A.
    Deadlock.

    El LockManager lo detecta y aborta una transaccion.
    """
    log("Iniciando escenario 4: deteccion de deadlocks")

    lm = LockManager()
    errores = []

    def transaccion_1():
        try:
            lm.acquire(1, "cuenta:A", LockMode.EXCLUSIVE)
            log("  T1 obtiene lock sobre A")

            time.sleep(0.1)  # Esperar a que T2 tome B

            log("  T1 intenta lock sobre B")
            lm.acquire(1, "cuenta:B", LockMode.EXCLUSIVE, timeout=5)
            log("  T1 obtiene lock sobre B")

        except RuntimeError as e:
            log(f"  T1 ABORTADA: {e}")
            errores.append("T1")
        finally:
            lm.release_all(1)

    def transaccion_2():
        try:
            lm.acquire(2, "cuenta:B", LockMode.EXCLUSIVE)
            log("  T2 obtiene lock sobre B")

            time.sleep(0.1)  # Esperar a que T1 tome A

            log("  T2 intenta lock sobre A")
            lm.acquire(2, "cuenta:A", LockMode.EXCLUSIVE, timeout=5)
            log("  T2 obtiene lock sobre A")

        except RuntimeError as e:
            log(f"  T2 ABORTADA: {e}")
            errores.append("T2")
        finally:
            lm.release_all(2)

    t1 = threading.Thread(target=transaccion_1, daemon=True)
    t2 = threading.Thread(target=transaccion_2, daemon=True)

    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    if t1.is_alive() or t2.is_alive():
        log("  TIMEOUT: alguna transaccion quedo colgada (deadlock no detectado)")
        return

    if errores:
        log(f"  CORRECTO: deadlock detectado y resuelto (abortada: {errores[0]})")
    else:
        log("  ERROR: no se detecto deadlock, algo esta mal")


# =====================================================================
# Main
# =====================================================================

def main():
    print("=" * 60)
    print("DEMOSTRACION DE CONCURRENCIA")
    print("=" * 60)

    print("\n--- Escenario 1: Race condition sin locks ---")
    demo_race_condition_sin_locks()

    print("\n--- Escenario 2: Correccion con locks ---")
    demo_race_condition_con_locks()

    print("\n--- Escenario 3: Transacciones concurrentes ---")
    demo_transacciones_concurrentes()

    print("\n--- Escenario 4: Deteccion de deadlock ---")
    demo_deadlock()



if __name__ == "__main__":
    main()