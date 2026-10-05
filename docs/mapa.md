# Mapa espacial

El panel **Mapa espacial** inicia una API HTTP local en `127.0.0.1` y el botón
**Abrir mapa** carga una página Leaflet con tiles de OpenStreetMap. No requiere
dependencias Python adicionales. El frontend nunca expone el servidor fuera de
la máquina local.

Cada `SELECT` sobre una tabla con una columna `POINT` publica sus puntos y
resalta los identificadores incluidos en el resultado:
- las consultas por radio dibujan el centro y el círculo, aunque el `WHERE` tenga otros filtros;
- los k-NN (`ORDER BY distancia(...) LIMIT k`) marcan el punto de consulta;
- `WITHIN(..., POLYGON(...))` dibuja el polígono.

Al hacer clic, el mapa inserta `POINT(lat, lon)` en el editor SQL.

**Rendimiento:**
- **Puntos cacheados por tabla:** el motor lee los puntos una vez por tabla y los guarda hasta que una sentencia pueda modificar datos (INSERT, DELETE, COPY, transacciones o DDL). Así una consulta resuelta con R-Tree no paga un scan extra por el mapa: con 20.000 filas, una consulta k-NN tarda ~5 ms en lugar de ~360 ms.
- **Serialización única:** el servidor convierte los puntos a JSON solo cuando cambia la lista.
- **Actualización por versión:** el navegador pide cada segundo un número de versión y redibuja solo cuando cambió. Por eso no pierde el zoom del usuario entre consultas, y encuadra el resultado solo cuando llega una consulta nueva.
- **Canvas:** los puntos se dibujan con el renderer de canvas de Leaflet, que soporta decenas de miles de puntos. Con más de 5.000, solo los resultados tienen popup.

La página está en `frontend/mapa.html`.

Para usarlo:

```sql
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
```

Después se pulsa **Abrir mapa**. El acceso a tiles y al CDN de Leaflet requiere
conexión a Internet en el navegador; los datos de la tabla y la API se sirven
localmente. La prueba HTTP se omite solo en entornos que prohíben sockets locales.
