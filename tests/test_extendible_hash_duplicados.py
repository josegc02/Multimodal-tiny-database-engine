"""Hash extensible con claves muy repetidas (una llave foránea): mismo resultado, sin costo cuadrático."""
import random
import time

from engine.indexes.extendible_hash import ExtendibleHash
from engine.storage.heap_file import RID


def test_mismas_busquedas_que_un_diccionario_con_altas_y_bajas():
    for semilla in range(20):
        r = random.Random(semilla)
        h, modelo = ExtendibleHash(r.choice([2, 4, 8, 32])), {}
        claves = r.choice([3, 50, 2000])
        vivos = []
        for i in range(3000):
            if vivos and r.random() < 0.15:
                clave, rid = vivos.pop(r.randrange(len(vivos)))
                h.delete(clave, rid)
                modelo[clave].discard(rid)
            else:
                clave, rid = r.randrange(claves), RID(i, 0, "main")
                h.insert(clave, rid)
                modelo.setdefault(clave, set()).add(rid)
                vivos.append((clave, rid))
        for clave, rids in modelo.items():
            assert set(h.search(clave)) == rids, (semilla, clave)
        assert len(h) == sum(len(v) for v in modelo.values())


def test_carga_en_bloque_con_duplicados_es_lineal():
    # Antes: cada par recorría la cadena de overflow de su clave (~30 s para 100,000 pares).
    h = ExtendibleHash(32)
    inicio = time.perf_counter()
    for i in range(100_000):
        h._insert(i % 40, RID(i, 0, "main"), False)
    assert time.perf_counter() - inicio < 5
    assert len(h.search(7)) == 2500


def test_las_caches_se_descartan_al_reconstruir_el_bucket():
    h = ExtendibleHash(2)
    for i in range(50):
        h.insert("x", RID(i, 0, "main"))
    h.delete("x", RID(0, 0, "main"))          # refill: la cadena cambia
    h.insert("x", RID(99, 0, "main"))
    h.insert("y", RID(100, 0, "main"))        # otra clave en el bucket lleno: puede dividir
    assert len(h.search("x")) == 50 and h.search("y") == [RID(100, 0, "main")]
