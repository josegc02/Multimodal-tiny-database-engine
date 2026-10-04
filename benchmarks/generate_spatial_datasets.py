"""Genera datasets reproducibles de comercios sintéticos de Lima para #25."""
from __future__ import annotations
import argparse, csv, json, random, sys
from pathlib import Path
if __package__ in (None, ""): sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.spatial.geometry import Point
ROOT = Path(__file__).resolve().parents[1]; OUTPUT = ROOT / "datasets/spatial/generated"
LIMA_BOUNDS = {"min_lat": -12.30, "max_lat": -11.75, "min_lon": -77.20, "max_lon": -76.80}
CATEGORIAS = ("tienda", "restaurante", "gasolinera", "farmacia", "banco")
SCHEMA = [("id", "int"), ("nombre", "str", 30), ("categoria", "str", 15), ("ubicacion", "point")]
def generate_points(n, seed=42):
    if type(n) is not int or n < 1: raise ValueError("n debe ser un entero positivo")
    rng=random.Random(seed); centers=((-12.0464,-77.0428),(-12.1193,-77.0300),(-11.9870,-77.0620),(-12.0740,-76.9550)); rows=[]
    for ident in range(n):
        if rng.random()<.78:
            lat,lon=centers[ident%len(centers)]; lat+=rng.gauss(0,.018); lon+=rng.gauss(0,.018)
        else: lat=rng.uniform(-12.30,-11.75); lon=rng.uniform(-77.20,-76.80)
        lat=min(-11.75,max(-12.30,lat)); lon=min(-76.80,max(-77.20,lon)); category=CATEGORIAS[ident%len(CATEGORIAS)]
        rows.append({"id":ident,"nombre":f"{category}_{ident:06d}","categoria":category,"ubicacion":Point(lat,lon)})
    return rows
def generate_queries(n=100, seed=7):
    if type(n) is not int or n<1: raise ValueError("n debe ser positivo")
    rng=random.Random(seed); return [{"id":i,"lat":rng.uniform(-12.30,-11.75),"lon":rng.uniform(-77.20,-76.80)} for i in range(n)]
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--sizes",type=int,nargs="+",default=(1000,10000,100000)); parser.add_argument("--queries",type=int,default=100); parser.add_argument("--seed",type=int,default=42); parser.add_argument("--output",type=Path,default=OUTPUT); args=parser.parse_args(argv)
    if any(n<1 for n in args.sizes) or len(set(args.sizes))!=len(args.sizes): parser.error("--sizes debe contener enteros positivos distintos")
    args.output.mkdir(parents=True,exist_ok=True)
    for n in sorted(args.sizes):
        rows=generate_points(n,args.seed)
        with (args.output/f"puntos_{n}.csv").open("w",newline="",encoding="utf-8") as stream:
            w=csv.writer(stream); w.writerow(("id","nombre","categoria","lat","lon")); w.writerows((r["id"],r["nombre"],r["categoria"],f"{r['ubicacion'].lat:.8f}",f"{r['ubicacion'].lon:.8f}") for r in rows)
        with (args.output/f"postgis_puntos_{n}.csv").open("w",newline="",encoding="utf-8") as stream:
            w=csv.writer(stream); w.writerow(("id","nombre","categoria","lon","lat")); w.writerows((r["id"],r["nombre"],r["categoria"],f"{r['ubicacion'].lon:.8f}",f"{r['ubicacion'].lat:.8f}") for r in rows)
        with (args.output/f"cargar_motor_{n}.sql").open("w",encoding="utf-8") as stream:
            stream.write("CREATE TABLE puntos (id INT PRIMARY KEY, nombre VARCHAR(30), categoria VARCHAR(15), ubicacion POINT);\n")
            for start in range(0,n,500): stream.write("INSERT INTO puntos VALUES "+",".join(f"({r['id']},'{r['nombre']}','{r['categoria']}',POINT({r['ubicacion'].lat:.8f},{r['ubicacion'].lon:.8f}))" for r in rows[start:start+500])+";\n")
            stream.write("CREATE INDEX puntos_geo ON puntos (ubicacion) USING RTREE;\n")
    with (args.output/"consultas.csv").open("w",newline="",encoding="utf-8") as stream:
        w=csv.DictWriter(stream,fieldnames=("id","lat","lon")); w.writeheader(); w.writerows(generate_queries(args.queries,args.seed+1))
    (args.output/"metadata.json").write_text(json.dumps({"seed":args.seed,"sizes":sorted(args.sizes),"queries":args.queries,"bounds":LIMA_BOUNDS,"domain":"comercios sintéticos de Lima"},indent=2)+"\n",encoding="utf-8")
if __name__=="__main__": main()
