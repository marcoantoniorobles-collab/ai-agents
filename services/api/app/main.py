import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .agent_manager import start_heartbeat_monitor, stop_heartbeat_monitor
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
    """Panel de control: estado de agentes y tareas recientes, en vivo
    (auto-refresh cada 4s). Sin build, sin dependencias externas — un solo
    archivo HTML/JS que consulta /agents y /tasks."""
    return FileResponse(os.path.join(STATIC_DIR, "dashboard.html"))
