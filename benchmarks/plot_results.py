"""Genera graficas comparativas de los benchmarks."""

import os
import matplotlib.pyplot as plt


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# Datos del benchmark
TAMANOS = [1, 5, 10]  # en miles

HEAP_INSERCION = [0.024, 0.284, 0.355]
SEQ_INSERCION = [0.214, 5.008, 17.619]

HEAP_BUSQUEDA = [0.217, 1.369, 2.545]
SEQ_BUSQUEDA = [0.067, 0.690, 0.726]

ESPACIO = [45056, 208896, 417792]  # mismo para ambos


def grafica_insercion():
    plt.figure(figsize=(8, 5))
    plt.plot(TAMANOS, HEAP_INSERCION, "o-", label="Heap File")
    plt.plot(TAMANOS, SEQ_INSERCION, "s-", label="Sequential File")
    plt.xlabel("Tamaño del dataset (miles de registros)")
    plt.ylabel("Tiempo de inserción (s)")
    plt.title("Tiempo de inserción: Heap vs Sequential")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    ruta = os.path.join(RESULTS_DIR, "grafica_insercion.png")
    plt.savefig(ruta)
    plt.close()
    print(f"Guardada: {ruta}")


def grafica_busqueda():
    plt.figure(figsize=(8, 5))
    plt.plot(TAMANOS, HEAP_BUSQUEDA, "o-", label="Heap File")
    plt.plot(TAMANOS, SEQ_BUSQUEDA, "s-", label="Sequential File")
    plt.xlabel("Tamaño del dataset (miles de registros)")
    plt.ylabel("Tiempo de búsqueda (s)")
    plt.title("Tiempo de búsqueda: Heap vs Sequential")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    ruta = os.path.join(RESULTS_DIR, "grafica_busqueda.png")
    plt.savefig(ruta)
    plt.close()
    print(f"Guardada: {ruta}")


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    grafica_insercion()
    grafica_busqueda()
    print("Listo.")


if __name__ == "__main__":
    main()