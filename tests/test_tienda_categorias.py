"""Limpieza de la metadata de Amazon: fuera de tema, consolas contradictorias y rutas promocionales."""
from tienda.amazon import producto
from tienda.categorias import consola_de_ruta, fuera_de_tema, normalizar
from tienda.recomendaciones import plataformas


def test_fuera_de_tema_por_main_category_formato_campos_y_titulo():
    assert fuera_de_tema({"main_category": "Books", "title": "Born a Crime"})  # el caso que se vio en la tienda
    assert fuera_de_tema({"main_category": "Video Games", "details": {"Type of item": "Blu-ray"}, "title": "Planet Earth II"})
    assert fuera_de_tema({"main_category": "Video Games", "details": {"Runtime": "1 h"}, "title": "Office Space"})
    assert fuera_de_tema({"main_category": "Video Games", "title": "Leverage Seasons 1-5 Complete TV Series DVD Collection"})
    # Juegos y accesorios no se tocan, aunque Amazon los clasifique en otra main_category.
    assert fuera_de_tema({"main_category": "Video Games", "details": {"Type of item": "Audio CD"}, "title": "Wii Sports"}) is None
    assert fuera_de_tema({"main_category": "Computers", "title": "Razer Naga X Gaming Mouse"}) is None
    assert fuera_de_tema({"main_category": "Video Games", "title": "The Elder Scrolls V: Skyrim (PC DVD)"}) is None


def test_producto_descarta_libros():
    meta = {"parent_asin": "0399588175", "title": "Born a Crime", "main_category": "Books", "price": "12.0",
            "description": ["palabra " * 20], "images": [{"large": "https://x/a.jpg"}],
            "categories": ["Video Games", "PC", "Games"]}
    assert producto(meta) is None
    assert producto({**meta, "main_category": "Video Games"})["categoria"] == "Video Games > PC > Games"


def test_switch_solo_cuando_es_la_consola():
    assert plataformas("Razer Naga X Gaming Mouse, Optical Switch", "") == set()
    assert plataformas("Mechanical Keyboard with Blue Switches", "") == set()
    for titulo in ("Mario Kart 8 Deluxe - Nintendo Switch", "Pro Controller for Switch", "Switch OLED Case", "Switch/Switch Lite Grip"):
        assert plataformas(titulo, "") == {"switch"}, titulo


def test_consola_del_titulo_corrige_la_ruta():
    ds = ["Video Games", "Legacy Systems", "Nintendo Systems", "Nintendo DS", "Accessories", "Cases & Storage"]
    assert normalizar(ds, "Daydayup Switch Carrying Case Compatible with Nintendo Switch") == \
        "Video Games > Nintendo Switch > Accessories > Cases & Storage"
    assert normalizar(["Video Games", "PlayStation 4", "Accessories"], "PS5 Controller Charging Station") == \
        "Video Games > PlayStation 5 > Accessories"
    # Sin contradicción, o con más de una consola en el título, la ruta de Amazon se respeta.
    assert normalizar(["Video Games", "PC", "Accessories", "Gaming Mice"], "Razer Naga X, Optical Switch") == \
        "Video Games > PC > Accessories > Gaming Mice"
    assert normalizar(["Video Games", "PlayStation 4"], "Charger for PS4 and PS5 controllers") == "Video Games > PlayStation 4"


def test_rutas_promocionales_no_son_consolas():
    assert normalizar(["Video Games", "Game Genre of the Month"], "Mario Kart 8 Deluxe - Nintendo Switch") == \
        "Video Games > Nintendo Switch"
    assert normalizar(["Video Games", "Ubisoft"], "Assassin's Creed Collection") == "Video Games"
    assert normalizar([], "Algo") == "Video Games"
    assert consola_de_ruta("Video Games > Legacy Systems > Nintendo Systems > Wii U > Games") == "wii u"
    assert normalizar(["Video Games", "Legacy Systems", "Sega Systems", "Sega Game Gear", "Games"],
                      "NexiGo PS5 Accessories Horizontal Stand") == "Video Games > PlayStation 5 > Games"


def test_lista_de_excluidos_revisados_a_mano():
    from tienda.categorias import EXCLUIDOS
    assert fuera_de_tema({"parent_asin": "B07WMTHLTH", "main_category": "Cell Phones & Accessories", "title": "Apple Watch Charger"})
    assert all(len(asin) == 10 for asin in EXCLUIDOS)
