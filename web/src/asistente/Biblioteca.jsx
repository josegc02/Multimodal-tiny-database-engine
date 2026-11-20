import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { autoresCortos, entero, esClase, TEMAS } from '../formato.js';
import { IconoBuscar, IconoError } from '../Iconos.jsx';
import { conFiltros, enlace } from '../ruta.js';

const PASO = 50; // filas por tanda

export default function Biblioteca({ filtros, cambiarRuta }) {
  const [documentos, setDocumentos] = useState(null);
  const [error, setError] = useState(null);
  const busqueda = filtros.get('titulo') ?? '';
  const tipo = ['papers', 'clases'].includes(filtros.get('tipo')) ? filtros.get('tipo') : 'todos';
  const tema = filtros.get('tema') ?? '';
  const anio = filtros.get('anio') ?? '';
  const autor = filtros.get('autor') ?? '';
  const [visibles, setVisibles] = useState(PASO);

  function cambiarFiltro(nombre, valor) {
    const nuevos = new URLSearchParams(filtros);
    if (valor) nuevos.set(nombre, valor);
    else nuevos.delete(nombre);
    cambiarRuta(conFiltros(enlace.biblioteca, nuevos));
  }

  const cargar = () => { setError(null); api.documentos().then(setDocumentos).catch(setError); };
  useEffect(cargar, []);
  useEffect(() => setVisibles(PASO), [busqueda, tipo, tema, anio, autor]);

  const totales = useMemo(() => {
    const lista = documentos ?? [];
    return { todos: lista.length, papers: lista.filter((d) => !esClase(d)).length, clases: lista.filter(esClase).length };
  }, [documentos]);
  const temas = useMemo(() => [...new Set((documentos ?? []).map((d) => d.tema))].sort(
    (a, b) => (TEMAS[a] ?? a).localeCompare(TEMAS[b] ?? b)), [documentos]);
  const anios = useMemo(() => [...new Set((documentos ?? []).map((d) => d.anio).filter(Boolean))]
    .sort((a, b) => b - a), [documentos]);
  const filas = useMemo(() => {
    const texto = busqueda.trim().toLowerCase();
    return (documentos ?? [])
      .filter((d) => tipo === 'todos' || (tipo === 'clases' ? esClase(d) : !esClase(d)))
      .filter((d) => !tema || d.tema === tema)
      .filter((d) => !anio || String(d.anio) === anio)
      .filter((d) => !autor.trim() || (d.autores ?? '').toLowerCase().includes(autor.trim().toLowerCase()))
      .filter((d) => !texto || d.titulo.toLowerCase().includes(texto));
  }, [documentos, busqueda, tipo, tema, anio, autor]);

  return (
    <div className="pagina">
      <div className="titulo-texto">
        <h1>Biblioteca</h1>
        <p className="sub">Explora los papers y las clases que puede consultar el asistente.</p>
      </div>

      <div className="herramientas">
        <label className="buscador">
          <IconoBuscar />
          <span className="oculto">Buscar por título</span>
          <input value={busqueda} onChange={(e) => cambiarFiltro('titulo', e.target.value)} placeholder="Título" />
        </label>
        <div className="segmentos" role="group" aria-label="Tipo de documento">
          {[['todos', 'Todos'], ['papers', 'Papers'], ['clases', 'Clases']].map(([id, texto]) => (
            <button key={id} aria-pressed={tipo === id} onClick={() => cambiarFiltro('tipo', id === 'todos' ? '' : id)}>
              {texto} <span className="num sub">{documentos ? totales[id] : ''}</span>
            </button>
          ))}
        </div>
        <label className="filtro-biblioteca">
          <span id="filtro-tema">Tema</span>
          <select className="selector" aria-labelledby="filtro-tema" value={tema} onChange={(e) => cambiarFiltro('tema', e.target.value)}>
            <option value="">Todos</option>
            {temas.map((t) => <option key={t} value={t}>{TEMAS[t] ?? t}</option>)}
          </select>
        </label>
        <label className="filtro-biblioteca">
          <span id="filtro-anio">Año</span>
          <select className="selector" aria-labelledby="filtro-anio" value={anio} onChange={(e) => cambiarFiltro('anio', e.target.value)}>
            <option value="">Todos</option>
            {anios.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="filtro-biblioteca">
          Autor
          <input className="selector" value={autor} onChange={(e) => cambiarFiltro('autor', e.target.value)} />
        </label>
      </div>

      <div className="panel">
        {error && (
          <div className="respuesta" role="alert">
            <div className="error-bloque"><IconoError /><span>{error.message}</span></div>
            <div className="acciones"><button className="btn2" onClick={cargar}>Reintentar</button></div>
          </div>
        )}
        {!error && (
          <div className="tabla-marco">
            <table className="tabla-biblioteca">
              <thead>
                <tr>
                  <th>Título</th>
                  <th>Tipo</th>
                  <th>Tema</th>
                  <th className="num">Año</th>
                  <th className="num">Fragmentos</th>
                </tr>
              </thead>
              <tbody>
                {!documentos && [1, 2, 3, 4, 5].map((n) => (
                  <tr key={n}><td colSpan={5}><div className="esqueleto" style={{ width: `${60 + n * 6}%` }} /></td></tr>
                ))}
                {documentos && filas.length === 0 && (
                  <tr><td colSpan={5} className="sub">Ningún documento coincide con estos filtros.</td></tr>
                )}
                {filas.slice(0, visibles).map((d) => (
                  <tr key={d.id}>
                    <td>
                      <a href={enlace.documento(d.id, filtros)} className="titulo-documento">{d.titulo}</a>
                      <span className="celda-sub">{autoresCortos(d.autores)}</span>
                      <span className="celda-sub ficha-movil">
                        {[esClase(d) ? 'Clase' : 'Paper', TEMAS[d.tema] ?? d.tema, d.anio,
                          `${entero(d.fragmentos)} ${d.fragmentos === 1 ? 'fragmento' : 'fragmentos'}`].filter(Boolean).join(' · ')}
                      </span>
                    </td>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--tinta-2)' }}>{esClase(d) ? 'Clase' : 'Paper'}</td>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--tinta-2)' }}>{TEMAS[d.tema] ?? d.tema}</td>
                    <td className="num">{d.anio}</td>
                    <td className="num">{entero(d.fragmentos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {documentos && (
              <div className="pie-tabla num">
                <span>{filas.length ? `1–${Math.min(visibles, filas.length)} de ${entero(filas.length)} documentos` : ''}</span>
                {visibles < filas.length && <button className="texto-btn" style={{ fontSize: 12 }} onClick={() => setVisibles(visibles + PASO)}>Cargar {Math.min(PASO, filas.length - visibles)} más</button>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
