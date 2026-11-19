// "Cómo se respondió": lo que hizo nuestro motor para esta pregunta.
export default function Traza({ datos }) {
  const { traza, consulta, fragmentos } = datos;
  const redaccion = traza.s_redaccion == null
    ? 'Sin LLM: solo los fragmentos'
    : `${traza.modelo ?? 'LLM'} · ${traza.s_redaccion.toFixed(1)} s al redactar`;

  return (
    <section className="panel traza" aria-label="Cómo se respondió">
      <h2>Cómo se respondió</h2>
      <dl className="traza-filas">
        <dt>Palabras clave</dt>
        <dd>
          {consulta || '—'}
          <span className="sub">
            {traza.palabras_con_llm ? ` · las eligió el LLM en ${traza.s_palabras?.toFixed(1)} s` : ' · glosario local'}
          </span>
        </dd>
        <dt>Consultas SQL</dt>
        <dd className="sql">
          {traza.sql.map((sentencia) => <pre key={sentencia}>{formatear(sentencia)}</pre>)}
        </dd>
        <dt>Resultado</dt>
        <dd className="num">
          {fragmentos.length} fragmento{fragmentos.length === 1 ? '' : 's'} de {traza.documentos} documento{traza.documentos === 1 ? '' : 's'}
          {' '}(máx. 2 por documento) · {traza.ms_motor.toFixed(0)} ms en el motor
        </dd>
        <dt>Redacción</dt>
        <dd className="num">{redaccion} · {traza.s_total.toFixed(1)} s en total</dd>
      </dl>
    </section>
  );
}

// Un salto de línea antes de cada cláusula, para leer la consulta de un vistazo.
const formatear = (sql) => sql.replace(/\s+(FROM|WHERE|ORDER BY|LIMIT)\s/g, '\n$1 ') + ';';
