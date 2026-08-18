import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------- Agents ----------

class AgentRegister(BaseModel):
    name: str
    metadata: dict[str, Any] = {}


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    status: str
    last_heartbeat: datetime | None
    created_at: datetime
    updated_at: datetime
    # El atributo real en el modelo SQLAlchemy es "metadata_" (con guión
    # bajo, porque "metadata" está reservado por SQLAlchemy). Acá se
    # renombra para que la API lo devuelva como "metadata" normal.
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")


# ---------- Tasks ----------

class TaskCreate(BaseModel):
    task_type: str
    payload: dict[str, Any] = {}
    priority: int = 0
    max_retries: int = 3
    agent_id: uuid.UUID | None = None       # opcional: asignar a un agente específico
    scheduled_at: datetime | None = None    # opcional: tarea diferida


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID | None
    task_type: str
    payload: dict[str, Any]
    status: str
    priority: int
    retry_count: int
    max_retries: int
    error_message: str | None
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskStatusUpdate(BaseModel):
    """Usado por el worker (fase 4) para reportar el resultado de una tarea."""
    status: str
    error_message: str | None = None
