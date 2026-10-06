"""Interpretación de fechas y horas en español tal como aparecen en PuntoTicket.

Formatos vistos en la planilla de avance:
    "19 de octubre 2026", "29 de Octubre 2026", "4 DE NOVIEMBRE 2026",
    "5 de diciembre" (sin año), "19-10-2026" (atributo datetime de <time>).
"""
import re
from datetime import date, datetime

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

_RE_TEXTO = re.compile(
    r"(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")(?:\s+(?:de(?:l)?\s+)?(20\d{2}))?",
    re.IGNORECASE,
)
_RE_NUMERICA = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b")
_RE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
# "21:00", "21:00 hrs", "21.30 hrs", "21 hrs", "9:00 PM"
_RE_HORA = re.compile(
    r"\b(2[0-3]|[01]?\d)(?!\d)(?:[:.]([0-5]\d))?\s*(hrs?\.?|horas|h\b|am|pm|a\.m\.|p\.m\.)?",
    re.IGNORECASE,
)


def _fecha_valida(anio, mes, dia):
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def parsear_fecha(texto, anio_por_defecto=None, hoy=None):
    """Devuelve un `date` o None.

    Si el texto no trae año usa `anio_por_defecto`; si tampoco hay, elige el año
    que deja la fecha en el futuro más cercano respecto de `hoy` (los eventos
    publicados siempre son próximos).
    """
    if not texto:
        return None
    hoy = hoy or date.today()

    m = _RE_ISO.search(texto)
    if m:
        return _fecha_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _RE_NUMERICA.search(texto)
    if m:
        return _fecha_valida(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    m = _RE_TEXTO.search(texto)
    if not m:
        return None
    dia, mes = int(m.group(1)), MESES[m.group(2).lower()]
    if m.group(3):
        return _fecha_valida(int(m.group(3)), mes, dia)
    if anio_por_defecto:
        return _fecha_valida(int(anio_por_defecto), mes, dia)
    candidata = _fecha_valida(hoy.year, mes, dia)
    if candidata and candidata < hoy:
        candidata = _fecha_valida(hoy.year + 1, mes, dia)
    return candidata


def anio_en(texto):
    m = re.search(r"\b(20\d{2})\b", texto or "")
    return int(m.group(1)) if m else None


def parsear_hora(texto):
    """Devuelve "HH:MM" o "".

    Solo acepta números que claramente son horas: con minutos ("21:00") o con
    sufijo ("21 hrs", "9 pm"). Así no confunde el día de "19 de octubre" ni
    precios con una hora.
    """
    if not texto:
        return ""
    for m in _RE_HORA.finditer(texto):
        hh, mm, suf = m.group(1), m.group(2), (m.group(3) or "").lower()
        if mm is None and not suf:
            continue
        # Evita leer "19.000" (precio) o "10.10.2026" (fecha) como hora.
        fin = texto[m.end():m.end() + 1]
        if mm is not None and fin.isdigit():
            continue
        if m.start() > 0 and texto[m.start() - 1] in "$.-/":
            continue
        h = int(hh)
        if suf.startswith("p") and h < 12:
            h += 12
        if suf.startswith("a") and h == 12:
            h = 0
        return f"{h:02d}:{int(mm or 0):02d}"
    return ""


def dia_semana(d):
    return DIAS[d.weekday()] if d else ""


def ahora_txt():
    return datetime.now().strftime("%Y-%m-%d %H:%M")
