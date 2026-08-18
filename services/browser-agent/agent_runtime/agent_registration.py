"""
Al arrancar, cada contenedor agent_runtime:
  1. Se auto-registra (o actualiza) su propia fila en `agents`, usando
     AGENT_NAME como identificador estable.
  2. Arranca un hilo en background que actualiza last_heartbeat cada
     heartbeat_interval_seconds, para que el Agent Manager de la API lo siga
     viendo ONLINE.

Esto reemplaza la necesidad de llamar al endpoint HTTP /agents/heartbeat:
como este proceso ya tiene acceso directo a Postgres (igual que el worker
genérico), es más simple escribir directo que ir por la API.
"""

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import Agent

logger = logging.getLogger("agent_registration")


def upsert_agent(name: str) -> Agent:
    db = SessionLocal()
    try:
        agent = db.scalar(select(Agent).where(Agent.name == name))
        now = datetime.now(timezone.utc)
        metadata = {"runtime": "playwright", "vnc_enabled": settings.enable_vnc}
        if agent:
            agent.status = "ONLINE"
            agent.last_heartbeat = now
            agent.metadata_ = metadata  # refleja el ENABLE_VNC actual, por si cambió
        else:
            agent = Agent(
                name=name,
                status="ONLINE",
                last_heartbeat=now,
                metadata_=metadata,
            )
            db.add(agent)
        db.commit()
        db.refresh(agent)
        return agent
    finally:
        db.close()


def _heartbeat_loop(agent_id, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            agent = db.get(Agent, agent_id)
            if agent:
                agent.last_heartbeat = datetime.now(timezone.utc)
                agent.status = "ONLINE"
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Error actualizando heartbeat")
        finally:
            db.close()
        stop_event.wait(settings.heartbeat_interval_seconds)


def start_heartbeat_thread(agent_id) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    thread = threading.Thread(target=_heartbeat_loop, args=(agent_id, stop_event), daemon=True)
    thread.start()
    return thread, stop_event
