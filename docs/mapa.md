# Mapa espacial

La pestaña **Mapa** es un panel nativo de Tkinter hecho con `tkintermapview`
(incluida en `requirements.txt`). Los datos de la tabla son locales; solo los
mosaicos del fondo se descargan de Internet.

Cada `SELECT` sobre una tabla con una columna `POINT` actualiza el mapa y
resalta los identificadores incluidos en el resultado:
- las consultas por radio dibujan el centro y el círculo, aunque el `WHERE` tenga otros filtros;
- los k-NN (`ORDER BY distancia(...) LIMIT k`) marcan el punto de consulta;
- `WITHIN(..., POLYGON(...))` dibuja el polígono.

La vista se encuadra sobre la figura y los resultados de la consulta; el botón
**⦿** vuelve a ese encuadre. Si la pestaña estaba oculta, encuadra al abrirla.

El clic derecho > **Insertar POINT aquí** escribe `POINT(lat, lon)` en el editor
SQL y vuelve a la pestaña **Consulta SQL**.

**Rendimiento:**
- **Puntos cacheados por tabla:** el motor lee los puntos una vez por tabla y los guarda hasta que una sentencia pueda modificar datos (INSERT, DELETE, COPY, transacciones o DDL). Así una consulta resuelta con R-Tree no paga un scan extra por el mapa: con 20.000 filas, una consulta k-NN tarda ~5 ms en lugar de ~360 ms.
- **Marcadores limitados:** cada marcador se crea en el hilo de la interfaz. Con 100 puntos o más solo se dibujan los del resultado, y nunca más de 500. La barra de estado indica cuántos se dibujaron.

Los límites están en `frontend/mapa_datos.py`.

Para usarlo:

```sql
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
```

Después se abre la pestaña **Mapa**.
