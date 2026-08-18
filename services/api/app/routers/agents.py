import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=schemas.AgentOut, status_code=201)
def register_agent(payload: schemas.AgentRegister, db: Session = Depends(get_db)):
    """
    Registra un agente nuevo, o si ya existe uno con ese name, lo devuelve
    actualizado (upsert simple por nombre). Pensado para que cada agente se
    registre solo al arrancar.
    """
    existing = db.scalar(select(models.Agent).where(models.Agent.name == payload.name))
    if existing:
        existing.metadata_ = payload.metadata
        existing.status = "ONLINE"
        existing.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    agent = models.Agent(
        name=payload.name,
        metadata_=payload.metadata,
        status="ONLINE",
        last_heartbeat=datetime.now(timezone.utc),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("", response_model=list[schemas.AgentOut])
def list_agents(status: str | None = None, db: Session = Depends(get_db)):
    query = select(models.Agent)
    if status:
        query = query.where(models.Agent.status == status)
    return db.scalars(query.order_by(models.Agent.name)).all()


@router.get("/{agent_id}", response_model=schemas.AgentOut)
def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    return agent


@router.post("/{agent_id}/heartbeat", response_model=schemas.AgentOut)
def heartbeat(agent_id: uuid.UUID, db: Session = Depends(get_db)):
    """El agente llama esto periódicamente (ej. cada 10-20s) para seguir ONLINE."""
    agent = db.get(models.Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    agent.last_heartbeat = datetime.now(timezone.utc)
    agent.status = "ONLINE"
    db.commit()
    db.refresh(agent)
    return agent
