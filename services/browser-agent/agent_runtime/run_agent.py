import logging

from rq import Queue
from rq.worker import SimpleWorker

from . import jobs
from .agent_registration import start_heartbeat_thread, upsert_agent
from .browser_manager import BrowserManager
from .config import settings
from .queue import redis_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_agent")


def main() -> None:
    agent = upsert_agent(settings.agent_name)
    logger.info("Agente registrado: name=%s id=%s", agent.name, agent.id)

    _heartbeat_thread, stop_heartbeat = start_heartbeat_thread(agent.id)

    browser = BrowserManager(agent.id)
    browser.start(headless=not settings.enable_vnc)
    jobs.set_browser_manager(browser)

    queue_name = f"agent:{agent.id}"
    queue = Queue(queue_name, connection=redis_conn)
    jobs.set_retry_queue(queue)

    logger.info("Escuchando cola '%s'", queue_name)
    # SimpleWorker: ejecuta cada job en ESTE MISMO proceso, sin bifurcar uno
    # nuevo (que es el comportamiento por defecto de Worker). Es necesario
    # acá porque el Chromium persistente vive en este proceso — si RQ
    # bifurcara un hijo por cada tarea, ese hijo no tendría acceso válido
    # al navegador ya abierto.
    worker = SimpleWorker([queue], connection=redis_conn)
    try:
        worker.work(with_scheduler=True)
    finally:
        stop_heartbeat.set()
        browser.stop()


if __name__ == "__main__":
    main()
