"""Simulacion de concurrencia con hilos.

Demuestra:
1. Race condition sin locks
2. Correccion con locks
3. Transacciones concurrentes sobre el mismo registro
4. Deteccion de deadlocks
"""

import threading
import time


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
        # Leer
        v = self.valor
        # Pequena pausa para forzar la race condition
        time.sleep(0.00001)
        # Escribir
        self.valor = v + 1


def demo_race_condition_sin_locks():
    """Dos hilos incrementan el mismo contador sin locks."""
    log("Iniciando escenario 1: race condition sin locks")
    contador = ContadorSinLocks()
    ITERACIONES = 1000

    def worker(nombre):
        log(f"  {nombre} comienza")
        for i in range(ITERACIONES):
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
# Escenarios pendientes
# =====================================================================

def demo_race_condition_con_locks():
    raise NotImplementedError("Pendiente")


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
    try:
        demo_race_condition_con_locks()
    except NotImplementedError:
        print("  (Pendiente)")

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