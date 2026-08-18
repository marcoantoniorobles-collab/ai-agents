"""
Agent Manager interno.

Vive dentro del proceso de la API (no es un microservicio separado, tal
como se definió en la auditoría de arquitectura). Corre un loop en
background que:

  1. Marca OFFLINE a los agentes cuyo last_heartbeat venció.
  2. Re-encola (status -> PENDING, agent_id -> NULL) las tareas que hayan
     quedado RUNNING colgadas de un agente recién marcado OFFLINE.

Si esto crece demasiado más adelante, puede extraerse a un servicio propio
sin tener que tocar el resto de la API.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .config import settings
from .database import SessionLocal

logger = logging.getLogger("agent_manager")


def _sweep_once() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.heartbeat_timeout_seconds)
    db = SessionLocal()
    try:
        offline_result = db.execute(
            text(
                """
                UPDATE agents
                SET status = 'OFFLINE'
                WHERE status != 'OFFLINE'
                  AND (last_heartbeat IS NULL OR last_heartbeat < :cutoff)
                RETURNING id
                """
            ),
            {"cutoff": cutoff},
        )
        offline_ids = [row[0] for row in offline_result.fetchall()]

        if offline_ids:
            db.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'PENDING', agent_id = NULL
                    WHERE status = 'RUNNING' AND agent_id = ANY(:ids)
                    """
                ),
                {"ids": offline_ids},
            )
            logger.info("Agentes OFFLINE: %s — tareas huérfanas re-encoladas", offline_ids)

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error en el sweep de heartbeat")
    finally:
        db.close()


async def _heartbeat_loop() -> None:
    while True:
        # _sweep_once es sync (SQLAlchemy sync engine); se corre en un thread
        # aparte para no bloquear el event loop de FastAPI.
        await asyncio.to_thread(_sweep_once)
        await asyncio.sleep(settings.heartbeat_check_interval_seconds)


def start_heartbeat_monitor() -> asyncio.Task:
    return asyncio.create_task(_heartbeat_loop())


async def stop_heartbeat_monitor(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
