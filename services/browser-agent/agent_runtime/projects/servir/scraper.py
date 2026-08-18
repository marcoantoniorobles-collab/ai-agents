"""
Scraper para el Sistema de Difusión de Ofertas Laborales de SERVIR
(https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml)

Estructura confirmada de la página (JSF/PrimeFaces, no es una <table>):
  - Contenedor: form#frmLstOfertsLabo
  - Cada oferta: div.cuadro-vacantes, con título en .titulo-vacante label,
    entidad en .nombre-entidad .detalle-sp, y 6 campos más como pares
    .sub-titulo (etiqueta) / .detalle-sp (valor) dentro de .col-sm-5.
  - Paginación: 2 barras (arriba/abajo) con botones de texto "Primero",
    "Atras", "Sig.", "Último", y una etiqueta "Página X de Y". Al hacer
    clic en "Sig." se dispara un POST AJAX a la misma URL (JSF ViewState),
    sin cambiar la URL ni recargar la página.

Diseño defensivo: un fallo en una página individual NO aborta todo el
recorrido. Se registra como página fallida y se sigue. El Excel se escribe
siempre con lo que se haya podido recolectar, incluso si el recorrido se
corta antes de llegar al final.
"""

import logging
import random
import re
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook

from .browser_manager import BrowserManager

logger = logging.getLogger("agent_runtime.scrapers.servir")

DEFAULT_URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

CARDS_SELECTOR = "form#frmLstOfertsLabo .cuadro-vacantes"
PAGE_LABEL_SELECTOR = "label.btn-paginator-cnt"
NEXT_BUTTON_SELECTOR = "button:has-text('Sig.')"

# Encabezados EXACTOS del Excel de referencia (incluye 2 columnas vacías,
# tal como venía en el archivo de muestra que compartió el usuario).
EXCEL_HEADERS = [
    "Título de Convocatoria", "Entidad", None, None, "Ubicación",
    "Número de Convocatoria", "Vacantes", "Remuneración",
    "Fecha Inicio Publicación", "Fecha Fin Publicación",
]

EXTRACT_CARDS_JS = """
() => {
  const cards = Array.from(document.querySelectorAll('form#frmLstOfertsLabo .cuadro-vacantes'));
  return cards.map(card => {
    const titulo = card.querySelector('.titulo-vacante label')?.innerText?.trim() || '';
    const entidad = card.querySelector('.nombre-entidad .detalle-sp')?.innerText?.trim() || '';
    const fields = {};
    card.querySelectorAll('.col-sm-5 .row.box-mb .col-sm-12').forEach(row => {
      const label = row.querySelector('.sub-titulo')?.innerText?.trim().replace(/:\\s*$/, '') || '';
      const value = row.querySelector('.detalle-sp')?.innerText?.trim() || '';
      if (label) fields[label] = value;
    });
    return {
      titulo, entidad,
      ubicacion: fields['Ubicación'] || '',
      numero_convocatoria: fields['Número de Convocatoria'] || '',
      vacantes: fields['Cantidad de Vacantes'] || '',
      remuneracion: fields['Remuneración'] || '',
      fecha_inicio: fields['Fecha Inicio de Publicación'] || '',
      fecha_fin: fields['Fecha Fin de Publicación'] || '',
    };
  });
}
"""


def _get_page_label_text(page) -> str:
    return page.locator(PAGE_LABEL_SELECTOR).first.inner_text()


def _parse_total_pages(label_text: str) -> int:
    match = re.search(r"P[aá]gina\s+\d+\s+de\s+(\d+)", label_text)
    if not match:
        raise ValueError(f"No se pudo interpretar el texto de paginación: '{label_text}'")
    return int(match.group(1))


def _humanized_pause(page, page_num: int) -> None:
    """Pausa aleatoria entre páginas para no saturar el servidor y evitar un
    patrón de request perfectamente regular. Cada ~20 páginas, una pausa
    más larga (simula que alguien se detuvo a leer)."""
    if page_num % 20 == 0:
        delay = random.uniform(8, 15)
    else:
        delay = random.uniform(2.5, 5.5)
    page.wait_for_timeout(int(delay * 1000))


def _go_to_next_page(page, current_label: str) -> None:
    """Hace clic en 'Sig.' y espera tanto la respuesta AJAX del servidor
    como la actualización real del DOM (la etiqueta de página cambia)."""
    with page.expect_response(
        lambda r: "ofertas_laborales.xhtml" in r.url and r.request.method == "POST",
        timeout=30_000,
    ):
        page.locator(NEXT_BUTTON_SELECTOR).first.click()

    page.wait_for_function(
        """(oldLabel) => {
            const el = document.querySelector('label.btn-paginator-cnt');
            return el && el.innerText !== oldLabel;
        }""",
        arg=current_label,
        timeout=15_000,
    )


def _extract_current_page(page) -> list[dict[str, str]]:
    return page.evaluate(EXTRACT_CARDS_JS)


def _write_excel(rows: list[dict[str, str]], output_path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ofertas Laborales"
    ws.append(EXCEL_HEADERS)

    for row in rows:
        ws.append([
            row.get("titulo", ""),
            row.get("entidad", ""),
            None,
            None,
            row.get("ubicacion", ""),
            row.get("numero_convocatoria", ""),
            row.get("vacantes", ""),
            row.get("remuneracion", ""),
            row.get("fecha_inicio", ""),
            row.get("fecha_fin", ""),
        ])

    wb.save(output_path)


def scrape_servir_ofertas(payload: dict[str, Any], browser: BrowserManager) -> dict[str, Any]:
    url = payload.get("url", DEFAULT_URL)
    session_label = payload.get("session_label", "servir")
    max_pages = payload.get("max_pages")  # None = recorrer todas las páginas
    start_page = payload.get("start_page", 1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = payload.get("filename", f"Ofertas_Laborales_SERVIR_{today}.xlsx")
    output_path = f"/app/output/{filename}"

    context = browser.get_context(session_label)
    page = context.new_page()

    all_rows: list[dict[str, str]] = []
    failed_pages: list[int] = []
    pages_scraped = 0
    stopped_early = False
    error_detail = None

    try:
        page.goto(url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(4000)  # deja asentar el growl inicial y el AJAX de carga

        label_text = _get_page_label_text(page)
        total_pages = _parse_total_pages(label_text)
        target_pages = min(max_pages, total_pages) if max_pages else total_pages
        logger.info(
            "SERVIR: %s páginas totales detectadas, recorriendo %s (desde página %s)",
            total_pages, target_pages, start_page,
        )

        # Si se pide arrancar más adelante que la página 1 (para reanudar un
        # recorrido cortado), avanzar sin extraer datos hasta llegar ahí.
        current_page_num = 1
        while current_page_num < start_page:
            label_text = _get_page_label_text(page)
            _go_to_next_page(page, label_text)
            current_page_num += 1
            _humanized_pause(page, current_page_num)

        while current_page_num <= target_pages:
            try:
                rows = _extract_current_page(page)
                all_rows.extend(rows)
                pages_scraped += 1
            except Exception as exc:
                logger.warning("Fallo extrayendo la página %s: %s", current_page_num, exc)
                failed_pages.append(current_page_num)

            if current_page_num >= target_pages:
                break

            try:
                label_text = _get_page_label_text(page)
                _go_to_next_page(page, label_text)
            except Exception as exc:
                logger.error(
                    "Fallo avanzando desde la página %s: %s — se corta el recorrido, "
                    "se guarda lo recolectado hasta acá",
                    current_page_num, exc,
                )
                stopped_early = True
                error_detail = str(exc)
                break

            current_page_num += 1
            _humanized_pause(page, current_page_num)

    except Exception as exc:
        # Fallo antes de poder extraer nada (ej: la página ni cargó).
        logger.error("Fallo irrecuperable en scrape_servir_ofertas: %s", exc)
        stopped_early = True
        error_detail = str(exc)
    finally:
        page.close()

    _write_excel(all_rows, output_path)

    result = {
        "output_file": filename,
        "total_ofertas_extraidas": len(all_rows),
        "paginas_recorridas": pages_scraped,
        "paginas_fallidas": failed_pages,
        "recorrido_completo": not stopped_early and not failed_pages,
        "detalle_error": error_detail,
    }
    logger.info("SERVIR: recorrido finalizado — %s", result)
    return result
