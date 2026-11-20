import { useEffect, useState } from 'react';
import { tienda } from '../api.js';
import { cantidad, distancia, estrellas, precio } from './formato.js';
import { nombre as nombreConsola } from './consolas.js';
import Foto from './Foto.jsx';
import { IconoError, IconoUbicacion } from './Iconos.jsx';
import Mapa from './Mapa.jsx';
import Recomendaciones from './Recomendaciones.jsx';
import { enlace } from './ruta.js';
import { guardarUbicacion, leerUbicacion, pedirUbicacion, UTEC } from './ubicacion.js';
import { guardarVisto } from './vistos.js';

const TIENDAS_EN_MAPA = 8;

export default function Ficha({ id, explicar, alVer }) {
  const [producto, setProducto] = useState(null);
  const [error, setError] = useState(null);
  const [ubicacion, setUbicacion] = useState(leerUbicacion);
  const [tiendas, setTiendas] = useState(null);
  const [errorTiendas, setErrorTiendas] = useState(null);
  const [sinStock, setSinStock] = useState([]);      // tiendas más cerca que no lo tienen
  const [avisoUbicacion, setAvisoUbicacion] = useState('');

  const cargar = () => {
    setError(null);
    tienda.producto(id).then((p) => { setProducto(p); alVer(guardarVisto(p)); }).catch(setError);
  };
  useEffect(cargar, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const cargarTiendas = () => {
    setTiendas(null);
    setErrorTiendas(null);
    setSinStock([]);
    Promise.all([
      tienda.tiendasCercanas({ lat: ubicacion.lat, lon: ubicacion.lon, productoId: id, limite: TIENDAS_EN_MAPA }),
      tienda.tiendasCercanas({ lat: ubicacion.lat, lon: ubicacion.lon, limite: 4 }),
    ]).then(([conStock, todas]) => {
      setTiendas(conStock);
      const conProducto = new Set(conStock.map((t) => t.id));
      const limite = conStock[0]?.distancia_m ?? Infinity;
      setSinStock(todas.filter((t) => !conProducto.has(t.id) && t.distancia_m < limite).slice(0, 3));
    }).catch(setErrorTiendas);
  };
  useEffect(cargarTiendas, [id, ubicacion]); // eslint-disable-line react-hooks/exhaustive-deps

  const usarMiUbicacion = () => {
    setAvisoUbicacion('Buscando tu ubicación…');
    pedirUbicacion()
      .then((u) => { setUbicacion(u); guardarUbicacion(u); setAvisoUbicacion(''); })
      .catch((e) => setAvisoUbicacion(e.message));
  };
  const volverAUtec = () => { setUbicacion(UTEC); guardarUbicacion(UTEC); setAvisoUbicacion(''); };

  if (error) {
    return (
      <div className="pagina">
        <h1>{error.estado === 404 ? 'Este producto no existe' : 'No se pudo abrir el producto'}</h1>
        <div className="error" role="alert">
          <IconoError />
          <div><span className="gris">{error.message}</span></div>
          {error.estado !== 404 && <button className="enlace" onClick={cargar} style={{ marginLeft: 'auto' }}>Reintentar</button>}
        </div>
        <a className="enlace" href={enlace.catalogo()}>Volver al catálogo</a>
      </div>
    );
  }
  if (!producto) return <FichaCargando />;

  const partes = (producto.categoria ?? '').split(' > ');
  const cercana = tiendas?.[0];

  return (
    <div className="pagina">
      <section className="cabecera" aria-labelledby="titulo-producto">
        <div className="foto"><Foto producto={producto} alt={producto.titulo} /></div>
        <div className="cabecera-texto">
          <nav className="ruta-cat" aria-label="Categoría">
            {partes.slice(1).map((parte, i) => {
              const ruta = partes.slice(0, i + 2).join(' > ');
              return <a key={ruta} href={enlace.catalogo({ categoria: ruta })}>{i === 0 ? nombreConsola(parte) : parte}</a>;
            })}
          </nav>
          <h1 id="titulo-producto">{producto.titulo}</h1>
          <div className="datos num">
            <span>{estrellas(producto.rating)} de 5 en {cantidad(producto.num_resenas)} reseñas</span>
            {producto.marca && <span>Marca {producto.marca}</span>}
            <span>ASIN {producto.asin}</span>
          </div>
          {producto.descripcion && <p className="descripcion">{producto.descripcion}</p>}
        </div>
        <div className="compra">
          <span className="precio num">{precio(producto.precio)}</span>
          <a className="btn2" href={`https://www.amazon.com/dp/${producto.asin}`} target="_blank" rel="noreferrer">Ver en Amazon</a>
        </div>
      </section>

      <div className="rejilla6">
        <section className="panel span2" aria-labelledby="donde">
          <div className="panel-cabeza"><h2 id="donde">Dónde comprarlo</h2></div>
          {errorTiendas && (
            <div className="error" role="alert">
              <IconoError /><div><strong>No se pudieron cargar las tiendas.</strong></div>
              <button className="enlace" onClick={cargarTiendas} style={{ marginLeft: 'auto' }}>Reintentar</button>
            </div>
          )}
          {!tiendas && !errorTiendas && <TiendasCargando />}
          {tiendas?.length === 0 && <p className="gris">Ninguna tienda de Lima tiene stock de este producto.</p>}
          {cercana && (
            <>
              <div>
                <p className="gris">La más cercana con stock</p>
                <p className="cercana-nombre">{cercana.nombre}</p>
              </div>
              {(cercana.direccion || cercana.distrito) && (
                <p className="gris">{[cercana.direccion, cercana.distrito].filter(Boolean).join(', ')}</p>
              )}
              <p className="cifra num">{distancia(cercana.distancia_m)}<small>de {ubicacion.nombre}, {cantidad(cercana.unidades)} en stock</small></p>
              <a className="enlace" target="_blank" rel="noreferrer"
                 href={`https://www.openstreetmap.org/directions?from=${ubicacion.lat},${ubicacion.lon}&to=${cercana.ubicacion.lat},${cercana.ubicacion.lon}`}>
                Cómo llegar
              </a>
              {tiendas.length > 1 && (
                <ul className="lista-tiendas">
                  {tiendas.slice(1, 5).map((t) => (
                    <li key={t.id}>
                      <span>{t.nombre}</span>
                      <span className="num">{distancia(t.distancia_m)}</span>
                      <span className="num">{cantidad(t.unidades)} u.</span>
                    </li>
                  ))}
                </ul>
              )}
              {tiendas.length === 1 && <p className="gris">Es la única tienda de Lima con stock.</p>}
              {sinStock.length > 0 && (
                <div>
                  <p className="subtitulo">Más cerca, pero sin stock</p>
                  <ul className="lista-tiendas">
                    {sinStock.map((t) => (
                      <li key={t.id}>
                        <span>{t.nombre}{t.distrito && <small>{t.distrito}</small>}</span>
                        <span className="num">{distancia(t.distancia_m)}</span>
                        <span className="num">0 u.</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </section>

        <section className="panel span4" aria-labelledby="mapa-titulo">
          <div className="panel-cabeza">
            <h2 id="mapa-titulo">Tiendas con stock cerca de {ubicacion.nombre}</h2>
            <div className="ubicacion">
              {ubicacion.nombre === UTEC.nombre
                ? <button className="btn2" onClick={usarMiUbicacion}><IconoUbicacion />Usar mi ubicación</button>
                : <button className="btn2" onClick={volverAUtec}>Volver a UTEC</button>}
            </div>
          </div>
          {avisoUbicacion && <p className="gris" aria-live="polite">{avisoUbicacion}</p>}
          <Mapa ubicacion={ubicacion} tiendas={tiendas ?? []} cercanaId={cercana?.id} />
          <div className="leyenda">
            <span><i style={{ background: 'var(--tinta)' }} />{ubicacion.nombre === UTEC.nombre ? 'UTEC (tu punto de partida)' : 'Tú'}</span>
            <span><i style={{ background: 'var(--tono)' }} />Tienda con stock, la más grande es la más cercana</span>
          </div>
        </section>
      </div>

      <Recomendaciones id={id} explicarAlAbrir={explicar} />
    </div>
  );
}

function FichaCargando() {
  return (
    <div className="pagina" aria-busy="true">
      <h1 className="oculto">Cargando el producto</h1>
      <div className="cabecera">
        <div className="foto esqueleto" style={{ border: 0 }} />
        <div className="cabecera-texto">
          <span className="esqueleto" style={{ height: 12, width: 220 }} />
          <span className="esqueleto" style={{ height: 22, width: '80%' }} />
          <span className="esqueleto" style={{ height: 14, width: 320 }} />
          <span className="esqueleto" style={{ height: 14, width: '70%' }} />
        </div>
        <div className="compra"><span className="esqueleto" style={{ height: 28, width: 96 }} /></div>
      </div>
    </div>
  );
}

function TiendasCargando() {
  return (
    <div aria-hidden="true" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <span className="esqueleto" style={{ height: 14, width: 140 }} />
      <span className="esqueleto" style={{ height: 22, width: '80%' }} />
      <span className="esqueleto" style={{ height: 28, width: 110 }} />
    </div>
  );
}
