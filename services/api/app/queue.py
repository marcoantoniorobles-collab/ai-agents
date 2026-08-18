from redis import Redis
from rq import Queue

from .config import settings

redis_conn = Redis.from_url(settings.redis_url)
task_queue = Queue("tasks", connection=redis_conn)  # cola genérica, sin agente específico


def enqueue_task(task_id: str, agent_id: str | None = None) -> None:
    """
    Encola una referencia a la tarea (por id).

    - Si la tarea NO tiene agent_id: va a la cola genérica "tasks", que
      procesa el worker sin navegador (fase 4, "worker.jobs.run_task").
    - Si la tarea SÍ tiene agent_id: va a la cola dedicada de ese agente
      ("agent:<agent_id>"), que solo escucha el contenedor de ese agente
      específico (fase 5, "agent_runtime.jobs.run_task") — es el único
      proceso que tiene el Chromium y las sesiones de ese agente.

    Las tareas que necesitan navegador (Playwright) DEBEN crearse con
    agent_id explícito, apuntando a un agente concreto.
    """
    if agent_id:
        agent_queue = Queue(f"agent:{agent_id}", connection=redis_conn)
        agent_queue.enqueue(
            "agent_runtime.jobs.run_task",
            task_id,
            job_id=task_id,
            result_ttl=86400,
            failure_ttl=86400,
        )
    else:
        task_queue.enqueue(
            "worker.jobs.run_task",
            task_id,
            job_id=task_id,
            result_ttl=86400,
            failure_ttl=86400,
        )
