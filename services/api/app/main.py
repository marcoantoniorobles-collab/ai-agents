import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .agent_manager import start_heartbeat_monitor, stop_heartbeat_monitor
from .config import settings
from .database import SessionLocal
from .routers import agents, tasks

logging.basicConfig(level=logging.INFO)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    heartbeat_task = start_heartbeat_monitor()
    yield
    await stop_heartbeat_monitor(heartbeat_task)


app = FastAPI(title="AI Agents — Control API", lifespan=lifespan)

app.include_router(agents.router)
app.include_router(tasks.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/dashboard", tags=["dashboard"])
def dashboard():
    """Panel de control: estado de agentes, tareas y monitoreo SERVIR en vivo."""
    return FileResponse(os.path.join(STATIC_DIR, "dashboard.html"))


@app.get("/servir/stats", tags=["servir"])
def servir_stats():
    """
    Estado actual del scraper SERVIR.
    Devuelve progreso de la corrida activa (desde Redis) y conteo de ofertas en BD.
    Consumido por el dashboard de monitoreo cada 5 segundos.
    """
    # ── Progreso desde Redis ──────────────────────────────────────────────────
    progress: dict = {}
    try:
        import redis as _redis_lib
        r = _redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        raw = r.get("servir:progress")
        if raw:
            progress = json.loads(raw)
    except Exception:
        pass  # Redis no disponible o clave inexistente → dict vacío

    # ── Conteo y última actualización desde PostgreSQL ────────────────────────
    db_count = 0
    last_seen = None
    try:
        from sqlalchemy import text
        db = SessionLocal()
        row = db.execute(
            text(
                "SELECT COUNT(*) AS total, MAX(last_seen_at) AS ultima "
                "FROM servir_ofertas WHERE removed_by_user = false"
            )
        ).fetchone()
        db.close()
        if row:
            db_count = int(row.total or 0)
            last_seen = row.ultima.isoformat() if row.ultima else None
    except Exception:
        pass

    return {
        "progress": progress,   # status, current_page, total_pages, offers_scraped, started_at, updated_at, error
        "db_count": db_count,   # ofertas activas en BD
        "last_seen": last_seen, # ISO timestamp de la última actualización
    }
