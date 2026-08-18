# AI Agents — Plataforma de agentes de IA/automatización

Plataforma para ejecutar múltiples agentes de IA/automatización en Docker,
sobre un servidor Ubuntu accedido vía Tailscale (sin exposición pública a
internet).

**Para entender las decisiones de arquitectura ya tomadas, leer primero:**
`docs/ARCHITECTURE.md`

**Para saber qué está desplegado ahora mismo (agentes, IDs, puertos):**
`docs/STATE.md`

**Para agregar un agente o proyecto nuevo:**
`docs/AGENT_PROTOCOL.md`

## Estructura del repo

```
services/
  api/              API de control (FastAPI): agentes, tareas, Agent Manager interno
  worker/           Worker genérico (sin navegador) para tareas simples
  browser-agent/    Runtime de agente con Chromium/Playwright + noVNC opcional
    agent_runtime/
      *.py          Núcleo genérico (config, DB, cola, ciclo de vida del agente)
      projects/     Un subdirectorio por proyecto de negocio (ej: servir/)
schema/             DDL de Postgres, numerado en orden de aplicación
infra/systemd/      Timers/servicios systemd para tareas programadas
docs/               Documentación (arquitectura, estado, protocolo de agentes)
```

## Levantar todo desde cero

```bash
docker compose up -d --build
```

Servicios: `postgres`, `redis` (internos, sin puertos publicados),
`api` (puerto 8000, solo en la IP de Tailscale), `worker`,
`agent-1`/`agent-2`/`agent-3` (agentes con navegador).

## Aplicar el esquema de Postgres (solo la primera vez, o al agregar tablas nuevas)

```bash
docker exec -i ai-postgres psql -U aiadmin -d ai_agents < schema/001_control.sql
docker exec -i ai-postgres psql -U aiadmin -d ai_agents < schema/002_servir_ofertas.sql
```

## Ver el navegador de un agente en vivo

`http://<TAILSCALE_IP>:6080/vnc.html` (solo `agent-1`, que tiene `ENABLE_VNC=true`).

## Historial de cambios

Ver `CHANGELOG.md`.
