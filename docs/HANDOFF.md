# Contexto de sesión — para retomar en un chat nuevo

Este documento resume todo lo trabajado en la sesión del 2026-08-18 sobre
la plataforma de agentes de IA. Pegar este archivo completo al inicio de
una conversación nueva le da a Claude (o cualquier otra IA) el contexto
necesario para continuar sin tener que re-explicar nada.

**Los documentos técnicos completos ya están en el repo** (leer primero,
en este orden): `README.md` → `docs/ARCHITECTURE.md` → `docs/STATE.md` →
`docs/AGENT_PROTOCOL.md`. Este archivo complementa esos con contexto de
la persona y del proceso de trabajo, que no está en la documentación
técnica.

## Quién es la persona y cómo prefiere trabajar

- **No es técnica.** No sabe Linux, Docker, ni programación. Cada comando
  de terminal tiene que dárselo de a UNO POR VEZ, numerado, con
  instrucciones de "copiá esto, pegalo, Enter, avisame". Nunca varios
  comandos juntos en un bloque — se confunde y pierde el hilo.
- Usa una VM de Ubuntu (con escritorio gráfico, VMware) accedida por
  Tailscale, con una carpeta compartida de VMware (`/mnt/hgfs/AI-Agents`
  en Ubuntu = carpeta `AI-Agents` en Windows) como puente para pasar
  archivos entre Claude y la VM.
- **Confundió varias veces** la carpeta compartida (`/mnt/hgfs/AI-Agents`)
  con la carpeta real del proyecto (`~/ai-agents`), y el navegador de
  Windows con el navegador gráfico de la VM. Hay que ser explícito sobre
  en qué máquina/carpeta se ejecuta cada cosa.
- Quiere que las cosas se prueben y verifiquen **antes** de dárselas
  ("quiero ver todo con evidencia, no que me digas que funciona sin
  probarlo"). Cuando algo falla, pide diagnóstico con comandos concretos,
  no explicaciones abstractas.
- Le importa mucho el orden, la documentación, y poder escalar a
  "cientos de agentes" sin que el repo se vuelva un caos — pidió
  explícitamente la reorganización a una estructura versionable con
  git/GitHub en medio de la sesión.
- Prefiere confirmaciones cortas tipo pregunta con opciones (A o B) en
  vez de preguntas abiertas.

## Qué se construyó en esta sesión (resumen narrativo)

Partiendo de una infraestructura ya existente (Postgres, Redis, API,
worker genérico, 3 agentes con Playwright — fases 1 a 5 del plan
original, ver `docs/ARCHITECTURE.md`), en esta sesión se agregó:

1. **VNC en vivo para `agent-1`** (Xvfb + x11vnc + noVNC), para poder ver
   el navegador del agente en tiempo real desde cualquier navegador
   (`http://<TAILSCALE_IP>:6080/vnc.html`). Costó bastante hacer entender
   que esto reemplaza la necesidad de tener Chrome instalado en Ubuntu.

2. **Primer proyecto de negocio: SERVIR** (ofertas laborales del estado
   peruano). Se validó la estructura de la página con ayuda de Claude
   para Chrome (mi propio `web_fetch` está bloqueado por el `robots.txt`
   del sitio, así que la inspección de estructura real se hizo por fuera,
   con esa extensión). El scraper terminó siendo bastante más elaborado
   de lo pensado inicialmente:
   - Formato de Excel prolijo (encabezados en negrita, colores, columnas
     anchas).
   - Columna **"No me interesa"** que el usuario marca con X — el sistema
     lo lee en la corrida siguiente y excluye esa oferta para siempre
     (tabla `servir_ofertas` en Postgres, ver `docs/STATE.md`).
   - Limpieza automática de ofertas vencidas.
   - Corrida diaria automática vía timer de systemd (**armado pero
     todavía NO instalado** al cierre de esta sesión — ver pendientes).

3. **Reorganización completa del repo** a una estructura versionable
   (`services/`, `schema/`, `docs/`, `infra/`), con git inicializado y
   subido a GitHub privado
   (`https://github.com/marcoantoniorobles-collab/ai-agents`). Esto fue
   un pedido explícito a mitad de sesión — el usuario se dio cuenta de
   que veníamos trabajando en modo "parche urgente" (zips sueltos,
   versiones v2, v3... v7) y pidió parar y ordenar antes de seguir.

4. **Dashboard web** (`/dashboard` en la API) — no estaba en el plan
   original de esta sesión, pero el usuario preguntó por el "módulo de
   monitoreo" que faltaba del plan original (fase 6, nunca hecha).
   HTML/JS autocontenido, sin build, con auto-refresh, que muestra
   agentes + tareas + un botón para embeber el noVNC de un agente en un
   panel lateral.

## Bugs reales encontrados y corregidos (importante para no repetirlos)

1. **`Browser.new_context: no running event loop`** — RQ bifurca
   (`fork`) un proceso por tarea por defecto, lo cual rompe el Chromium
   persistente. Fix: usar `SimpleWorker` de RQ en vez de `Worker` en los
   agentes con navegador.
2. **Clave única incorrecta en `servir_ofertas`** — se asumió que
   (`numero_convocatoria`, `entidad`) era única; en la práctica una misma
   entidad repite el mismo número de convocatoria para puestos distintos.
   Fix: agregar `titulo` a la clave (3 columnas).
3. **Timeout de RQ matando la corrida real de 338 páginas** — el default
   de RQ (180s) mataba el proceso completo a mitad de la corrida, sin
   dejar rastro recuperable (tarea quedaba en `RUNNING` para siempre en
   Postgres). Fix: `job_timeout=3600` explícito en todos los
   `enqueue()`/`enqueue_in()`.
4. **tzdata interactivo colgando el build de Docker** — al instalar
   paquetes de VNC, `tzdata` preguntaba la zona horaria de forma
   interactiva. Fix: `ENV DEBIAN_FRONTEND=noninteractive` en el
   Dockerfile.

## Estado al cierre de esta sesión

Ver `docs/STATE.md` para el detalle completo y actualizado. En resumen:
toda la infraestructura y el dashboard están funcionando y probados. La
corrida real completa de SERVIR (338 páginas) se lanzó con el fix del
timeout ya aplicado — **falta confirmar que terminó bien** (puede haberse
completado ya, o seguir en curso, dependiendo de cuándo se retome esto).

## Pendientes concretos para la próxima sesión

1. Confirmar el resultado de la corrida real de SERVIR (`GET /tasks/<id>`
   de la última tarea `servir_daily_sync` lanzada, o mirar el dashboard).
2. Instalar el timer de systemd (`infra/systemd/`) — los archivos ya
   están listos en el repo, solo falta copiarlos a `/etc/systemd/system/`
   y activarlos (pasos en `README.md`).
3. Verificar que el `.env` real (con la contraseña de Postgres) sigue
   intacto en `~/ai-agents/.env` — nunca se subió a git (por diseño,
   está en `.gitignore`), así que si se reconstruye la VM desde cero
   hay que regenerarlo.
4. Cuando se defina el segundo agente/proyecto, seguir el patrón de
   `docs/AGENT_PROTOCOL.md`.
