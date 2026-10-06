"""Escritura del reporte en Excel (y CSV de respaldo)."""
import csv

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

COLUMNAS_FUNCIONES = [
    ("evento", "Evento", 38), ("fecha", "Fecha", 11), ("dia", "Día", 10), ("hora", "Hora", 9),
    ("lugar", "Lugar", 32), ("estado", "Estado", 13), ("agotado", "Agotado", 9),
    ("ocupacion_numerada", "% ocupación numerada", 12), ("ocupacion_total_estimada", "% ocupación total (estim.)", 13),
    ("asientos_numerados_totales", "Asientos numerados", 11), ("asientos_vendidos", "Vendidos", 10),
    ("asientos_disponibles", "Disponibles", 11), ("sectores_numerados", "Sectores numerados", 10),
    ("sectores_numerados_agotados", "Sectores agotados", 10), ("sectores_generales", "Sectores sin asiento (cancha/general)", 40),
    ("aforo_recinto", "Aforo recinto", 10), ("cancha_estimada", "Cancha estimada", 10),
    ("confianza", "Confianza", 10), ("estado_landing", "Estado en landing", 12),
    ("sectores_sin_capacidad", "Sectores sin capacidad conocida", 30), ("genero", "Género", 12),
    ("fecha_texto_original", "Fecha (texto sitio)", 22), ("fecha_scraping", "Fecha scraping", 16),
    ("url_evento", "URL evento", 40), ("url_compra", "URL compra", 40), ("alertas", "Alertas", 60),
]

COLUMNAS_SECTORES = [
    ("evento", "Evento", 34), ("fecha", "Fecha", 11), ("hora", "Hora", 8), ("lugar", "Lugar", 30),
    ("sector", "Sector", 26), ("sector_id", "Sector ID", 14), ("tipo", "Tipo", 10), ("precio", "Precio", 10),
    ("agotado", "Agotado", 9), ("estado_lista", "Estado lista precios", 14),
    ("asientos_totales", "Asientos (medido)", 10), ("asientos_vendidos", "Vendidos (medido)", 10),
    ("asientos_disponibles", "Disponibles (medido)", 10), ("capacidad_usada", "Capacidad usada", 10),
    ("vendidos_usados", "Vendidos usados", 10), ("ocupacion_sector", "% ocupación", 10),
    ("fuente_capacidad", "Fuente capacidad", 22), ("fecha_scraping", "Fecha scraping", 16),
    ("url_compra", "URL compra", 40),
]

NOTAS = [
    "Cómo leer este reporte",
    "",
    "Hoja Funciones: una fila por función (cada fecha/hora de un evento es un evento distinto).",
    "Estado: AGOTADO si todos los sectores están agotados (o la landing/catálogo lo dice y no hay link de compra).",
    "% ocupación numerada: vendidos / capacidad de los sectores con asientos numerados.",
    "  Los sectores numerados agotados no muestran asientos: se cuentan 100% vendidos con la capacidad",
    "  de referencia (columna 'Fuente capacidad' en la hoja Sectores):",
    "    MEDIDO            leído del mapa en esta corrida",
    "    HISTORIAL_FUNCION misma función, lectura anterior (data/historial_sectores.csv)",
    "    HISTORIAL_EVENTO  mismo evento, otra fecha",
    "    REF_RECINTO       mismo recinto en otros eventos (aproximado: el montaje puede cambiar)",
    "    SIN_REFERENCIA    no hay dato: el sector queda fuera del cálculo",
    "Sectores sin asiento (cancha/general): PuntoTicket no publica cuántas entradas quedan; solo su estado.",
    "  Si cargás el aforo del recinto en data/aforo_recintos.csv: cancha estimada = aforo - asientos numerados,",
    "  y % ocupación total (estim.) se calcula cuando la cancha está agotada.",
    "Confianza: ALTA = todo medido; MEDIA = se usó historial del mismo evento; BAJA = referencia de otro evento,",
    "  sectores sin dato o sin mapa.",
    "Estado en landing: lo que dice la página del evento. Puede decir AGOTADO y en la compra haber entradas",
    "  (caso Anuel): manda lo que se ve en la página de compra.",
]


def _hoja(ws, filas, columnas):
    ws.append([c[1] for c in columnas])
    for fila in filas:
        ws.append([fila.get(c[0]) for c in columnas])
    negrita, fondo = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496")
    for i, (clave, _t, ancho) in enumerate(columnas, start=1):
        celda = ws.cell(row=1, column=i)
        celda.font, celda.fill = negrita, fondo
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = ancho
        if clave.startswith("ocupacion"):
            for r in range(2, ws.max_row + 1):
                ws.cell(row=r, column=i).number_format = "0.0%"
    ws.row_dimensions[1].height = 42
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions


def escribir_excel(ruta, funciones, sectores, alertas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Funciones"
    _hoja(ws, funciones, COLUMNAS_FUNCIONES)
    rojo = PatternFill("solid", fgColor="F8CBAD")
    col_agotado = [c[0] for c in COLUMNAS_FUNCIONES].index("agotado") + 1
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=col_agotado).value == "SI":
            ws.cell(row=r, column=col_agotado).fill = rojo

    _hoja(wb.create_sheet("Sectores"), sectores, COLUMNAS_SECTORES)
    _hoja(wb.create_sheet("Alertas"), [{"evento": a[0], "detalle": a[1]} for a in alertas],
          [("evento", "Evento / función", 50), ("detalle", "Detalle", 100)])
    notas = wb.create_sheet("Notas")
    for linea in NOTAS:
        notas.append([linea])
    notas["A1"].font = Font(bold=True, size=13)
    notas.column_dimensions["A"].width = 120
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)


def escribir_csv(ruta, filas, columnas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[c[0] for c in columnas], extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
