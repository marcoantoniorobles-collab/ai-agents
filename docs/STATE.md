# Estado actual — actualizar cada vez que algo cambie en producción

_Última actualización: 2026-08-18 (tarde)_

## Servicios desplegados

| Servicio     | Contenedor     | Puerto (solo Tailscale) | Notas |
|--------------|---------------|--------------------------|-------|
| postgres     | ai-postgres    | interno, sin publicar    | `postgres:17`, DB `ai_agents` |
| redis        | ai-redis       | interno, sin publicar    | `redis:7-alpine`, `--appendonly no` |
| api          | ai-api         | 8000                      | FastAPI + Agent Manager interno + Dashboard (`/dashboard`) |
| worker       | ai-worker      | —                         | Worker genérico, cola `tasks` |
| agent-1      | ai-agent-1     | 6080 (noVNC)              | `ENABLE_VNC=true`, único con navegador visible |
| agent-2      | ai-agent-2     | —                         | headless, sin uso todavía |
| agent-3      | ai-agent-3     | —                         | headless, sin uso todavía |

## Dashboard

`http://<TAILSCALE_IP>:8000/dashboard` — panel de solo lectura, sin login
propio (protegido por la red Tailscale). Auto-refresh cada 4s. Muestra:
- Tarjetas de agentes: estado, último heartbeat, tarea actual (si hay una
  `RUNNING`), y un botón "Ver pantalla en vivo" para los agentes con
  `metadata.vnc_enabled=true` (embebe el mismo noVNC en un panel lateral,
  sin salir de la página).
- Tabla de las últimas 50 tareas, filtrable por estado, con duración y
  mensaje de error si falló.

Implementación: `services/api/app/static/dashboard.html` (HTML/JS
autocontenido, sin build ni dependencias) + ruta `GET /dashboard` en
`services/api/app/main.py`. El flag `vnc_enabled` viaja en
`agents.metadata` (JSONB), seteado por cada agente al registrarse según su
propio `ENABLE_VNC`.

## Agentes registrados (tabla `agents`)

| Nombre   | ID                                     | Estado al 2026-08-18 |
|----------|-----------------------------------------|------------------------|
| agent-1  | `023c69df-7b7b-4056-8738-bfd5961081c7` | ONLINE, con navegador visible por noVNC |

(agent-2 y agent-3 se registran solos al arrancar, con sus propios IDs —
consultar `GET /agents` o el dashboard para verlos).

## Proyectos de negocio activos

### SERVIR — Sistema de Difusión de Ofertas Laborales

- Carpeta: `services/browser-agent/agent_runtime/projects/servir/`
- Corre en: `agent-1`
- Tabla propia: `servir_ofertas` (`schema/002_servir_ofertas.sql`)
  - **Clave única: (`numero_convocatoria`, `entidad`, `titulo`)** — no
    alcanza con número+entidad solos, porque una misma entidad puede
    repetir el mismo número de convocatoria para varios puestos distintos
    dentro de la misma convocatoria transitoria (ej. "1 chofer / 1
    secretaria" bajo un mismo número). Esto se detectó y corrigió
    en pruebas reales (ver `CHANGELOG.md`).
  - El upsert hace **commit por fila individual** (no un commit al final
    de todo el lote): si una fila puntual falla, se registra el error y
    se sigue con las demás, sin perder el resto del progreso.
- `task_type` disponibles:
  - `scrape_servir_ofertas` — corrida simple, sin sincronización con Postgres (uso: pruebas puntuales, admite `max_pages`).
  - `servir_daily_sync` — corrida completa diaria con seguimiento persistente, respeta la columna "No me interesa" marcada por el usuario, y limpia ofertas vencidas. Esta es la que corre el timer diario. **Loguea progreso cada 20 páginas** (`docker compose logs -f agent-1`) para poder seguir corridas largas.
- Salida: `AI-Agents/salidas/agente-1/Ofertas_SERVIR_activas.xlsx` (mismo archivo, se sobreescribe cada corrida)
- Programado: timer de systemd `servir-daily.timer`, todos los días 6:00 AM (con recuperación si la máquina estaba apagada) — **archivos listos en `infra/systemd/`, todavía no instalado en el sistema** (pendiente).
- Fuente: `https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml`
- Estructura de la página: JSF/PrimeFaces, NO es una `<table>` — ver
  `services/browser-agent/agent_runtime/projects/servir/README.md` para
  el detalle completo de selectores.
- **Pruebas realizadas:** `scrape_servir_ofertas` (3 páginas, OK) y
  `servir_daily_sync` (3 páginas, OK, tras corregir la clave única).
  **Pendiente:** primera corrida real completa (338 páginas / ~3377 ofertas).

## Próximos pasos pendientes (al momento de este snapshot)

- [ ] Confirmar que la corrida real completa de `servir_daily_sync` (338 páginas) terminó bien — lanzada, en curso al momento de este snapshot.
- [ ] Instalar el timer systemd (`infra/systemd/`) para que quede corriendo solo a diario — todavía no instalado.
- [ ] (Futuro) Definir el segundo agente/proyecto.

## Fix importante: timeout de RQ (job_timeout)

RQ mata una tarea a la fuerza si supera 180 segundos por defecto (sin
avisar de forma recuperable — mata el proceso worker completo, dejando la
tarea en Postgres atascada en `RUNNING` para siempre, sin actualizar su
estado). Esto rompió el primer intento de corrida real de SERVIR (338
páginas, ~20-30 min de duración esperada).

**Fix aplicado:** `job_timeout=3600` (1 hora) en TODOS los `enqueue()` /
`enqueue_in()` de la plataforma — tanto en `services/api/app/queue.py`
(encolado inicial) como en `services/browser-agent/agent_runtime/jobs.py`
(re-encolado de reintentos). Ver `docs/ARCHITECTURE.md` para el detalle.

**Si una tarea real queda atascada en `RUNNING` para siempre** (por este
u otro motivo antes de este fix): arreglar a mano en Postgres:
```sql
UPDATE tasks SET status='DEAD', error_message='...', completed_at=now()
WHERE id='<uuid de la tarea>';
```

## Cómo retomar este proyecto sin el historial del chat

1. Leer, en orden: `README.md` → `docs/ARCHITECTURE.md` → `docs/STATE.md` (este archivo) → `docs/AGENT_PROTOCOL.md`.
2. El código real vive en `~/ai-agents/` dentro del servidor Ubuntu, y en `https://github.com/marcoantoniorobles-collab/ai-agents` (privado).
3. Para ver el estado en vivo: `http://<TAILSCALE_IP>:8000/dashboard` (necesita estar conectado al mismo tailnet).
4. `git log --oneline` en `~/ai-agents/` muestra el historial real de cambios aplicados.

