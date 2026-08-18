# Changelog

## 2026-08-18 (tarde) — Dashboard + corrección de clave única en SERVIR

- **Dashboard** (`/dashboard` en la API): panel en vivo de agentes y
  tareas, HTML/JS autocontenido sin build. Incluye botón para ver la
  pantalla de un agente (noVNC) embebida en un panel lateral, sin salir
  del dashboard.
- **Fix crítico en SERVIR:** la clave única de `servir_ofertas` pasó de
  (`numero_convocatoria`, `entidad`) a (`numero_convocatoria`, `entidad`,
  `titulo`) — se detectó con datos reales que la clave original generaba
  choques (múltiples puestos bajo el mismo número de convocatoria).
- El upsert de ofertas ahora hace commit por fila individual, no un solo
  commit al final del lote — más resiliente a fallos puntuales.
- Se agregó logging de progreso cada 20 páginas en `servir_daily_sync`,
  para poder seguir corridas largas por `docker compose logs -f agent-1`.
- Probado de punta a punta: `servir_daily_sync` con 3 páginas, COMPLETED,
  27 ofertas nuevas guardadas correctamente. Pendiente: corrida real
  completa (338 páginas).

## 2026-08-18 — Reorganización del repo + proyecto SERVIR

- Reestructuración completa a un layout versionable (`services/`,
  `schema/`, `docs/`, `infra/`), separado por proyecto/agente.
- Fase 1-4 (ya estables): infraestructura base (Postgres+Redis), esquema
  de control, API mínima con Agent Manager interno, worker genérico con
  retry/backoff/dead-letter.
- Fase 5 (Chrome/Playwright): 1 Chromium persistente por agente, cola RQ
  dedicada por agente (`agent:<id>`), `SimpleWorker` (sin fork) para
  compatibilidad con el navegador persistente, noVNC opcional por agente.
- Primer proyecto de negocio: SERVIR (ofertas laborales).
  - Scraper con selectores validados contra la página real.
  - Formato de Excel prolijo + columna "No me interesa".
  - Seguimiento persistente en Postgres (`servir_ofertas`): no repite
    ofertas marcadas por el usuario, limpia las vencidas automáticamente.
  - Corrida diaria automática vía timer de systemd (resistente a que la
    máquina esté apagada a la hora programada).
