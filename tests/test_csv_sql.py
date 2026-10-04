import os
import shutil
import tempfile
import unittest

import frontend.motor as motor_module
from frontend.csv_sql import sql_para_csv


class TestSqlParaCsv(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _csv(self, nombre, contenido, encoding="utf-8"):
        path = os.path.join(self.dir, nombre)
        with open(path, "w", encoding=encoding, newline="") as stream:
            stream.write(contenido)
        return path

    def test_infiere_tipos_pk_y_copy(self):
        path = self._csv("Alumnos 2025.csv",
                         'id,nombre,carrera_id,nota\n8,Luis Torres,2,15.5\n3,"Pérez, Juan",1,14\n')
        sql = sql_para_csv(path, base_dir=self.dir)
        self.assertIn("CREATE TABLE alumnos_2025 (id INT PRIMARY KEY, nombre VARCHAR(20), "
                      "carrera_id INT, nota FLOAT);", sql)
        self.assertIn("COPY alumnos_2025 FROM 'Alumnos 2025.csv' WITH (FORMAT csv, HEADER);", sql)

    def test_tabla_existente_solo_copy(self):
        path = self._csv("ventas.csv", "id,total\n1,10\n2,20\n")
        sql = sql_para_csv(path, {"ventas"}, base_dir=self.dir)
        self.assertNotIn("CREATE TABLE", sql)
        self.assertIn("COPY ventas FROM 'ventas.csv'", sql)

    def test_delimitador_latin1_y_palabras_reservadas(self):
        path = self._csv("datos.csv", "count;descripción\n1;año\n2;niño\n", encoding="latin-1")
        sql = sql_para_csv(path, base_dir=self.dir)
        self.assertIn("count_ INT PRIMARY KEY", sql)
        self.assertIn("DELIMITER ';'", sql)
        self.assertIn("ENCODING 'latin-1'", sql)

    def test_el_sql_generado_se_ejecuta_en_el_motor(self):
        demo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, demo, True)
        original = motor_module.DEMO_DIR
        motor_module.DEMO_DIR = demo
        self.addCleanup(setattr, motor_module, "DEMO_DIR", original)
        path = self._csv("productos_csv.csv", "id;nombre;precio\n1;Silla;45.5\n2;Mesa;120\n3;Lámpara;30\n")
        motor = motor_module.Motor()
        self.addCleanup(motor.cerrar)
        resultado = motor.ejecutar(sql_para_csv(path, set(motor.catalog.tables)))
        self.assertFalse(resultado.tiene_error, resultado.error)
        self.assertEqual(sorted(resultado.filas), [(1, "Silla", 45.5), (2, "Mesa", 120.0), (3, "Lámpara", 30.0)])


if __name__ == "__main__":
    unittest.main()
