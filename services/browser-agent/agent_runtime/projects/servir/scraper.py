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
import os
import random
import re
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select

from ...browser_manager import BrowserManager
from ...database import SessionLocal
from ...models import ServirOferta

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


MARK_COLUMN_HEADER = "No me interesa"
MARK_VALUES = {"X", "SI", "SÍ", "YES", "1", "S"}

HEADER_FILL = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
ROW_FILL_EVEN = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
COLUMN_WIDTHS = [45, 38, 4, 4, 26, 24, 10, 16, 16, 16, 16]  # incluye las 2 vacías + marca


def _write_excel_formatted(rows: list[dict[str, str]], output_path: str) -> None:
    """Escribe el Excel final con encabezados en negrita, ancho de columnas
    prolijo, filas alternadas, y la columna 'No me interesa' vacía al final
    (lista para que el usuario la marque)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Ofertas Laborales"

    headers = EXCEL_HEADERS + [MARK_COLUMN_HEADER]
    ws.append(headers)
    for col_idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"

    for i, row in enumerate(rows, start=2):
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
            None,  # columna "No me interesa", vacía
        ])
        if i % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=i, column=col_idx).fill = ROW_FILL_EVEN

    for col_idx, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    wb.save(output_path)


def _read_marked_keys(output_path: str) -> set[tuple[str, str, str]]:
    """Lee el Excel existente (si existe) y devuelve el conjunto de claves
    (numero_convocatoria, entidad, titulo) que el usuario marcó como
    'No me interesa'. El título se incluye en la clave porque una misma
    entidad puede repetir el mismo número de convocatoria para varios
    puestos distintos (ej: '1 chofer / 1 secretaria' bajo la misma
    convocatoria transitoria)."""
    if not os.path.exists(output_path):
        return set()

    try:
        wb = load_workbook(output_path, data_only=True)
        ws = wb.active
        header_row = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    except Exception as exc:
        logger.warning("No se pudo leer el Excel previo para detectar marcas: %s", exc)
        return set()

    try:
        idx_titulo = header_row.index("Título de Convocatoria")
        idx_num = header_row.index("Número de Convocatoria")
        idx_ent = header_row.index("Entidad")
        idx_mark = header_row.index(MARK_COLUMN_HEADER)
    except ValueError:
        logger.warning("El Excel previo no tiene las columnas esperadas, no se detectan marcas")
        return set()

    marked: set[tuple[str, str, str]] = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if idx_mark >= len(row):
            continue
        mark_value = row[idx_mark]
        if mark_value and str(mark_value).strip().upper() in MARK_VALUES:
            titulo = str(row[idx_titulo] or "").strip()
            numero = str(row[idx_num] or "").strip()
            entidad = str(row[idx_ent] or "").strip()
            if numero and entidad and titulo:
                marked.add((numero, entidad, titulo))
    return marked


def sync_servir_daily(payload: dict[str, Any], browser: BrowserManager) -> dict[str, Any]:
    """
    Corrida diaria completa:
      1. Lee el Excel de trabajo actual y detecta qué filas marcó el usuario
         con 'X' en la columna 'No me interesa'.
      2. Aplica esas marcas de forma permanente en Postgres (servir_ofertas).
      3. Recorre TODAS las páginas de SERVIR (recomendado correr sin límite).
      4. Actualiza Postgres: ofertas nuevas se agregan, las que siguen
         publicadas actualizan su last_seen_at, las marcadas no se vuelven a
         mostrar aunque sigan activas.
      5. Si el recorrido fue completo (sin páginas fallidas), las ofertas que
         ya no aparecieron en SERVIR se consideran vencidas y se excluyen.
         Si hubo páginas fallidas, no se excluye nada por las dudas (para no
         perder ofertas válidas por un fallo puntual de red).
      6. Escribe el Excel final (mismo nombre siempre) con formato prolijo.
    """
    url = payload.get("url", DEFAULT_URL)
    session_label = payload.get("session_label", "servir")
    max_pages = payload.get("max_pages")  # None = todas las páginas (recomendado para uso diario)

    output_filename = payload.get("filename", "Ofertas_SERVIR_activas.xlsx")
    output_path = f"/app/output/{output_filename}"

    run_time = datetime.now(timezone.utc)

    # --- Paso 1 y 2: detectar y aplicar marcas del usuario ---
    marked_keys = _read_marked_keys(output_path)
    db = SessionLocal()
    try:
        for numero, entidad, titulo in marked_keys:
            oferta = db.scalar(
                select(ServirOferta).where(
                    ServirOferta.numero_convocatoria == numero,
                    ServirOferta.entidad == entidad,
                    ServirOferta.titulo == titulo,
                )
            )
            if oferta and not oferta.removed_by_user:
                oferta.removed_by_user = True
                oferta.removed_by_user_at = run_time
        db.commit()
    finally:
        db.close()

    # --- Paso 3: recorrer SERVIR (reutiliza la misma lógica de paginación) ---
    context = browser.get_context(session_label)
    page = context.new_page()

    all_rows: list[dict[str, str]] = []
    failed_pages: list[int] = []
    pages_scraped = 0
    stopped_early = False
    error_detail = None

    try:
        page.goto(url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(4000)

        label_text = _get_page_label_text(page)
        total_pages = _parse_total_pages(label_text)
        target_pages = min(max_pages, total_pages) if max_pages else total_pages
        logger.info("SERVIR (sync diario): recorriendo %s de %s páginas", target_pages, total_pages)

        current_page_num = 1
        while current_page_num <= target_pages:
            try:
                rows = _extract_current_page(page)
                all_rows.extend(rows)
                pages_scraped += 1
            except Exception as exc:
                logger.warning("Fallo extrayendo la página %s: %s", current_page_num, exc)
                failed_pages.append(current_page_num)

            if pages_scraped % 20 == 0 or current_page_num == target_pages:
                logger.info(
                    "SERVIR (sync diario): progreso %s/%s páginas, %s ofertas recolectadas hasta ahora",
                    current_page_num, target_pages, len(all_rows),
                )

            if current_page_num >= target_pages:
                break

            try:
                label_text = _get_page_label_text(page)
                _go_to_next_page(page, label_text)
            except Exception as exc:
                logger.error("Fallo avanzando desde la página %s: %s — se corta acá", current_page_num, exc)
                stopped_early = True
                error_detail = str(exc)
                break

            current_page_num += 1
            _humanized_pause(page, current_page_num)

    except Exception as exc:
        logger.error("Fallo irrecuperable en sync_servir_daily: %s", exc)
        stopped_early = True
        error_detail = str(exc)
    finally:
        page.close()

    recorrido_completo = not stopped_early and not failed_pages

    # --- Paso 4: upsert en Postgres (commit por fila: un fallo puntual en
    # una oferta no debe perder el resto del progreso ya guardado) ---
    db = SessionLocal()
    nuevas = 0
    try:
        for row in all_rows:
            numero = row.get("numero_convocatoria", "").strip()
            entidad = row.get("entidad", "").strip()
            titulo = row.get("titulo", "").strip()
            if not numero or not entidad or not titulo:
                continue  # sin clave confiable, no se puede rastrear de forma persistente

            try:
                oferta = db.scalar(
                    select(ServirOferta).where(
                        ServirOferta.numero_convocatoria == numero,
                        ServirOferta.entidad == entidad,
                        ServirOferta.titulo == titulo,
                    )
                )
                if oferta:
                    oferta.ubicacion = row.get("ubicacion", "")
                    oferta.vacantes = row.get("vacantes", "")
                    oferta.remuneracion = row.get("remuneracion", "")
                    oferta.fecha_inicio = row.get("fecha_inicio", "")
                    oferta.fecha_fin = row.get("fecha_fin", "")
                    oferta.last_seen_at = run_time
                else:
                    db.add(ServirOferta(
                        numero_convocatoria=numero,
                        entidad=entidad,
                        titulo=titulo,
                        ubicacion=row.get("ubicacion", ""),
                        vacantes=row.get("vacantes", ""),
                        remuneracion=row.get("remuneracion", ""),
                        fecha_inicio=row.get("fecha_inicio", ""),
                        fecha_fin=row.get("fecha_fin", ""),
                        first_seen_at=run_time,
                        last_seen_at=run_time,
                        removed_by_user=False,
                    ))
                    nuevas += 1
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("Fallo guardando oferta '%s' (%s / %s): %s", titulo, numero, entidad, exc)

        # --- Paso 5: decidir qué mostrar ---
        if recorrido_completo:
            # Solo lo confirmado presente HOY y no marcado por el usuario.
            activas = db.scalars(
                select(ServirOferta).where(
                    ServirOferta.last_seen_at == run_time,
                    ServirOferta.removed_by_user.is_(False),
                )
            ).all()
            # Limpieza: lo que no se vio hoy y no está marcado ya venció, se borra.
            vencidas = db.scalars(
                select(ServirOferta).where(ServirOferta.last_seen_at < run_time)
            ).all()
            for v in vencidas:
                db.delete(v)
            db.commit()
        else:
            # Recorrido incompleto: no se descarta nada por las dudas, se
            # muestra todo lo no marcado, sin importar si se vio hoy.
            activas = db.scalars(
                select(ServirOferta).where(ServirOferta.removed_by_user.is_(False))
            ).all()

        final_rows = [
            {
                "titulo": o.titulo, "entidad": o.entidad, "ubicacion": o.ubicacion,
                "numero_convocatoria": o.numero_convocatoria, "vacantes": o.vacantes,
                "remuneracion": o.remuneracion, "fecha_inicio": o.fecha_inicio,
                "fecha_fin": o.fecha_fin,
            }
            for o in activas
        ]
    finally:
        db.close()

    # --- Paso 6: escribir el Excel final ---
    _write_excel_formatted(final_rows, output_path)

    result = {
        "output_file": output_filename,
        "total_activas_en_excel": len(final_rows),
        "nuevas_hoy": nuevas,
        "marcadas_no_interesa_hoy": len(marked_keys),
        "paginas_recorridas": pages_scraped,
        "paginas_fallidas": failed_pages,
        "recorrido_completo": recorrido_completo,
        "detalle_error": error_detail,
    }
    logger.info("SERVIR (sync diario): finalizado — %s", result)
    return result


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
