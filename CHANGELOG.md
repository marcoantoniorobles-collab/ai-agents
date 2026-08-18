# Changelog

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
