"""
Igual que en el worker genérico (fase 4): sin lógica de negocio real
todavía. Acá cada handler recibe además el BrowserManager del agente, para
poder abrir páginas dentro de un contexto/sesión persistente.
"""

from typing import Any, Callable

from .browser_manager import BrowserManager
from .projects.servir.scraper import scrape_servir_ofertas, sync_servir_daily

BrowserTaskHandler = Callable[[dict[str, Any], BrowserManager], dict[str, Any]]


def echo_handler(payload: dict[str, Any], browser: BrowserManager) -> dict[str, Any]:
    """Handler simple sin navegador, por si se necesita en un agente."""
    return {"echo": payload}


def browser_ping_handler(payload: dict[str, Any], browser: BrowserManager) -> dict[str, Any]:
    """
    Handler de prueba: abre una página dentro de un BrowserContext (por
    session_label), navega a una URL, espera opcionalmente (para poder
    verla en vivo por noVNC), devuelve el título, y guarda el storageState
    de la sesión.
    """
    url = payload.get("url", "https://example.com")
    session_label = payload.get("session_label", "default")
    wait_seconds = payload.get("wait_seconds", 0)

    context = browser.get_context(session_label)
    page = context.new_page()
    try:
        page.goto(url, wait_until="load", timeout=60_000)
        title = page.title()
        if wait_seconds:
            page.wait_for_timeout(wait_seconds * 1000)
    finally:
        page.close()

    browser.save_session(session_label)
    return {"url": url, "title": title, "session_label": session_label}


def inspect_page_handler(payload: dict[str, Any], browser: BrowserManager) -> dict[str, Any]:
    """
    Navega a una URL, espera a que cargue, y guarda una captura de pantalla
    completa en /app/output (la carpeta compartida del agente). Pensado
    para inspeccionar visualmente una página sin necesidad de manejar el
    navegador a mano por noVNC.
    """
    url = payload.get("url")
    if not url:
        raise ValueError("payload.url es obligatorio para inspect_page")
    session_label = payload.get("session_label", "default")
    filename = payload.get("filename", "captura.png")
    wait_seconds = payload.get("wait_seconds", 3)

    context = browser.get_context(session_label)
    page = context.new_page()
    try:
        page.goto(url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(wait_seconds * 1000)
        title = page.title()
        screenshot_path = f"/app/output/{filename}"
        page.screenshot(path=screenshot_path, full_page=True)
    finally:
        page.close()

    return {"url": url, "title": title, "screenshot": filename}


def dump_html_handler(payload: dict[str, Any], browser: BrowserManager) -> dict[str, Any]:
    """
    Navega a una URL y guarda el HTML completo de la página en /app/output.
    Pensado para que Claude pueda analizar la estructura real de una página
    (tablas, formularios, paginación) sin necesidad de verla visualmente.
    """
    url = payload.get("url")
    if not url:
        raise ValueError("payload.url es obligatorio para dump_html")
    session_label = payload.get("session_label", "default")
    filename = payload.get("filename", "pagina.html")
    wait_seconds = payload.get("wait_seconds", 3)

    context = browser.get_context(session_label)
    page = context.new_page()
    try:
        page.goto(url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(wait_seconds * 1000)
        title = page.title()
        html = page.content()
        output_path = f"/app/output/{filename}"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
    finally:
        page.close()

    return {"url": url, "title": title, "html_file": filename, "html_length": len(html)}


TASK_HANDLERS: dict[str, BrowserTaskHandler] = {
    "ping": echo_handler,
    "browser_ping": browser_ping_handler,
    "inspect_page": inspect_page_handler,
    "dump_html": dump_html_handler,
    "scrape_servir_ofertas": scrape_servir_ofertas,
    "servir_daily_sync": sync_servir_daily,
}


def get_handler(task_type: str) -> BrowserTaskHandler | None:
    return TASK_HANDLERS.get(task_type)
