import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..queue import enqueue_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=schemas.TaskOut, status_code=201)
def create_task(payload: schemas.TaskCreate, db: Session = Depends(get_db)):
    """
    Inserta la tarea en Postgres (fuente de verdad) y la encola en RQ.

    Si payload.agent_id viene definido, la tarea se encola en la cola
    dedicada de ese agente (necesario para cualquier task_type que use
    Playwright/navegador, ya que el Chromium y las sesiones viven en ese
    proceso específico). Si no, va a la cola genérica sin navegador.

    Si scheduled_at está en el futuro, se guarda como PENDING sin encolar
    todavía (encolar tareas programadas cuando llegue su hora queda fuera
    del alcance de esta fase).
    """
    task = models.Task(
        task_type=payload.task_type,
        payload=payload.payload,
        priority=payload.priority,
        max_retries=payload.max_retries,
        agent_id=payload.agent_id,
        scheduled_at=payload.scheduled_at,
        status="PENDING",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    is_due_now = payload.scheduled_at is None or payload.scheduled_at <= datetime.now(timezone.utc)
    if is_due_now:
        enqueue_task(str(task.id), str(task.agent_id) if task.agent_id else None)
        task.status = "QUEUED"
        db.commit()
        db.refresh(task)

    return task


@router.get("", response_model=list[schemas.TaskOut])
def list_tasks(
    status: str | None = None,
    agent_id: uuid.UUID | None = None,
    task_type: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = select(models.Task)
    if status:
        query = query.where(models.Task.status == status)
    if agent_id:
        query = query.where(models.Task.agent_id == agent_id)
    if task_type:
        query = query.where(models.Task.task_type == task_type)
    query = query.order_by(models.Task.created_at.desc()).limit(limit)
    return db.scalars(query).all()


@router.get("/{task_id}", response_model=schemas.TaskOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


@router.patch("/{task_id}/status", response_model=schemas.TaskOut)
def update_task_status(task_id: uuid.UUID, payload: schemas.TaskStatusUpdate, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    valid_statuses = {"PENDING", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "DEAD"}
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"status inválido: {payload.status}")

    task.status = payload.status
    task.error_message = payload.error_message
    if payload.status == "RUNNING" and task.started_at is None:
        task.started_at = datetime.now(timezone.utc)
    if payload.status in {"COMPLETED", "FAILED", "DEAD"}:
        task.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(task)
    return task
