"""Genera un INSERT de 1000 filas para pegarlo en el frontend."""

from pathlib import Path

sql = "INSERT INTO empleados_seq (id, nombre) VALUES\n"
sql += ",\n".join(
    f"({row_id}, 'Empleado_{row_id}')"
    for row_id in range(1, 1001)
)
sql += ";\n"

Path("insert_1000.sql").write_text(sql, encoding="utf-8")
print("Creado insert_1000.sql con 1000 filas")
