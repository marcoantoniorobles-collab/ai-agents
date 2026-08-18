# Cómo agregar un agente o proyecto nuevo

Esta plataforma está pensada para crecer a muchos agentes y proyectos sin
que el repo se vuelva un caos. Seguir este patrón siempre.

## Caso A: agregar lógica de negocio nueva a un agente EXISTENTE

Ejemplo: `agent-1` ya existe y corre Playwright; querés agregarle una
tarea nueva para otro sitio web distinto de SERVIR.

1. Crear una carpeta nueva bajo
   `services/browser-agent/agent_runtime/projects/<nombre_proyecto>/`.
2. Adentro: un `scraper.py` (o el nombre que corresponda) con la lógica,
   más un `README.md` propio explicando qué hace, qué estructura de
   página asume, y cualquier decisión de diseño específica.
3. Si el proyecto necesita su propia tabla en Postgres, agregar un archivo
   nuevo en `schema/`, numerado siguiente (ej: `003_<proyecto>.sql`) — no
   reutilizar tablas de otro proyecto.
4. Registrar el/los handler(s) nuevos en
   `services/browser-agent/agent_runtime/registry.py`
   (import + entrada en `TASK_HANDLERS`).
5. Actualizar `docs/STATE.md` con el nuevo `task_type` disponible.

**No** se crean carpetas nuevas para esto en `services/` — un mismo
contenedor de agente puede tener muchos `task_type` distintos registrados.

## Caso B: agregar un AGENTE nuevo (nuevo contenedor)

Ejemplo: agente 4, 5, 6... o un tipo de agente distinto (sin navegador,
solo lógica/código — para tareas tipo "Claude Code" autónomo).

1. Si es el mismo tipo de runtime (con navegador): solo agregar un
   servicio nuevo en `docker-compose.override.yml`, con su propio
   `AGENT_NAME`, construido desde el mismo
   `services/browser-agent`. No duplicar código — todos los agentes con
   navegador comparten la misma imagen, se diferencian por `AGENT_NAME`
   (que determina su fila en `agents` y su cola RQ dedicada).
2. Si es un tipo de runtime distinto (ej: agente sin navegador que solo
   ejecuta código/decisiones): crear una carpeta nueva en
   `services/<nombre-del-tipo-de-runtime>/`, siguiendo el mismo patrón
   interno que `browser-agent` (config, database, models, agent
   registration con heartbeat, cola RQ dedicada por agente, registry de
   handlers) — pero sin las partes específicas de Chromium/Playwright/VNC
   si no las necesita.
3. Agregar el servicio nuevo a `docker-compose.override.yml`.
4. Documentar en `docs/STATE.md`.

## Reglas fijas (no negociables al escalar)

- **1 agente = 1 fila en `agents` = 1 cola RQ dedicada** (`agent:<id>`).
  Nunca compartir cola entre agentes que necesiten mantener estado propio
  (navegador, sesión, etc).
- **Postgres es una sola instancia compartida**; cada proyecto tiene sus
  propias tablas, nunca reutiliza tablas de otro proyecto.
- **Todo cambio de código es un commit de git**, no un zip nuevo. Mensajes
  de commit descriptivos (qué cambió y por qué).
- **Todo scraper/tarea larga debe ser resiliente a fallos parciales**: un
  error en el medio no debe tirar todo el progreso a la basura (ver
  `docs/ARCHITECTURE.md`, sección de reintentos).
- **Todo proyecto nuevo lleva su propio `README.md`** dentro de su
  carpeta, explicando su propósito y cualquier decisión de diseño
  específica — no solo un comentario en el código.
