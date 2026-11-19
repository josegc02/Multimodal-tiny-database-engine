import { useState } from 'react';
import { esClase, paginas, referencia } from '../formato.js';

// "Cómo se respondió": lo que hizo nuestro motor para esta pregunta, plegable.
// El gráfico de candidatos cambia con cada consulta: muestra los fragmentos que BM25
// devolvió, cuáles pasaron el filtro y por qué se descartaron los demás.
const ESTADOS = {
  elegido: { nombre: 'Elegido', clase: 'barra-elegido' },
  por_documento: { nombre: 'Ya hay 2 de su documento', clase: 'barra-documento' },
  sobra: { nombre: 'Sobra: ya están las fuentes', clase: 'barra-sobra' },
  umbral: { nombre: 'Bajo el umbral', clase: 'barra-umbral' },
};
const FILAS = 12;
const CLAVE_ABIERTA = 'bd2.asistente.traza-abierta';

// Abierta por defecto con VITE_TRAZA_ABIERTA=1 (para proyectar en la exposición);
// si no, recuerda lo último que eligió esta persona.
function leerAbierta() {
  if (import.meta.env.VITE_TRAZA_ABIERTA === '1') return true;
  try { return window.localStorage.getItem(CLAVE_ABIERTA) === '1'; } catch { return false; }
}
function guardarAbierta(abierta) {
  try { window.localStorage.setItem(CLAVE_ABIERTA, abierta ? '1' : '0'); } catch { /* sin almacenamiento */ }
}

export default function Traza({ datos }) {
  const { traza, consulta, fragmentos } = datos;
  const candidatos = traza.candidatos ?? [];
  const [todas, setTodas] = useState(false);
  const [abierta] = useState(leerAbierta);
  const segundosMotor = traza.ms_motor / 1000;

  return (
    <details className="panel traza" open={abierta} onToggle={(e) => guardarAbierta(e.currentTarget.open)}>
      <summary>
        <span className="traza-titulo">Cómo se respondió</span>
        <span className="traza-resumen num">
          {candidatos.length} candidatos → {fragmentos.length} fuente{fragmentos.length === 1 ? '' : 's'}
          {' '}· {traza.ms_motor.toFixed(0)} ms en el motor · {traza.s_total.toFixed(1)} s en total
        </span>
        <svg className="chevron" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </summary>

      <div className="traza-cuerpo">
        <ol className="flujo" aria-label="Pasos">
          <Paso cifra={consulta.split(' ').filter(Boolean).length} unidad="palabras clave"
                detalle={consulta} pie={traza.palabras_con_llm ? `el LLM · ${traza.s_palabras?.toFixed(1)} s` : 'glosario local'} />
          <Paso cifra={candidatos.length} unidad="candidatos" detalle="MATCH … USING BM25 sobre fragmentos.texto (SPIMI)"
                pie={`motor · ${traza.ms_motor.toFixed(0)} ms`} destacado />
          <Paso cifra={fragmentos.length} unidad={fragmentos.length === 1 ? 'fuente' : 'fuentes'}
                detalle={`umbral del ${Math.round(traza.umbral_relativo * 100)} % · máx. ${traza.max_por_documento} por documento`}
                pie={`${traza.documentos} documento${traza.documentos === 1 ? '' : 's'}`} />
          <Paso cifra={traza.s_redaccion == null ? '—' : `${traza.s_redaccion.toFixed(1)} s`} unidad="redacción"
                detalle={traza.modelo ?? 'Sin LLM: solo los fragmentos'} pie={`${(datos.citas ?? []).length} citas`} />
        </ol>

        {candidatos.length > 0 && (
          <Candidatos candidatos={todas ? candidatos : candidatos.slice(0, FILAS)} total={candidatos.length} k={fragmentos.length}
                      umbral={traza.umbral} verTodas={() => setTodas(!todas)} todas={todas} />
        )}

        <Tiempo partes={[
          ['Palabras clave (LLM)', traza.s_palabras ?? 0, 'tiempo-llm'],
          ['Motor: BM25 y papers', segundosMotor, 'tiempo-motor'],
          ['Redacción (LLM)', traza.s_redaccion ?? 0, 'tiempo-llm2'],
        ]} total={traza.s_total} />

        <div className="traza-bloque">
          <h3>Consultas SQL</h3>
          <div className="sql">
            {traza.sql.map((sentencia) => <pre key={sentencia}>{formatear(sentencia)}</pre>)}
          </div>
        </div>
      </div>
    </details>
  );
}

function Paso({ cifra, unidad, detalle, pie, destacado }) {
  return (
    <li className="paso-flujo" data-destacado={destacado || undefined}>
      <span className="paso-cifra num">{cifra}</span>
      <span className="paso-unidad">{unidad}</span>
      <span className="paso-detalle" title={detalle}>{detalle}</span>
      <span className="paso-pie num">{pie}</span>
    </li>
  );
}

function Candidatos({ candidatos, total, umbral, verTodas, todas, k }) {
  const maximo = Math.max(...candidatos.map((c) => c.puntaje), umbral, 1);
  const enUso = new Set(candidatos.map((c) => c.estado));
  return (
    <figure className="traza-bloque" style={{ margin: 0 }}>
      <div className="grafico-cabeza">
        <h3>Puntajes BM25 de los candidatos</h3>
        <ul className="leyenda">
          {Object.entries(ESTADOS).filter(([id]) => enUso.has(id)).map(([id, e]) => (
            <li key={id}><span className={`muestra ${e.clase}`} />{id === 'sobra' ? `Sobra: ya hay ${k} fuentes` : e.nombre}</li>
          ))}
          <li><span className="muestra-umbral" />Umbral {umbral.toFixed(1)}</li>
        </ul>
      </div>
      <div className="grafico" role="img"
           aria-label={`${total} candidatos; ${candidatos.filter((c) => c.estado === 'elegido').length} elegidos; umbral ${umbral.toFixed(1)}`}>
        {candidatos.map((c) => (
          <div key={c.id} className="fila-grafico" data-estado={c.estado}>
            <span className="fila-n num">{c.n ?? ''}</span>
            <span className="fila-nombre" title={c.titulo}>{referencia(c)} · {paginas(c, esClase(c))}</span>
            <span className="fila-pista">
              <span className={`fila-barra ${ESTADOS[c.estado].clase}`} style={{ width: `${(c.puntaje / maximo) * 100}%` }} />
              <span className="linea-umbral" style={{ left: `${(umbral / maximo) * 100}%` }} />
            </span>
            <span className="fila-valor num">{c.puntaje.toFixed(1)}</span>
          </div>
        ))}
      </div>
      {total > FILAS && (
        <button className="texto-btn" style={{ fontSize: 12, alignSelf: 'flex-start' }} onClick={verTodas}>
          {todas ? 'Ver solo los primeros' : `Ver los ${total} candidatos`}
        </button>
      )}
    </figure>
  );
}

function Tiempo({ partes, total }) {
  const resto = Math.max(total - partes.reduce((s, [, v]) => s + v, 0), 0);
  const todas = [...partes, ['Red y API', resto, 'tiempo-resto']].filter(([, v]) => v > 0.005);
  return (
    <div className="traza-bloque">
      <h3>Dónde se fue el tiempo <span className="sub num" style={{ fontWeight: 400 }}>· {total.toFixed(1)} s</span></h3>
      <div className="tiempo" role="img" aria-label={todas.map(([n, v]) => `${n} ${v.toFixed(2)} s`).join(', ')}>
        {todas.map(([nombre, valor, clase]) => (
          <span key={nombre} className={clase} style={{ flexGrow: valor, minWidth: 3 }} title={`${nombre}: ${valor.toFixed(2)} s`} />
        ))}
      </div>
      <ul className="leyenda">
        {todas.map(([nombre, valor, clase]) => (
          <li key={nombre}><span className={`muestra ${clase}`} />{nombre} <span className="num" style={{ color: 'var(--tinta)' }}>{valor < 1 ? `${Math.round(valor * 1000)} ms` : `${valor.toFixed(1)} s`}</span></li>
        ))}
      </ul>
    </div>
  );
}

// Un salto de línea antes de cada cláusula, para leer la consulta de un vistazo.
const formatear = (sql) => sql.replace(/\s+(FROM|WHERE|ORDER BY|LIMIT)\s/g, '\n$1 ') + ';';
