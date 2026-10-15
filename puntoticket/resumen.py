"""Arma las filas finales: una por sector y una por función (fecha + hora).

Todo se cuenta en ENTRADAS, no en sectores: un sector de 474 asientos pesa
474 y uno de 90 pesa 90.

Por sector numerado:
  - Medido: capacidad, vendidas y no vendidas salen del mapa de asientos.
  - Agotado (no muestra asientos): vendidas = capacidad de referencia
    (lectura anterior, ver capacidades.py), no vendidas = 0.
  - Recaudación vendida = vendidas x precio; no vendida = no vendidas x precio.
    Es a precio de lista publicado (sin cargo por servicio, sin descuentos,
    preventas ni cortesías).
Por función: suma de los sectores numerados con capacidad conocida.
  % vendido = vendidas / capacidad (ponderado por entradas).
Sectores sin asiento (cancha / general): PuntoTicket no publica cuántas
entradas quedan; se informa su estado. Con el aforo del recinto cargado en
data/aforo_recintos.csv se estima la cancha = aforo - capacidad numerada.
"""
from .fechas import dia_semana
from .util import a_precio, normalizar

# Origen de la capacidad de cada sector, en palabras.
ORIGEN = {
    "MEDIDO": "Medido hoy",
    "HISTORIAL_FUNCION": "Lectura anterior (misma función)",
    "HISTORIAL_EVENTO": "Lectura anterior (otra fecha del evento)",
    "REF_RECINTO": "Estimado (otro evento, mismo recinto)",
    "SIN_REFERENCIA": "Sin dato",
    "GENERAL_SIN_CONTEO": "Sin asiento: el sitio no informa cantidad",
}


def completar_sectores(funcion, capacidades):
    """Agrega capacidad / vendidas / no vendidas / recaudación a cada sector."""
    filas = []
    for s in funcion["sectores"]:
        f = dict(s)
        capacidad = vendidas = None
        if s["asientos_totales"]:
            capacidad, vendidas, fuente = s["asientos_totales"], s["asientos_vendidos"], "MEDIDO"
        elif s["tipo"] == "NUMERADO":
            capacidad, fuente = capacidades.buscar(funcion["lugar"], funcion["evento"], funcion["fecha"],
                                                   s["sector_id"])
            if capacidad and s["agotado"]:
                vendidas = capacidad
            elif not s["agotado"]:
                fuente = "SIN_REFERENCIA"  # disponible pero no se pudieron leer los asientos
                capacidad = None
        else:
            fuente = "GENERAL_SIN_CONTEO"
        precio = a_precio(s.get("precio"))
        no_vendidas = capacidad - vendidas if (capacidad and vendidas is not None) else None
        f.update(
            capacidad=capacidad, vendidas=vendidas, no_vendidas=no_vendidas,
            pct_vendido=vendidas / capacidad if (capacidad and vendidas is not None) else None,
            precio_num=precio,
            recaudacion_vendida=vendidas * precio if (precio and vendidas is not None) else None,
            recaudacion_no_vendida=no_vendidas * precio if (precio and no_vendidas is not None) else None,
            fuente_capacidad=fuente, origen_capacidad=ORIGEN.get(fuente, fuente),
            evento=funcion["evento"], fecha=funcion["fecha"], hora=funcion["hora"], lugar=funcion["lugar"],
            fecha_scraping=funcion["fecha_scraping"],
        )
        filas.append(f)
    return filas


def _suma(filas, clave):
    valores = [f[clave] for f in filas if f[clave] is not None]
    return sum(valores) if valores else None


def resumir_funcion(funcion, filas_sector, aforos):
    numerados = [s for s in filas_sector if s["tipo"] == "NUMERADO"]
    generales = [s for s in filas_sector if s["tipo"] == "GENERAL"]
    con_dato = [s for s in numerados if s["capacidad"] and s["vendidas"] is not None]
    sin_dato = [s for s in numerados if not (s["capacidad"] and s["vendidas"] is not None)]
    capacidad = sum(s["capacidad"] for s in con_dato)
    vendidas = sum(s["vendidas"] for s in con_dato)

    if filas_sector:
        agotada = all(s["agotado"] for s in filas_sector)
        estado = "AGOTADO" if agotada else "DISPONIBLE"
    elif funcion["agotado_landing"] or funcion["agotado_catalogo"] or funcion.get("sin_entradas_pagina"):
        estado, agotada = "AGOTADO", True
    elif funcion["accesible"]:
        estado, agotada = "SIN SECTORES VISIBLES", False
    else:
        estado, agotada = "SIN INFORMACIÓN", False

    pct = vendidas / capacidad if capacidad else (1.0 if agotada else None)

    aforo = aforos.get(normalizar(funcion["lugar"]))
    cancha_est = aforo - capacidad if (aforo and generales and capacidad and aforo > capacidad) else None
    if agotada:
        ocup_total = 1.0
    elif aforo and cancha_est and all(g["agotado"] for g in generales):
        ocup_total = (vendidas + cancha_est) / aforo
    elif not generales and capacidad:
        ocup_total = pct
    else:
        ocup_total = None

    rec_vendida = _suma(con_dato, "recaudacion_vendida")
    rec_no_vendida = _suma(con_dato, "recaudacion_no_vendida")
    sin_precio = [s for s in con_dato if s["precio_num"] is None]

    fuentes = {s["fuente_capacidad"] for s in numerados}
    if not filas_sector:
        calidad = "Sin mapa (agotada)" if agotada else "Sin mapa"
    elif sin_dato or "REF_RECINTO" in fuentes:
        calidad = "Parcial: incluye estimaciones o sectores sin dato"
    elif fuentes - {"MEDIDO"}:
        calidad = "Medido + lecturas anteriores de agotados"
    else:
        calidad = "Todo medido hoy"

    def lista(sectores):
        return "; ".join(f"{s['sector']} ({'AGOTADO' if s['agotado'] else s['estado_lista'] or 'DISPONIBLE'})"
                         for s in sectores)

    return {
        "evento": funcion["evento"],
        "fecha": funcion["fecha"],
        "dia": dia_semana(funcion["fecha_obj"]),
        "hora": funcion["hora"] or "NO DETECTADA",
        "lugar": funcion["lugar"],
        "estado": estado,
        "agotado": "SI" if agotada else "NO",
        "capacidad": capacidad or None,
        "vendidas": vendidas if capacidad else None,
        "no_vendidas": (capacidad - vendidas) if capacidad else None,
        "pct_vendido": pct,
        "recaudacion_vendida": rec_vendida,
        "recaudacion_no_vendida": rec_no_vendida,
        "recaudacion_potencial": (rec_vendida or 0) + (rec_no_vendida or 0) if rec_vendida is not None else None,
        "sectores_numerados": len(numerados),
        "sectores_numerados_agotados": sum(1 for s in numerados if s["agotado"]),
        "sectores_generales": lista(generales),
        "aforo_recinto": aforo,
        "cancha_estimada": cancha_est,
        "ocupacion_total_estimada": ocup_total,
        "calidad": calidad,
        "sectores_sin_dato": "; ".join(f"{s['sector']} ({s['sector_id']})" for s in sin_dato),
        "sectores_sin_precio": "; ".join(s["sector"] for s in sin_precio),
        "estado_landing": "AGOTADO" if funcion["agotado_landing"] else "DISPONIBLE",
        "fecha_scraping": funcion["fecha_scraping"],
        "url_evento": funcion["url_evento"],
        "url_compra": funcion["url_compra"],
    }
