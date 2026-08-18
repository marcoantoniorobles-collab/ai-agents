"""
run_task(task_id): esto es lo que RQ ejecuta por cada job en la cola
"tasks" (referenciado desde la API como "worker.jobs.run_task").

Flujo por tarea:
  1. Marca la tarea RUNNING en Postgres.
  2. Busca el handler según task_type y lo ejecuta con el payload.
  3. Si tiene éxito: guarda execution_history COMPLETED, marca la tarea
     COMPLETED.
  4. Si falla: guarda execution_history FAILED, incrementa retry_count.
       - Si retry_count < max_retries: vuelve a PENDING y se re-encola en
         RQ con backoff exponencial (enqueue_in).
       - Si no: la tarea pasa a DEAD (dead-letter), queda para revisión
         manual en el futuro dashboard.

Postgres es la fuente de verdad en todo momento: si el worker se cae a
mitad de un intento, la tarea queda RUNNING y el Agent Manager (fase 3)
la re-encola cuando detecta el agente OFFLINE. Nota: esto último aplica
a tareas de agentes con heartbeat; el worker genérico en sí no registra
heartbeat todavía — eso se agrega si/cuando haga falta diferenciar
workers individuales.
"""

import logging
from datetime import datetime, timedelta, timezone

from .database import SessionLocal
from .models import ExecutionHistory, Task
from .queue import task_queue
from .registry import get_handler

logger = logging.getLogger("worker")

BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300  # 5 minutos, tope del backoff exponencial


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
            output = handler(task.payload)
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
    task_queue.enqueue_in(timedelta(seconds=delay), "worker.jobs.run_task", str(task.id))
    logger.warning(
        "Tarea %s falló (intento %s/%s, task_type=%s), reintenta en %ss: %s",
        task.id, task.retry_count, task.max_retries, task.task_type, delay, error_text,
    )
