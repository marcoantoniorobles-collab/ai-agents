# Estado actual — actualizar cada vez que algo cambie en producción

_Última actualización: 2026-08-18_

## Servicios desplegados

| Servicio     | Contenedor     | Puerto (solo Tailscale) | Notas |
|--------------|---------------|--------------------------|-------|
| postgres     | ai-postgres    | interno, sin publicar    | `postgres:17`, DB `ai_agents` |
| redis        | ai-redis       | interno, sin publicar    | `redis:7-alpine`, `--appendonly no` |
| api          | ai-api         | 8000                      | FastAPI + Agent Manager interno |
| worker       | ai-worker      | —                         | Worker genérico, cola `tasks` |
| agent-1      | ai-agent-1     | 6080 (noVNC)              | `ENABLE_VNC=true`, único con navegador visible |
| agent-2      | ai-agent-2     | —                         | headless |
| agent-3      | ai-agent-3     | —                         | headless, sin uso todavía |

## Agentes registrados (tabla `agents`)

| Nombre   | ID                                     | Estado al 2026-08-18 |
|----------|-----------------------------------------|------------------------|
| agent-1  | `023c69df-7b7b-4056-8738-bfd5961081c7` | ONLINE, con navegador visible por noVNC |

(agent-2 y agent-3 se registran solos al arrancar, con sus propios IDs —
consultar `GET /agents` para verlos).

## Proyectos de negocio activos

### SERVIR — Sistema de Difusión de Ofertas Laborales

- Carpeta: `services/browser-agent/agent_runtime/projects/servir/`
- Corre en: `agent-1`
- Tabla propia: `servir_ofertas` (`schema/002_servir_ofertas.sql`)
- `task_type` disponibles:
  - `scrape_servir_ofertas` — corrida simple, sin sincronización con Postgres (uso: pruebas puntuales, admite `max_pages`).
  - `servir_daily_sync` — corrida completa diaria con seguimiento persistente, respeta la columna "No me interesa" marcada por el usuario, y limpia ofertas vencidas. Esta es la que corre el timer diario.
- Salida: `AI-Agents/salidas/agente-1/Ofertas_SERVIR_activas.xlsx` (mismo archivo, se sobreescribe cada corrida)
- Programado: timer de systemd `servir-daily.timer`, todos los días 6:00 AM (con recuperación si la máquina estaba apagada)
- Fuente: `https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml`
- Estructura de la página: JSF/PrimeFaces, NO es una `<table>` — ver
  `services/browser-agent/agent_runtime/projects/servir/README.md` para
  el detalle completo de selectores.

## Próximos pasos pendientes (al momento de este snapshot)

- [ ] Confirmar la primera corrida real de `servir_daily_sync` sin límite de páginas (338 páginas completas).
- [ ] Verificar que el timer systemd quede instalado y activo.
- [ ] Iniciar repo git y primer commit.
- [ ] (Futuro) Definir el segundo agente/proyecto.
