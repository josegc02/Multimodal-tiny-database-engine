import tkinter as tk
import unittest
from unittest.mock import patch

from frontend.panel_consultas import PanelConsultas


class TestPegarEditor(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Sin pantalla: {error}")
        self.addCleanup(self.root.destroy)
        self.panel = PanelConsultas(self.root)
        self.panel.pack()
        self.root.update()
        self.editor = self.panel.editor
        self.panel.set_sql("SELECT cuentas FROM tabla")
        self.editor.edit_reset()

    def test_pegar_reemplaza_seleccion_aunque_cursor_este_al_final_y_deshace(self):
        self.editor.tag_add("sel", "1.7", "1.14")
        self.editor.mark_set("insert", "end-1c")
        with patch.object(self.editor, "clipboard_get", return_value="productos"):
            self.editor.event_generate("<<Paste>>")
            self.root.update()
        self.assertEqual(self.editor.get("1.0", "end-1c"), "SELECT productos FROM tabla")
        self.panel._deshacer(None)
        self.assertEqual(self.editor.get("1.0", "end-1c"), "SELECT cuentas FROM tabla")
        self.panel._rehacer(None)
        self.assertEqual(self.editor.get("1.0", "end-1c"), "SELECT productos FROM tabla")

    def test_sin_seleccion_inserta_en_el_cursor(self):
        self.editor.mark_set("insert", "1.7")
        with patch.object(self.editor, "clipboard_get", return_value="nueva_\n"):
            self.editor.event_generate("<<Paste>>")
            self.root.update()
        self.assertEqual(self.editor.get("1.0", "end-1c"), "SELECT nueva_\ncuentas FROM tabla")

    def test_portapapeles_no_disponible_no_elimina_seleccion(self):
        self.editor.tag_add("sel", "1.7", "1.14")
        with patch.object(self.editor, "clipboard_get", side_effect=tk.TclError("sin texto")):
            self.editor.event_generate("<<Paste>>")
            self.root.update()
        self.assertEqual(self.editor.get("1.0", "end-1c"), "SELECT cuentas FROM tabla")
        self.assertTrue(self.editor.tag_ranges("sel"))
