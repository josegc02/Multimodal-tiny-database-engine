import { useEffect, useState } from 'react';
import { tienda } from '../api.js';
import { cantidad } from './formato.js';
import { IconoBuscar, Marca } from './Iconos.jsx';
import { enlace, ir, useRuta } from './ruta.js';
import { leerVistos } from './vistos.js';
import Catalogo from './Catalogo.jsx';
import Ficha from './Ficha.jsx';
import Vistos from './Vistos.jsx';

export default function App() {
  const ruta = useRuta();
  const [categorias, setCategorias] = useState(null);   // GET /categorias, una vez
  const [errorCategorias, setErrorCategorias] = useState(null);
  const [vistos, setVistos] = useState(leerVistos);
  const [busqueda, setBusqueda] = useState(ruta.vista === 'catalogo' ? ruta.q : '');

  const cargarCategorias = () => {
    setErrorCategorias(null);
    tienda.categorias().then(setCategorias).catch(setErrorCategorias);
  };
  useEffect(cargarCategorias, []);
  useEffect(() => { if (ruta.vista === 'catalogo') setBusqueda(ruta.q); }, [ruta]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [ruta.vista, ruta.id]);

  const total = categorias ? categorias.reduce((n, c) => n + c.productos, 0) : null;
  const buscar = (evento) => {
    evento.preventDefault();
    const filtros = ruta.vista === 'catalogo' ? ruta : {};
    ir(enlace.catalogo({ ...filtros, q: busqueda.trim() }));
  };

  return (
    <div className="marco">
      <header className="barra">
        <a className="marca" href={enlace.catalogo()}>
          <Marca />
          <span style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="marca-nombre">Partida</span>
            <span className="marca-sub">Videojuegos en Lima</span>
          </span>
        </a>
        <form className="buscador" role="search" onSubmit={buscar}>
          <IconoBuscar />
          <label className="oculto" htmlFor="buscar">Buscar en el catálogo</label>
          <input id="buscar" type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)}
                 placeholder={total ? `Buscar entre ${cantidad(total)} productos` : 'Buscar productos'} autoComplete="off" />
        </form>
        <nav className="barra-der" aria-label="Secciones">
          <a href={enlace.catalogo()} aria-current={ruta.vista === 'catalogo' ? 'page' : undefined}>Catálogo</a>
          <a href={enlace.vistos} aria-current={ruta.vista === 'vistos' ? 'page' : undefined}>
            Vistos{vistos.length > 0 && <span className="gris num" style={{ marginLeft: 6 }}>{vistos.length}</span>}
          </a>
        </nav>
      </header>

      <main className="hoja">
        {ruta.vista === 'catalogo' && (
          <Catalogo ruta={ruta} categorias={categorias} errorCategorias={errorCategorias} reintentar={cargarCategorias} />
        )}
        {ruta.vista === 'ficha' && <Ficha key={ruta.id} id={ruta.id} alVer={setVistos} />}
        {ruta.vista === 'vistos' && <Vistos vistos={vistos} />}
      </main>

      <footer className="pie">
        <span>Productos, fotos y compras: Amazon Reviews 2023 (McAuley Lab, UCSD), categoría Video Games.</span>
        <span>Tiendas: OpenStreetMap. Stock generado para la demo.</span>
        <span>Cada consulta corre en el motor del curso (SPIMI, HNSW, R-Tree, hash y B+).</span>
      </footer>
    </div>
  );
}
