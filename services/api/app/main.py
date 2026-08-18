import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .agent_manager import start_heartbeat_monitor, stop_heartbeat_monitor
from .routers import agents, tasks

logging.basicConfig(level=logging.INFO)


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
