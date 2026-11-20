import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { autoresCortos, entero, esClase, paginas, sinCorreos, TEMAS } from '../formato.js';
import { IconoError } from '../Iconos.jsx';

export default function Documento({ id, volverBiblioteca, preguntarSobre }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDoc(null);
    setError(null);
    api.documento(id).then(setDoc).catch(setError);
  }, [id]);

  if (error) {
    return (
      <div className="pagina">
        <a href={volverBiblioteca}>← Biblioteca</a>
        <div className="panel respuesta" role="alert">
          <div className="error-bloque"><IconoError /><span>{error.message}</span></div>
        </div>
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="pagina" aria-busy="true">
        <a href={volverBiblioteca}>← Biblioteca</a>
        <div className="esqueleto" style={{ height: 28, width: '70%' }} />
        <div className="esqueleto" style={{ width: '40%' }} />
      </div>
    );
  }

  const clase = esClase(doc);
  const palabras = doc.fragmentos.reduce((s, f) => s + f.palabras, 0);
  const meta = [autoresCortos(doc.autores), doc.anio, doc.arxiv_id && `arXiv ${doc.arxiv_id}`, TEMAS[doc.tema] ?? doc.tema,
    `${entero(doc.fragmentos.length)} fragmentos`].filter(Boolean).join(' · ');

  return (
    <div className="pagina">
      <a href={volverBiblioteca} style={{ alignSelf: 'flex-start' }}>← Biblioteca</a>
      <div className="titulo-fila">
        <div className="titulo-texto">
          <h1 style={{ maxWidth: '60ch' }}>{doc.titulo}</h1>
          <span className="sub num">{meta}</span>
        </div>
        <div className="acciones">
          <a className="btn2" href={api.urlPdf(doc.id)} target="_blank" rel="noreferrer">Abrir PDF</a>
          {doc.url && <a className="btn2" href={doc.url} target="_blank" rel="noreferrer">arXiv</a>}
          <button className="btn" onClick={() => preguntarSobre(`¿De qué trata «${doc.titulo}»?`)}>Preguntar sobre este documento</button>
        </div>
      </div>

      <div className="columnas">
        <section className="panel principal" aria-label="Fragmentos" style={{ gap: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '16px 20px 8px' }}>
            <h2>Fragmentos</h2>
            <span className="sub num" style={{ fontSize: 12 }}>{entero(palabras)} palabras · 200–500 por fragmento</span>
          </div>
          <div className="tabla-marco">
            <table className="tabla-fragmentos">
              <thead>
                <tr>
                  <th className="num" style={{ width: 40 }}>Nº</th>
                  <th className="num" style={{ width: 96 }}>{clase ? 'Diaps.' : 'Páginas'}</th>
                  <th className="num" style={{ width: 80 }}>Palabras</th>
                  <th>Texto</th>
                </tr>
              </thead>
              <tbody>
                {doc.fragmentos.map((f) => (
                  <tr key={f.id}>
                    <td className="num">{f.orden}</td>
                    <td className="num">
                      <a href={api.urlPdf(doc.id, f.pagina)} target="_blank" rel="noreferrer">{paginas(f, clase).replace(/^\D+/, '')}</a>
                    </td>
                    <td className="num" style={{ color: 'var(--tinta-2)' }}>{f.palabras}</td>
                    <td style={{ fontSize: 13, lineHeight: '19px', color: 'var(--tinta-2)' }}>
                      <a className="fragmento-ubicacion" href={api.urlPdf(doc.id, f.pagina)} target="_blank" rel="noreferrer">
                        Fragmento {f.orden} · {paginas(f, clase)}
                      </a>
                      {sinCorreos(f.texto).slice(0, 280)}{f.texto.length > 280 ? '…' : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel lateral" aria-label="Datos del documento" style={{ padding: '16px 20px 20px', gap: 8 }}>
          <h2>{clase || !doc.abstract ? 'Datos' : 'Abstract'}</h2>
          {doc.abstract && <p style={{ fontSize: 13, lineHeight: '20px', color: 'var(--tinta-2)' }}>{doc.abstract}</p>}
          <span className="sub" style={{ fontSize: 12 }}>Licencia: {doc.licencia || '—'}</span>
          {doc.categoria && <span className="sub" style={{ fontSize: 12 }}>Categoría: {doc.categoria}</span>}
        </section>
      </div>
    </div>
  );
}
