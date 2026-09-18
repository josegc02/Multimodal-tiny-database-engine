"""Generación de datasets sintéticos para pruebas de escalabilidad (1K, 10K, 100K registros)."""

import csv
import os
import random

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def generar_dataset(nombre, n):
    """Genera un CSV con n registros aleatorios."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ruta = os.path.join(RESULTS_DIR, f"{nombre}.csv")

    random.seed(42)  # reproducible

    with open(ruta, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "nombre", "saldo"])
        for i in range(1, n + 1):
            writer.writerow([i, f"Cliente{i:06d}", random.randint(0, 10000)])

    print(f"Generado: {ruta} ({n} registros)")


def main():
    print("Generando datasets...")
    generar_dataset("dataset_1k", 1_000)
    generar_dataset("dataset_10k", 10_000)
    generar_dataset("dataset_100k", 100_000)
    print("Listo.")


if __name__ == "__main__":
    main()