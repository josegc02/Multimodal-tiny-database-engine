"""Simulacion de concurrencia con hilos.

Demuestra:
1. Race condition sin locks
2. Correccion con locks
3. Transacciones concurrentes sobre el mismo registro
4. Deteccion de deadlocks
"""

import sys
import threading
import time
import faulthandler
faulthandler.dump_traceback_later(10, exit=True)

from engine.concurrency.lock_manager import LockManager, LockMode


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
# Escenarios pendientes
# =====================================================================

def demo_transacciones_concurrentes():
    raise NotImplementedError("Pendiente")


def demo_deadlock():
    raise NotImplementedError("Pendiente")


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
    try:
        demo_transacciones_concurrentes()
    except NotImplementedError:
        print("  (Pendiente)")

    print("\n--- Escenario 4: Deteccion de deadlock ---")
    try:
        demo_deadlock()
    except NotImplementedError:
        print("  (Pendiente)")



if __name__ == "__main__":
    main()