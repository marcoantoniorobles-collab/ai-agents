"""
BrowserManager: un solo proceso Chromium por agente (por contenedor), con
un BrowserContext separado por sesión lógica ("session_label") en vez de un
proceso Chrome completo por sesión. Esto es lo que reduce el consumo de RAM
frente al modelo "1 sesión = 1 proceso Chrome".

Las sesiones logueadas se persisten como storageState (JSON liviano: cookies
+ localStorage) en la tabla `sessions`, no como perfiles completos de Chrome.

Usa la API sync de Playwright a propósito: el worker RQ de este contenedor
procesa tareas de forma secuencial en un solo hilo (Worker.work() es
bloqueante), que es justamente el modelo que la API sync de Playwright
requiere (todo desde el mismo hilo).
"""

import logging
from datetime import datetime, timezone

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright
from sqlalchemy import select

from .database import SessionLocal
from .models import AgentSession

logger = logging.getLogger("browser_manager")


class BrowserManager:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}

    def start(self, headless: bool = True) -> None:
        self._playwright = sync_playwright().start()
        # --no-sandbox: corremos como root dentro del contenedor, Chromium
        # lo requiere en ese caso (headed o headless).
        self._browser = self._playwright.chromium.launch(headless=headless, args=["--no-sandbox"])
        logger.info("Chromium iniciado para agente %s (headless=%s)", self.agent_id, headless)

    def get_context(self, session_label: str) -> BrowserContext:
        """Devuelve el BrowserContext de esta sesión, creándolo (y cargando
        su storageState guardado, si existe) la primera vez que se pide."""
        if session_label in self._contexts:
            return self._contexts[session_label]

        storage_state = self._load_storage_state(session_label)
        context = (
            self._browser.new_context(storage_state=storage_state)
            if storage_state
            else self._browser.new_context()
        )
        self._contexts[session_label] = context
        return context

    def save_session(self, session_label: str) -> None:
        """Persiste el storageState actual del contexto (cookies/localStorage)
        en Postgres. Llamar después de un login o cualquier cambio de sesión
        que valga la pena conservar entre tareas."""
        context = self._contexts.get(session_label)
        if context is None:
            logger.warning("save_session: no hay contexto abierto para '%s'", session_label)
            return
        state = context.storage_state()
        self._persist_storage_state(session_label, state)

    def _load_storage_state(self, session_label: str) -> dict | None:
        db = SessionLocal()
        try:
            row = db.scalar(
                select(AgentSession).where(
                    AgentSession.agent_id == self.agent_id,
                    AgentSession.label == session_label,
                    AgentSession.status == "ACTIVE",
                )
            )
            return row.storage_state if row else None
        finally:
            db.close()

    def _persist_storage_state(self, session_label: str, state: dict) -> None:
        db = SessionLocal()
        try:
            row = db.scalar(
                select(AgentSession).where(
                    AgentSession.agent_id == self.agent_id,
                    AgentSession.label == session_label,
                )
            )
            if row:
                row.storage_state = state
                row.status = "ACTIVE"
            else:
                row = AgentSession(
                    agent_id=self.agent_id,
                    session_type="browser",
                    label=session_label,
                    storage_state=state,
                    status="ACTIVE",
                )
                db.add(row)
            db.commit()
            logger.info("Sesión '%s' guardada para agente %s", session_label, self.agent_id)
        finally:
            db.close()

    def stop(self) -> None:
        for context in list(self._contexts.values()):
            try:
                context.close()
            except Exception:
                logger.exception("Error cerrando un BrowserContext")
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Chromium detenido para agente %s", self.agent_id)
