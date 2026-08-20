# AI Agents — Plataforma Multi-Agente

Plataforma de automatización web basada en agentes Playwright independientes, con orquestación vía Redis/RQ, API FastAPI y panel de control en tiempo real. Diseñada para escalar horizontalmente: cada proyecto corre en su propio contenedor y puede eliminarse sin afectar al resto.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│  Ubuntu VM (VMware) — acceso vía Tailscale              │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐   │
│  │ FastAPI  │  │  Redis   │  │     PostgreSQL      │   │
│  │  :8000   │  │  :6379   │  │       :5432        │   │
│  └──────────┘  └──────────┘  └────────────────────┘   │
│       │              │                  │               │
│  ┌────▼──────────────▼──────────────────▼────────────┐ │
│  │               ai-network (Docker)                  │ │
│  └────────────────────────────────────────────────────┘ │
│       │              │                  │               │
│  ┌────▼────┐  ┌──────▼──┐  ┌───────────▼──┐           │
│  │ agent-1 │  │ agent-2 │  │   agent-3    │           │
│  │ SERVIR  │  │ futuro  │  │   futuro     │           │
│  │ VNC:6080│  │         │  │              │           │
│  └─────────┘  └─────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────┘
```

**Principio de diseño:** `1 proyecto = 1 agente = 1 contenedor = 1 cola RQ`

---

## Estructura del Repositorio

```
ai-agents/
├── docker-compose.yml              # postgres, redis, red ai-network
├── docker-compose.override.yml     # api, worker, agent-1/2/3
├── .env                            # credenciales (NO en repo)
├── schema/                         # scripts SQL de creación de tablas
│   ├── 001_schema_control.sql
│   └── 001_servir_ofertas.sql
├── services/
│   ├── api/                        # FastAPI
│   │   └── app/
│   │       ├── main.py
│   │       └── static/dashboard.html
│   ├── worker/                     # RQ worker global
│   └── browser-agent/             # imagen base de agentes
│       └── agent_runtime/
│           ├── models.py           # modelos compartidos (Agent, Task, Session, History)
│           ├── database.py
│           └── projects/
│               └── servir/         # proyecto aislado — eliminar esta carpeta = eliminar SERVIR
│                   ├── models.py   # ServirOferta (aislado)
│                   └── scraper.py
├── infra/
│   └── systemd/                    # timer para scraping diario (pendiente instalación)
└── docs/
    ├── ARCHITECTURE.md
    ├── STATE.md
    └── AGENT_PROTOCOL.md
```

---

## Requisitos

- Ubuntu 22.04+ (VM o bare metal)
- Docker Engine + Docker Compose v2
- Tailscale instalado y activo
- VMware Tools con `vmhgfs-fuse` (si se usa carpeta compartida con Windows)

---

## Instalación desde Cero

### 1. Clonar el repositorio

```bash
git clone https://github.com/marcoantoniorobles-collab/ai-agents.git ~/ai-agents
cd ~/ai-agents
```

### 2. Crear el archivo `.env`

```bash
cp .env.example .env
nano .env   # completar TAILSCALE_IP, DB_USER, DB_PASSWORD, etc.
```

Variables requeridas:

| Variable | Descripción |
|---|---|
| `TAILSCALE_IP` | IP de la máquina en la red Tailscale |
| `POSTGRES_USER` | Usuario de PostgreSQL |
| `POSTGRES_PASSWORD` | Contraseña de PostgreSQL |
| `POSTGRES_DB` | Nombre de la base de datos |
| `REDIS_URL` | URL de Redis (`redis://redis:6379/0`) |

### 3. Crear directorios de salida

```bash
mkdir -p ~/ai-output/agente-1 ~/ai-output/agente-2 ~/ai-output/agente-3
```

### 4. Levantar los servicios

```bash
docker compose up -d --build
docker compose ps   # verificar que todos están Up
```

### 5. Crear las tablas en PostgreSQL

```bash
# Ejecutar los scripts SQL en orden
docker exec -i ai-postgres psql -U aiadmin -d ai_agents < schema/001_schema_control.sql
docker exec -i ai-postgres psql -U aiadmin -d ai_agents < schema/001_servir_ofertas.sql
```

---

## Servicios

| Contenedor | Puerto | Descripción |
|---|---|---|
| `ai-api` | 8000 | FastAPI — dashboard y API REST |
| `ai-worker` | — | RQ worker (SimpleWorker, compatible con Playwright) |
| `ai-agent-1` | 6080 | Agente SERVIR, VNC habilitado |
| `ai-agent-2` | — | Agente libre (sin proyecto asignado) |
| `ai-agent-3` | — | Agente libre (sin proyecto asignado) |
| `postgres` | 5432 | Base de datos principal |
| `redis` | 6379 | Cola de tareas y progreso en tiempo real |

---

## URLs

| Servicio | URL |
|---|---|
| Dashboard | `http://<TAILSCALE_IP>:8000/dashboard` |
| VNC Agent-1 | `http://<TAILSCALE_IP>:6080/vnc_auto.html` |
| API Health | `http://<TAILSCALE_IP>:8000/health` |
| SERVIR Stats | `http://<TAILSCALE_IP>:8000/servir/stats` |
| API Docs | `http://<TAILSCALE_IP>:8000/docs` |

---

## API Endpoints

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/agents` | Lista todos los agentes y su estado |
| `GET` | `/agents/{id}` | Detalle de un agente |
| `POST` | `/agents/{id}/heartbeat` | Heartbeat del agente |
| `GET` | `/tasks` | Lista tareas recientes |
| `POST` | `/tasks` | Crear y encolar una nueva tarea |
| `GET` | `/tasks/{id}/status` | Estado de una tarea |
| `GET` | `/servir/stats` | Progreso del scraper SERVIR + conteo en BD |
| `GET` | `/health` | Estado general del sistema |
| `GET` | `/dashboard` | Panel de control HTML |

---

## Lanzar el Scraper SERVIR

### Corrida completa (todas las páginas)

```bash
AGENT_ID=$(curl -s http://localhost:8000/agents | python3 -c \
  "import sys,json; print([a['id'] for a in json.load(sys.stdin) if a['name']=='agent-1'][0])")

curl -s -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d "{\"task_type\": \"servir_daily_sync\", \"agent_id\": \"$AGENT_ID\", \"payload\": {}, \"priority\": 0}"
```

### Corrida de prueba (N páginas, sin eliminar datos existentes)

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d "{\"task_type\": \"servir_daily_sync\", \"agent_id\": \"$AGENT_ID\", \"payload\": {\"max_pages\": 3}, \"priority\": 0}"
```

> **Nota:** Con `max_pages` definido, el scraper nunca elimina registros existentes aunque no los vea en la corrida parcial.

---

## Agregar un Nuevo Proyecto / Agente

1. Crear la carpeta del proyecto:
   ```bash
   mkdir -p services/browser-agent/agent_runtime/projects/mi-proyecto
   touch services/browser-agent/agent_runtime/projects/mi-proyecto/__init__.py
   touch services/browser-agent/agent_runtime/projects/mi-proyecto/models.py
   touch services/browser-agent/agent_runtime/projects/mi-proyecto/scraper.py
   ```

2. Añadir el bloque en `docker-compose.override.yml` (copiar de `agent-3`):
   ```yaml
   agent-4:
     build: ./services/browser-agent
     container_name: ai-agent-4
     environment:
       AGENT_NAME: agent-4
       ENABLE_VNC: "false"
     volumes:
       - /home/aiadmin/ai-output/agente-4:/app/output
     # ... resto igual que agent-3
   ```

3. Crear directorio de salida y levantar:
   ```bash
   mkdir -p ~/ai-output/agente-4
   docker compose up -d agent-4
   ```

4. Crear tabla SQL si el proyecto la necesita:
   ```bash
   docker exec -i ai-postgres psql -U aiadmin -d ai_agents < schema/002_mi_proyecto.sql
   ```

> **Aislamiento total:** Para eliminar un proyecto basta con borrar su carpeta en `projects/` y su tabla SQL. No afecta a otros agentes ni modelos compartidos.

---

## Modelos de Base de Datos

### Modelos compartidos (`agent_runtime/models.py`)

| Tabla | Descripción |
|---|---|
| `agents` | Registro de agentes (UUID, nombre, heartbeat, estado) |
| `tasks` | Cola e historial de tareas (tipo, payload, estado, reintentos) |
| `sessions` | Sesiones de navegador Playwright por agente |
| `execution_history` | Historial detallado de cada intento de ejecución |

> Las tablas **no** se crean con `create_all` — deben crearse con los scripts SQL en `schema/`.

### Modelos por proyecto

Cada proyecto define sus propios modelos en `projects/<nombre>/models.py`. Ejemplo: `servir_ofertas` está en `projects/servir/models.py`.

---

## VMware / Carpeta Compartida

Si el host es Windows con VMware Workstation:

```bash
# Montar carpeta compartida (necesario tras cada reinicio del VM)
sudo vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other

# La carpeta "AI Agents" de Google Drive aparece en:
ls "/mnt/hgfs/AI Agents/"
```

> Los volúmenes Docker **no** deben apuntar a `/mnt/hgfs/` — Docker daemon no puede crear directorios en mounts FUSE. Usar siempre rutas locales Ubuntu como `/home/aiadmin/ai-output/`.

---

## Seguridad

- Acceso exclusivo vía red Tailscale (sin puertos expuestos a internet)
- Dashboard sin autenticación adicional (la red privada es el perímetro)
- Credenciales en `.env` (excluido del repositorio vía `.gitignore`)
- Logs con rotación automática: máximo 10MB × 3 archivos por contenedor

---

## Comandos Útiles

```bash
# Estado de todos los contenedores
docker compose ps

# Logs de un agente en tiempo real
docker compose logs -f agent-1

# Reiniciar un agente
docker compose restart agent-1

# Reconstruir imagen y reiniciar
docker compose build --no-cache agent-1 && docker compose up -d agent-1

# Conectarse a PostgreSQL
docker exec -it ai-postgres psql -U aiadmin -d ai_agents

# Ver cola de Redis
docker exec -it ai-redis redis-cli LLEN rq:queue:default
```

---

## Estado Actual (2026-08-20)

- ✅ 7 contenedores operativos (postgres, redis, api, worker, agent-1/2/3)
- ✅ Dashboard funcional con monitoreo SERVIR en tiempo real
- ✅ Proyecto SERVIR aislado en `projects/servir/` (modelos y scraper independientes)
- ✅ VNC operativo en agent-1 (`http://<TAILSCALE_IP>:6080/vnc_auto.html`)
- 🔄 Corrida SERVIR completa en progreso (~3,229 ofertas)
- ⏳ Pendiente: instalar systemd timer para scraping diario automático
- ⏳ Pendiente: agent-2 (Coursera) y agent-3 (por definir)
