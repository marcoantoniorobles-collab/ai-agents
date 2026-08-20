"""
SERVIR Ofertas Laborales scraper.
Ruta destino: services/browser-agent/agent_runtime/projects/servir/scraper.py

Correcciones y mejoras vs versión anterior
==========================================
1. _go_to_next_page: reintentos (3), timeouts 60 s / 30 s, espera extra 1 500 ms
   tras cambio de etiqueta (race condition PrimeFaces).
2. _parse_remuneracion: extrae float desde "S/. 4,000.00" → 4000.00
3. _parse_fecha: convierte "DD/MM/YYYY" → datetime.date (Excel entiende fechas reales)
4. _parse_vacantes: extrae int desde "1"
5. _write_excel_formatted / _write_excel: escriben tipos nativos (int, float, date)
   con formatos de celda correctos; Excel ya no distorsiona los valores.
6. Carga inicial con wait_until="networkidle" (más estable que "load").
7. Log preciso cuando se detiene antes de terminar todas las páginas.
8. NUEVO _extract_detail_page: al hacer clic en "¡Ver más!" extrae el N° de Aviso
   MÁS los campos: Requerimiento, Experiencia, Formación Académica, Especialización.
   Se detiene en "Conocimientos" (todo lo que viene después no se captura).
   Activar con get_detail=True.
   WARNING: ~3-4 horas extra para 3 200 ofertas (~1 clic/seg aprox).

IMPORTANTE sobre los links de convocatoria
==========================================
SERVIR usa JSF puro (PrimeFaces). El botón "¡Ver más!" hace un POST de formulario
y lleva a detalle_ofertas_laborales.xhtml SIN parámetros en la URL. No existe una
URL estable por oferta. El único identificador visible es el "N° de Aviso"
(p. ej. 802776) que sólo aparece en la página de detalle.

Mapa de columnas Excel
======================
Col  1 → Título de Convocatoria
Col  2 → Entidad
Col  3 → (espaciador)
Col  4 → (espaciador)
Col  5 → Ubicación
Col  6 → Número de Convocatoria
Col  7 → Vacantes          (int)
Col  8 → Remuneración      (float, formato #,##0.00)
Col  9 → Fecha Inicio      (date, formato DD/MM/YYYY)
Col 10 → Fecha Fin         (date, formato DD/MM/YYYY)
Col 11 → Requerimiento     (texto largo — sólo si get_detail=True)
Col 12 → Experiencia       (texto largo — sólo si get_detail=True)
Col 13 → Formación Académica (texto largo — sólo si get_detail=True)
Col 14 → Especialización   (texto largo — sólo si get_detail=True)
Col 15 → No me interesa    (columna de marcado manual)
"""

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select

from ...browser_manager import BrowserManager
from ...database import SessionLocal
from ...models import ServirOferta

logger = logging.getLogger("agent_runtime.scrapers.servir")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
DEFAULT_URL = (
    "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/"
    "ofertas_laborales.xhtml"
)
CARDS_SELECTOR       = "form#frmLstOfertsLabo .cuadro-vacantes"
PAGE_LABEL_SELECTOR  = "label.btn-paginator-cnt"
NEXT_BUTTON_SELECTOR = "button:has-text('Sig.')"
VER_MAS_SELECTOR     = "a:has-text('¡Ver más!'), button:has-text('¡Ver más!')"

EXCEL_HEADERS = [
    "Título de Convocatoria",    # col  1
    "Entidad",                   # col  2
    None,                        # col  3  (espaciador)
    None,                        # col  4  (espaciador)
    "Ubicación",                 # col  5
    "Número de Convocatoria",    # col  6
    "Vacantes",                  # col  7  → int
    "Remuneración",              # col  8  → float "#,##0.00"
    "Fecha Inicio Publicación",  # col  9  → date  "DD/MM/YYYY"
    "Fecha Fin Publicación",     # col 10  → date  "DD/MM/YYYY"
    "Requerimiento",             # col 11  → texto (detalle)
    "Experiencia",               # col 12  → texto (detalle)
    "Formación Académica",       # col 13  → texto (detalle)
    "Especialización",           # col 14  → texto (detalle)
    "No me interesa",            # col 15  → marcado manual
]

# ---------------------------------------------------------------------------
# JS — extrae tarjetas del listado
# ---------------------------------------------------------------------------
EXTRACT_CARDS_JS = """
() => {
  const cards = Array.from(
    document.querySelectorAll('form#frmLstOfertsLabo .cuadro-vacantes')
  );
  return cards.map(card => {
    const titulo  = card.querySelector('.titulo-vacante label')
                        ?.innerText?.trim() || '';
    const entidad = card.querySelector('.nombre-entidad .detalle-sp')
                        ?.innerText?.trim() || '';
    const fields  = {};
    card.querySelectorAll('.col-sm-5 .row.box-mb .col-sm-12').forEach(row => {
      const label = row.querySelector('.sub-titulo')
                        ?.innerText?.trim().replace(/:\\s*$/, '') || '';
      const value = row.querySelector('.detalle-sp')
                        ?.innerText?.trim() || '';
      if (label) fields[label] = value;
    });
    return {
      titulo,
      entidad,
      ubicacion:            fields['Ubicación']                   || '',
      numero_convocatoria:  fields['Número de Convocatoria']      || '',
      vacantes:             fields['Cantidad de Vacantes']        || '',
      remuneracion:         fields['Remuneración']                || '',
      fecha_inicio:         fields['Fecha Inicio de Publicación'] || '',
      fecha_fin:            fields['Fecha Fin de Publicación']    || '',
    };
  });
}
"""

# ---------------------------------------------------------------------------
# JS — extrae campos de la página de DETALLE (después de "¡Ver más!")
# ---------------------------------------------------------------------------
EXTRACT_DETAIL_JS = r"""
() => {
  const STOP_KEY = /conocimientos/i;
  const TARGET_KEYS = {
    requerimiento:      /^requerimiento/i,
    experiencia:        /^experiencia/i,
    formacion_academica:/^formaci[oó]n\s+acad[eé]mica/i,
    especializacion:    /^especializaci[oó]n/i,
  };

  function nodeText(el) {
    return (el.innerText || el.textContent || '').trim();
  }

  const allEls = Array.from(document.body.querySelectorAll('*'));

  const result = {
    aviso_num:           '',
    requerimiento:       '',
    experiencia:         '',
    formacion_academica: '',
    especializacion:     '',
  };

  const bodyText = document.body.innerText || '';
  const avisoMatch = bodyText.match(/N[°º]\s*(\d{4,8})/);
  if (avisoMatch) result.aviso_num = avisoMatch[1];

  let currentKey = null;
  let stop = false;

  for (const el of allEls) {
    if (stop) break;

    const ownText = nodeText(el);
    if (!ownText) continue;

    if (STOP_KEY.test(ownText)) { stop = true; break; }

    let matchedKey = null;
    for (const [key, pattern] of Object.entries(TARGET_KEYS)) {
      if (pattern.test(ownText.replace(/:\s*$/, ''))) {
        matchedKey = key;
        break;
      }
    }

    if (matchedKey) {
      currentKey = matchedKey;
      const colonIdx = ownText.indexOf(':');
      if (colonIdx !== -1) {
        const inline = ownText.slice(colonIdx + 1).trim();
        if (inline) {
          result[currentKey] = inline;
          currentKey = null;
        }
      }
      continue;
    }

    if (currentKey && ownText.length > 1) {
      if (!result[currentKey]) {
        result[currentKey] = ownText;
      }
      currentKey = null;
    }
  }

  for (const k of Object.keys(result)) {
    if (typeof result[k] === 'string') {
      result[k] = result[k].replace(/\s{2,}/g, ' ').trim();
    }
  }

  return result;
}
"""

# ---------------------------------------------------------------------------
# Helpers de parseo
# ---------------------------------------------------------------------------

def _parse_remuneracion(raw: str) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[Ss]/\.\s*", "", raw).strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        logger.warning("No se pudo parsear remuneracion: %r", raw)
        return None


def _parse_fecha(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").date()
    except ValueError:
        logger.warning("No se pudo parsear fecha: %r", raw)
        return None


def _parse_vacantes(raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("No se pudo parsear vacantes: %r", raw)
        return None


# ---------------------------------------------------------------------------
# Paginador
# ---------------------------------------------------------------------------

def _get_page_label_text(page) -> str:
    try:
        return page.locator(PAGE_LABEL_SELECTOR).first.inner_text(timeout=5_000).strip()
    except Exception:
        return ""


def _parse_total_pages(label_text: str) -> int:
    m = re.search(r"de\s+(\d+)", label_text, re.IGNORECASE)
    return int(m.group(1)) if m else 1


def _humanized_pause(page, min_ms: int = 800, max_ms: int = 1800) -> None:
    import random
    page.wait_for_timeout(random.randint(min_ms, max_ms))


def _go_to_next_page(page) -> bool:
    next_btn = page.locator(NEXT_BUTTON_SELECTOR).first
    try:
        if next_btn.is_disabled(timeout=3_000):
            return False
    except Exception:
        return False

    label_before = _get_page_label_text(page)

    for attempt in range(1, 4):
        try:
            with page.expect_response(
                lambda r: "ofertas_laborales.xhtml" in r.url
                          and r.request.method == "POST",
                timeout=60_000,
            ):
                next_btn.click()

            page.wait_for_function(
                f"""
                () => {{
                    const el = document.querySelector('{PAGE_LABEL_SELECTOR}');
                    return el && el.innerText.trim() !== {repr(label_before)};
                }}
                """,
                timeout=30_000,
            )
            page.wait_for_timeout(1_500)
            return True

        except Exception as exc:
            logger.warning("Intento %d/3 de pasar página falló: %s", attempt, exc)
            if attempt < 3:
                page.wait_for_timeout(3_000)

    logger.error("No se pudo pasar de página tras 3 intentos.")
    return False


# ---------------------------------------------------------------------------
# Extracción de página de detalle
# ---------------------------------------------------------------------------

def _extract_detail_page(page, card_index: int) -> dict:
    empty = {
        "aviso_num": "", "requerimiento": "", "experiencia": "",
        "formacion_academica": "", "especializacion": "",
    }
    try:
        cards = page.locator(CARDS_SELECTOR).all()
        if card_index >= len(cards):
            return empty

        ver_mas = cards[card_index].locator(VER_MAS_SELECTOR).first
        with page.expect_response(
            lambda r: "detalle_ofertas_laborales.xhtml" in r.url
                      and r.request.method == "POST",
            timeout=30_000,
        ):
            ver_mas.click()

        page.wait_for_load_state("networkidle", timeout=20_000)
        detail: dict = page.evaluate(EXTRACT_DETAIL_JS)

    except Exception as exc:
        logger.warning("Error al abrir detalle (tarjeta %d): %s", card_index, exc)
        detail = empty

    try:
        page.go_back(wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(1_000)
    except Exception as exc:
        logger.warning("Error al volver del detalle (tarjeta %d): %s", card_index, exc)

    return detail


# ---------------------------------------------------------------------------
# Estilos Excel
# ---------------------------------------------------------------------------

DATE_FMT      = "DD/MM/YYYY"
CURRENCY_FMT  = "#,##0.00"
HEADER_FILL   = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT   = Font(bold=True, color="FFFFFF", size=11)
ALT_FILL      = PatternFill("solid", fgColor="D6E4F7")
CENTER_ALIGN  = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_ALIGN    = Alignment(horizontal="left",   vertical="center", wrap_text=True)

_COL_WIDTHS = {
    1:  40,
    2:  35,
    3:   5,
    4:   5,
    5:  30,
    6:  22,
    7:  10,
    8:  15,
    9:  18,
    10: 18,
    11: 50,
    12: 50,
    13: 50,
    14: 50,
    15: 20,
}


def _write_excel_formatted(path: str, rows: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ofertas SERVIR"

    for col_idx, header in enumerate(EXCEL_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header or "")
        cell.fill      = HEADER_FILL
        cell.font      = HEADER_FONT
        cell.alignment = CENTER_ALIGN

    for row_num, row in enumerate(rows, start=2):
        alt = (row_num % 2 == 0)

        def _put(col: int, value, fmt: str | None = None, align=LEFT_ALIGN):
            c = ws.cell(row=row_num, column=col, value=value)
            if alt:
                c.fill = ALT_FILL
            c.alignment = align
            if fmt:
                c.number_format = fmt
            return c

        _put(1,  row.get("titulo",               ""))
        _put(2,  row.get("entidad",              ""))
        _put(3,  "")
        _put(4,  "")
        _put(5,  row.get("ubicacion",            ""))
        _put(6,  row.get("numero_convocatoria",  ""), align=CENTER_ALIGN)
        _put(7,  _parse_vacantes(row.get("vacantes", "")))
        _put(8,  _parse_remuneracion(row.get("remuneracion", "")), CURRENCY_FMT, CENTER_ALIGN)
        _put(9,  _parse_fecha(row.get("fecha_inicio", "")),        DATE_FMT,     CENTER_ALIGN)
        _put(10, _parse_fecha(row.get("fecha_fin",    "")),        DATE_FMT,     CENTER_ALIGN)
        _put(11, row.get("requerimiento",       ""))
        _put(12, row.get("experiencia",         ""))
        _put(13, row.get("formacion_academica", ""))
        _put(14, row.get("especializacion",     ""))
        _put(15, "")

    for col_idx, width in _COL_WIDTHS.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A2"
    wb.save(path)
    logger.info("Excel guardado en %s (%d filas)", path, len(rows))


def _write_excel(path: str, rows: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active

    ws.append([
        "titulo", "entidad", "", "", "ubicacion",
        "numero_convocatoria", "vacantes", "remuneracion",
        "fecha_inicio", "fecha_fin",
        "requerimiento", "experiencia", "formacion_academica",
        "especializacion", "no_me_interesa",
    ])

    for row in rows:
        ws.append([
            row.get("titulo",               ""),
            row.get("entidad",              ""),
            "", "",
            row.get("ubicacion",            ""),
            row.get("numero_convocatoria",  ""),
            _parse_vacantes(row.get("vacantes",      "")),
            _parse_remuneracion(row.get("remuneracion", "")),
            _parse_fecha(row.get("fecha_inicio", "")),
            _parse_fecha(row.get("fecha_fin",    "")),
            row.get("requerimiento",        ""),
            row.get("experiencia",          ""),
            row.get("formacion_academica",  ""),
            row.get("especializacion",      ""),
            "",
        ])

    for row_cells in ws.iter_rows(min_row=2, min_col=8, max_col=10):
        row_cells[0].number_format = CURRENCY_FMT
        row_cells[1].number_format = DATE_FMT
        row_cells[2].number_format = DATE_FMT

    wb.save(path)


# ---------------------------------------------------------------------------
# Lectura de marcados ("No me interesa" en col 15)
# ---------------------------------------------------------------------------

def _read_marked_keys(path: str) -> set[tuple[str, str, str]]:
    if not path or not __import__("os").path.exists(path):
        return set()
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        marked: set[tuple[str, str, str]] = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row and len(row) >= 15 and row[14]:
                titulo   = str(row[0]  or "").strip()
                entidad  = str(row[1]  or "").strip()
                num_conv = str(row[5]  or "").strip()
                marked.add((num_conv, entidad, titulo))
        wb.close()
        return marked
    except Exception as exc:
        logger.warning("No se pudo leer marcados de %s: %s", path, exc)
        return set()


# ---------------------------------------------------------------------------
# Función principal de scraping
# ---------------------------------------------------------------------------

def scrape_servir_ofertas(
    url: str = DEFAULT_URL,
    get_detail: bool = False,
) -> list[dict]:
    """
    Recorre todas las páginas de SERVIR y devuelve lista de dicts.

    get_detail=True → hace clic en cada "¡Ver más!" para extraer
    Requerimiento, Experiencia, Formación Académica, Especialización.
    Tarda ~3-4 horas extra para 3 200 ofertas.
    """
    browser_mgr = BrowserManager.get_instance()
    page = browser_mgr.new_page()
    all_rows: list[dict] = []

    try:
        logger.info("Cargando página inicial: %s", url)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_selector(CARDS_SELECTOR, timeout=30_000)

        label_text  = _get_page_label_text(page)
        total_pages = _parse_total_pages(label_text)
        logger.info("Total de páginas detectadas: %d", total_pages)

        current_page = 1

        while True:
            logger.info("Extrayendo página %d / %d ...", current_page, total_pages)
            cards_data: list[dict] = page.evaluate(EXTRACT_CARDS_JS)

            if get_detail:
                for idx, card in enumerate(cards_data):
                    logger.debug("  Detalle tarjeta %d/%d ...", idx + 1, len(cards_data))
                    detail = _extract_detail_page(page, idx)
                    card.update(detail)
                    _humanized_pause(page, 500, 1_000)
            else:
                for card in cards_data:
                    card.setdefault("aviso_num",           "")
                    card.setdefault("requerimiento",       "")
                    card.setdefault("experiencia",         "")
                    card.setdefault("formacion_academica", "")
                    card.setdefault("especializacion",     "")

            all_rows.extend(cards_data)
            _humanized_pause(page)

            if current_page >= total_pages:
                logger.info(
                    "Scraping completado: %d páginas, %d ofertas.",
                    current_page, len(all_rows),
                )
                break

            success = _go_to_next_page(page)
            if not success:
                logger.warning(
                    "Detenido en página %d de %d (%d ofertas extraídas).",
                    current_page, total_pages, len(all_rows),
                )
                break

            current_page += 1

    finally:
        page.close()

    return all_rows


# ---------------------------------------------------------------------------
# Sincronización diaria con BD + Excel
# ---------------------------------------------------------------------------

def sync_servir_daily(
    excel_path: str | None = None,
    url: str = DEFAULT_URL,
    get_detail: bool = False,
    use_formatted_excel: bool = True,
) -> dict[str, Any]:
    """
    1. Scrapea todas las ofertas de SERVIR.
    2. Inserta / actualiza en servir_ofertas de Postgres.
    3. Genera Excel en excel_path (si se indica).

    get_detail=True activa extracción de campos del detalle (~3-4 h extra).
    """
    logger.info("=== sync_servir_daily START (get_detail=%s) ===", get_detail)
    rows = scrape_servir_ofertas(url=url, get_detail=get_detail)
    logger.info("Ofertas scrapeadas: %d", len(rows))

    inserted = 0
    updated  = 0

    with SessionLocal() as db:
        for row in rows:
            num_conv = row.get("numero_convocatoria", "").strip()
            entidad  = row.get("entidad",             "").strip()
            titulo   = row.get("titulo",              "").strip()

            if not num_conv or not entidad:
                continue

            existing = db.execute(
                select(ServirOferta).where(
                    ServirOferta.numero_convocatoria == num_conv,
                    ServirOferta.entidad             == entidad,
                    ServirOferta.titulo              == titulo,
                )
            ).scalar_one_or_none()

            now = datetime.now(timezone.utc)

            if existing:
                existing.ubicacion    = row.get("ubicacion",    "")
                existing.vacantes     = row.get("vacantes",     "")
                existing.remuneracion = row.get("remuneracion", "")
                existing.fecha_inicio = row.get("fecha_inicio", "")
                existing.fecha_fin    = row.get("fecha_fin",    "")
                existing.last_seen_at = now
                updated += 1
            else:
                db.add(ServirOferta(
                    numero_convocatoria = num_conv,
                    entidad             = entidad,
                    titulo              = titulo,
                    ubicacion           = row.get("ubicacion",    ""),
                    vacantes            = row.get("vacantes",     ""),
                    remuneracion        = row.get("remuneracion", ""),
                    fecha_inicio        = row.get("fecha_inicio", ""),
                    fecha_fin           = row.get("fecha_fin",    ""),
                    first_seen_at       = now,
                    last_seen_at        = now,
                ))
                inserted += 1

        db.commit()

    logger.info("BD → nuevas: %d, actualizadas: %d", inserted, updated)

    if excel_path:
        if use_formatted_excel:
            _write_excel_formatted(excel_path, rows)
        else:
            _write_excel(excel_path, rows)

    logger.info("=== sync_servir_daily END ===")
    return {
        "total_scraped": len(rows),
        "inserted":      inserted,
        "updated":       updated,
        "excel_path":    excel_path,
    }
