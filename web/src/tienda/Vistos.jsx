import Foto from './Foto.jsx';
import { precio } from './formato.js';
import { enlace } from './ruta.js';

export default function Vistos({ vistos }) {
  return (
    <div className="pagina">
      <div className="titulo-texto">
        <h1>Vistos recientemente</h1>
        <p className="gris">Los últimos {vistos.length || ''} productos que abriste en este navegador.</p>
      </div>
      <section className="rejilla" aria-label="Productos vistos">
        {vistos.length === 0 && (
          <div className="vacio">
            <span>Todavía no abriste ningún producto.</span>
            <a className="enlace" href={enlace.catalogo()}>Ir al catálogo</a>
          </div>
        )}
        {vistos.map((p) => (
          <a key={p.id} className="tarjeta" href={enlace.ficha(p.id)}>
            <span className="foto"><Foto producto={p} /></span>
            <span className="tarjeta-titulo">{p.titulo}</span>
            <span className="tarjeta-precio num">{precio(p.precio)}</span>
          </a>
        ))}
      </section>
    </div>
  );
}
