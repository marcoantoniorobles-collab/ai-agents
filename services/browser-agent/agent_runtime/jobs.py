"""
run_task(task_id): lo que RQ ejecuta por cada job en la cola dedicada de
este agente ("agent:<agent_id>", referenciado desde la API como
"agent_runtime.jobs.run_task").

Mismo flujo de estados/retry/backoff/DEAD que worker/jobs.py (fase 4); la
diferencia es que acá el handler recibe también el BrowserManager del
agente, y los reintentos se re-encolan en la cola propia del agente (no en
la cola genérica "tasks"), porque solo este proceso tiene el Chromium y las
sesiones de este agente.
"""

import logging
from datetime import datetime, timedelta, timezone

from rq import Queue

from .database import SessionLocal
from .models import ExecutionHistory, Task
from .registry import get_handler

logger = logging.getLogger("agent_runtime.jobs")

BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300

# Configurados por run_agent.py al arrancar, antes de escuchar la cola.
_browser_manager = None
_retry_queue: Queue | None = None


def set_browser_manager(browser_manager) -> None:
    global _browser_manager
    _browser_manager = browser_manager


def set_retry_queue(queue: Queue) -> None:
    global _retry_queue
    _retry_queue = queue


def _backoff_seconds(retry_count: int) -> int:
    return min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** retry_count))


def run_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            logger.warning("run_task: tarea %s no existe en Postgres, se ignora", task_id)
            return

        attempt_number = task.retry_count + 1
        task.status = "RUNNING"
        if task.started_at is None:
            task.started_at = datetime.now(timezone.utc)
        db.commit()

        started_at = datetime.now(timezone.utc)
        handler = get_handler(task.task_type)

        try:
            if handler is None:
                raise ValueError(f"No hay handler registrado para task_type='{task.task_type}'")
            output = handler(task.payload, _browser_manager)
        except Exception as exc:
            _handle_failure(db, task, attempt_number, started_at, exc)
        else:
            _handle_success(db, task, attempt_number, started_at, output)
    finally:
        db.close()


def _handle_success(db, task: Task, attempt_number: int, started_at: datetime, output: dict) -> None:
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    db.add(ExecutionHistory(
        task_id=task.id,
        agent_id=task.agent_id,
        attempt_number=attempt_number,
        status="COMPLETED",
        output=output,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    ))
    task.status = "COMPLETED"
    task.completed_at = finished_at
    task.error_message = None
    db.commit()
    logger.info("Tarea %s completada (task_type=%s)", task.id, task.task_type)


def _handle_failure(db, task: Task, attempt_number: int, started_at: datetime, exc: Exception) -> None:
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    error_text = str(exc)

    db.add(ExecutionHistory(
        task_id=task.id,
        agent_id=task.agent_id,
        attempt_number=attempt_number,
        status="FAILED",
        error=error_text,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    ))

    task.retry_count += 1
    task.error_message = error_text

    if task.retry_count >= task.max_retries:
        task.status = "DEAD"
        task.completed_at = finished_at
        db.commit()
        logger.error(
            "Tarea %s pasó a DEAD tras %s intentos (task_type=%s): %s",
            task.id, task.retry_count, task.task_type, error_text,
        )
        return

    task.status = "PENDING"
    db.commit()

    delay = _backoff_seconds(task.retry_count)
    _retry_queue.enqueue_in(
        timedelta(seconds=delay), "agent_runtime.jobs.run_task", str(task.id),
        job_timeout=-1,
    )
    logger.warning(
        "Tarea %s falló (intento %s/%s, task_type=%s), reintenta en %ss: %s",
        task.id, task.retry_count, task.max_retries, task.task_type, delay, error_text,
    )
