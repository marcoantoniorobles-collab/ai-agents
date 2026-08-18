"""
Registro de handlers de tareas.

Cada agente eventualmente va a tener su propia lógica de negocio por
task_type (todavía no implementada — eso es fase 7 del plan). Por ahora
solo existe un handler de prueba ("ping") para validar que el circuito
completo funciona: API -> Postgres -> Redis/RQ -> worker -> Postgres.

Para agregar lógica real más adelante: escribir una función que reciba el
payload (dict) y devuelva un dict con el resultado, y registrarla acá con
su task_type correspondiente.
"""

from typing import Any, Callable

TaskHandler = Callable[[dict[str, Any]], dict[str, Any]]


def ping_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Handler de prueba: simplemente devuelve el payload recibido."""
    return {"echo": payload}


TASK_HANDLERS: dict[str, TaskHandler] = {
    "ping": ping_handler,
}


def get_handler(task_type: str) -> TaskHandler | None:
    return TASK_HANDLERS.get(task_type)
