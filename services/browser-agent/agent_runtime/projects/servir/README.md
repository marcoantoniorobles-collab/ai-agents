# Proyecto: SERVIR — Ofertas Laborales

Scraper del Sistema de Difusión de Ofertas Laborales de SERVIR (Perú).

**URL fuente:** `https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml`

## Por qué Playwright (navegador real) y no peticiones HTTP directas

La página es una aplicación JSF/PrimeFaces con estado de sesión
(`javax.faces.ViewState`) que cambia en cada respuesta del servidor.
Replicar el protocolo AJAX a mano (headers, form-data con ViewState)
es fràgil y depende de un token por-sesión. Usar un navegador real que
hace clic en los botones reales es más robusto: Playwright maneja el
AJAX, las cookies, y el ViewState automáticamente, igual que lo haría
una persona.

## Estructura real de la página (confirmada, no es una `<table>`)

- Contenedor: `form#frmLstOfertsLabo`
- Cada oferta: `div.cuadro-vacantes`
  - Título: `.titulo-vacante label`
  - Entidad: `.nombre-entidad .detalle-sp`
  - 6 campos más, como pares `.sub-titulo` (etiqueta) / `.detalle-sp`
    (valor) dentro de `.col-sm-5`: Ubicación, Número de Convocatoria,
    Cantidad de Vacantes, Remuneración, Fecha Inicio de Publicación,
    Fecha Fin de Publicación.
- Paginación: 2 barras (arriba/abajo), botones de texto "Primero",
  "Atras", "Sig.", "Último". Etiqueta central `label.btn-paginator-cnt`
  con el texto "Página X de Y".
- Al hacer clic en "Sig." se dispara un POST AJAX a la misma URL (no
  cambia la URL, no es navegación de página completa).
- 10 ofertas por página. Al momento de escribir esto: ~3377 ofertas,
  ~338 páginas.
- No hace falta clic en "Buscar": la página carga con los resultados ya
  poblados de entrada.
- No se detectó captcha ni límite de tasa visible, pero de todas formas
  el scraper usa delays aleatorios entre páginas (2.5-5.5s, con pausas
  más largas cada 20 páginas) para no comportarse como un bot perfecto.

## `task_type` disponibles

### `scrape_servir_ofertas` (prueba puntual, sin memoria)

Payload:
```json
{
  "max_pages": 3,
  "filename": "prueba.xlsx",
  "url": "(opcional, usa la URL por defecto si se omite)"
}
```
Recorre `max_pages` páginas (o todas si se omite) y escribe un Excel
simple, sin comparar con corridas anteriores. Pensado para pruebas.

### `servir_daily_sync` (uso real, con seguimiento persistente)

Payload: `{}` (todos los campos son opcionales, usa los valores por
defecto: todas las páginas, archivo `Ofertas_SERVIR_activas.xlsx`).

Flujo:
1. Lee el Excel de trabajo actual (si existe) y busca filas marcadas
   con `X` en la columna **"No me interesa"**.
2. Marca esas ofertas como `removed_by_user=true` en la tabla
   `servir_ofertas` (Postgres) — de forma **permanente**, no se vuelven
   a mostrar aunque sigan publicadas en SERVIR.
3. Recorre TODAS las páginas de SERVIR.
4. Actualiza `servir_ofertas`: ofertas nuevas se agregan
   (`first_seen_at`), las que siguen publicadas actualizan
   `last_seen_at`.
5. Si el recorrido fue completo (sin páginas fallidas): las ofertas que
   ya no aparecieron se consideran vencidas y se eliminan de la tabla.
   Si hubo páginas fallidas, no se elimina nada por las dudas (para no
   perder ofertas válidas por un fallo puntual de red).
6. Escribe el Excel final (mismo nombre siempre, se sobreescribe) con
   formato prolijo: encabezados en negrita, columnas anchas, filas
   alternadas, y la columna "No me interesa" vacía lista para marcar.

## Tabla `servir_ofertas` (Postgres)

Ver `schema/002_servir_ofertas.sql`. Clave única:
(`numero_convocatoria`, `entidad`).

## Programación automática

Timer de systemd `servir-daily.timer`, todos los días a las 6:00 AM,
con `Persistent=true` (si la máquina estaba apagada, corre apenas
prende). Ver `infra/systemd/`.
