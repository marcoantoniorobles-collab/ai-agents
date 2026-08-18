# Arquitectura — decisiones ya tomadas

Este documento existe para que cualquier persona (o IA) que retome este
proyecto entienda el "por qué" sin tener que releer el historial completo
del chat. Las decisiones acá **no se vuelven a discutir** salvo pedido
explícito.

## Filosofía general

Infraestructura primero, agentes después, procesos de negocio al final.
Evitar sobre-ingeniería: nada de Kubernetes, Kafka, ni Celery para esta
escala (empezando con 3 agentes, con capacidad de crecer a 6-10+).

## Entorno

Ubuntu (VM sobre VMware) como servidor real. Un solo usuario administrador.
Todo corre en Docker/Compose — nada instalado directo con `apt` salvo
herramientas de sistema/red (Tailscale, systemd timers).

## Acceso remoto: Tailscale, no exposición pública

Se eligió Tailscale sobre exposición pública tradicional (dominio + Caddy +
ufw + fail2ban) por ser más simple y más seguro: no hay puertos abiertos a
internet, no hay certificados TLS que gestionar. Dashboard/API bindeados
**solo** a la IP de Tailscale, nunca a `0.0.0.0`. Postgres/Redis sin
publicar ningún puerto — solo alcanzables entre contenedores por nombre
dentro de la red Docker interna.

## Cola de tareas: Redis + RQ

No Celery (excesivo para esta escala), no RabbitMQ/Kafka. Redis corre con
`--appendonly no`: no es la fuente de verdad, solo el canal de la cola.

## Base de datos de control: Postgres = fuente de verdad

Postgres (una sola instancia compartida, ver más abajo el criterio de
tablas) guarda el estado real de agentes/tareas/sesiones. Si Redis se
reinicia y se pierden jobs encolados, Postgres sigue teniendo la verdad y
las tareas se pueden re-encolar.

Tablas de control (ver `schema/001_control.sql`):
`agents`, `tasks`, `sessions`, `execution_history`.

- `tasks.payload` es `JSONB` (no columnas fijas): la forma de los datos
  varía mucho entre tipos de tarea y agentes, y JSONB evita tener que
  rediseñar el esquema por cada tipo de tarea nuevo.
- `tasks.status`: `PENDING → QUEUED → RUNNING → COMPLETED | FAILED | DEAD`.
  `DEAD` = dead-letter, se agotaron los reintentos (`retry_count` vs
  `max_retries`, con backoff exponencial).
- Evitar doble ejecución: `SELECT ... FOR UPDATE SKIP LOCKED` en Postgres
  como mecanismo autoritativo (no confiar solo en Redis).

## Postgres compartida, tablas separadas por proyecto

**Una sola instancia de Postgres** para todos los agentes/proyectos, pero
**cada proyecto de negocio tiene sus propias tablas** (ej: `servir_ofertas`
para el proyecto SERVIR). Esto evita la complejidad operativa de mantener
N instancias de Postgres (backups, memoria, mantenimiento por separado),
sin mezclar datos entre proyectos (cada tabla es su propio espacio lógico).
Si algún proyecto crece mucho o tiene requisitos de aislamiento fuertes,
se evalúa separarlo en ese momento — no antes.

## Agent Manager: módulo interno de la API, no microservicio separado

Vive dentro del proceso de la API (FastAPI), como loop de background
(`agent_manager.py`). Marca `OFFLINE` a agentes con heartbeat vencido, y
re-encola tareas `RUNNING` huérfanas. Se puede extraer a un servicio propio
después si hace falta, sin tener que rediseñar el resto.

## Modelo de agentes: 1 contenedor = 1 agente, con cola RQ dedicada

Cada agente-con-navegador (`services/browser-agent`) es su propio
contenedor, que:
1. Se auto-registra en `agents` al arrancar (por nombre, vía `AGENT_NAME`).
2. Mantiene su propio heartbeat en Postgres (thread en background).
3. Escucha **su propia cola RQ** (`agent:<agent_id>`), no la genérica.
4. Lanza **un solo proceso Chromium persistente** al arrancar (no uno por
   tarea), con **un `BrowserContext` por sesión lógica** (no un proceso
   Chrome completo por sesión) — reduce el consumo de RAM a la mitad
   frente al modelo "1 sesión = 1 proceso completo".
5. Las sesiones logueadas se persisten como `storageState` (JSON liviano:
   cookies + localStorage) en la tabla `sessions`, no como perfiles
   completos de Chrome.

**Por qué cola dedicada por agente, no una cola compartida:** el
Chromium y las sesiones viven en un proceso específico. Una tarea que
necesita navegador tiene que ejecutarse en ESE proceso, no en cualquier
worker disponible. Por eso `tasks.agent_id` es obligatorio para cualquier
tarea de navegación, y la API la encola en `agent:<agent_id>` en vez de la
cola genérica `tasks`.

**Por qué `SimpleWorker` de RQ, no el `Worker` por defecto:** el `Worker`
por defecto bifurca (`fork`) un proceso nuevo por cada tarea, para
aislamiento. Pero el Chromium persistente vive en el proceso padre — un
hijo bifurcado no tiene acceso válido a ese navegador ya abierto (error
típico: `Browser.new_context: no running event loop`). `SimpleWorker`
ejecuta cada tarea en el mismo proceso, sin bifurcar, que es lo que
necesitamos acá.

**Worker genérico (`services/worker`) vs agentes con navegador:** tareas
sin `agent_id` (sin necesidad de navegador) van a la cola genérica
`tasks`, procesada por el worker genérico — más liviano, sin Playwright.

## Agentes visibles en vivo: noVNC, activado por agente

`ENABLE_VNC=true` en un agente arranca Xvfb + fluxbox + x11vnc + noVNC
dentro de su contenedor, exponiendo el escritorio remoto en el puerto 6080
(bindeado solo a la IP de Tailscale). El navegador de ese agente arranca
`headed` (visible) en vez de `headless`. Otros agentes sin esa variable
corren headless, más livianos, sin el overhead de Xvfb/VNC.

## Tareas programadas: systemd timers, no cron puro

Se usa un timer de systemd con `Persistent=true` en vez de `cron` puro:
si la máquina está apagada a la hora programada, la tarea se dispara
automáticamente apenas se prende de nuevo. `cron` simple no tiene esa
recuperación.

## Timeout de RQ: siempre explícito, nunca el default

El default de RQ (`job_timeout`) es 180 segundos — mata el proceso a la
fuerza si se excede, sin darle chance al código a actualizar el estado en
Postgres (la tarea queda atascada en `RUNNING` para siempre). Cualquier
tarea que pueda tardar más que unos segundos (scrapers multi-página,
cualquier cosa con delays humanizados) DEBE encolarse con un
`job_timeout` explícito y generoso. En esta plataforma se usa un valor
único de **3600 segundos (1 hora)** para todo, tanto en el encolado
inicial (`services/api/app/queue.py`) como en el re-encolado de
reintentos (`jobs.py` de cada tipo de agente/worker) — más simple que
tener un valor por `task_type`, y ninguna tarea actual necesita más de
una hora.

## Claves únicas de negocio: verificar contra datos reales, no asumir

Al diseñar la tabla `servir_ofertas` se asumió que (`numero_convocatoria`,
`entidad`) identificaba una oferta de forma única. Falso: una misma
entidad puede repetir el mismo número de convocatoria para varios puestos
distintos dentro de una convocatoria transitoria (ej. "1 chofer / 1
secretaria" bajo el mismo número). Se corrigió agregando `titulo` a la
clave. **Lección para proyectos futuros:** antes de fijar una clave única
de negocio, probarla contra una muestra real de datos (no asumir desde la
documentación de la página), y diseñar el upsert con commit por fila
individual (no un solo commit al final del lote) para que un choque de
clave puntual no aborte todo el progreso ya guardado.

## Reintentos y resiliencia en tareas largas (scrapers multi-página)

Un scraper que recorre cientos de páginas NO debe abortar todo el progreso
por el fallo de una sola página. Patrón usado: capturar la excepción por
página individual, registrarla como fallida, y seguir — nunca dejar que
una falla parcial dispare el mecanismo de reintento genérico de RQ (que
reiniciaría la tarea completa desde cero). El resultado final (ej: el
Excel) se escribe siempre con lo que se haya podido recolectar, aunque el
recorrido se haya cortado antes de terminar.

## Monitoreo

Descartado Prometheus/Grafana/Loki por ahora (prematuro para esta escala).
Alcanza con `docker logs` / `docker stats` y la tabla `execution_history`.
Se reevalúa si el volumen de agentes lo justifica más adelante.

## Reverse proxy

Descartado (Nginx/Traefik/Caddy) — resuelto con Tailscale, no hace falta.

## Dashboard: HTML/JS autocontenido servido por la misma API

Sin build, sin framework, sin contenedor nuevo. Un solo archivo
(`services/api/app/static/dashboard.html`) que hace `fetch()` periódico a
`/agents` y `/tasks` (ya existentes) y renderiza el estado. Servido por una
ruta más de la API (`GET /dashboard`), reutilizando la misma seguridad de
red que ya existe (Tailscale) — sin login propio, porque la red ya es el
control de acceso.

**Por qué no un frontend con build (React, etc.):** para esta escala,
agregar un pipeline de build (npm, bundler) es sobre-ingeniería. Un archivo
HTML con JS vanilla que hace polling cada 4 segundos cubre la necesidad
completa (ver estado de agentes y tareas en vivo) sin esa complejidad. Se
reevalúa si el dashboard crece mucho en funcionalidad.

**Ver pantalla en vivo embebida:** el dashboard puede embeber el noVNC de
un agente en un panel lateral (iframe), en vez de mandar a la persona a
otra pestaña. Esto se ofrece solo para agentes con
`metadata.vnc_enabled=true` (cada agente setea ese flag en su propia fila
de `agents` al registrarse, según su propio `ENABLE_VNC`). El iframe vive
en un contenedor separado de la grilla de agentes que se refresca cada 4s,
para no reconectar el VNC en cada ciclo de refresh.
