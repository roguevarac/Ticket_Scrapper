"""Arma las filas finales: una por sector y una por función (fecha + hora).

Ocupación de una función
  - Sectores numerados medidos: vendidos y totales reales del mapa.
  - Sectores numerados agotados (no muestran asientos): se cuentan 100%
    vendidos con la capacidad de referencia (ver capacidades.py).
  - ocupacion_numerada = vendidos / totales de los sectores con capacidad conocida.
  - Sectores sin asiento (cancha / general) no tienen conteo en el sitio: se
    informa su estado (DISPONIBLE / CASI AGOTADO / AGOTADO). Si el recinto tiene
    aforo cargado en data/aforo_recintos.csv, cancha_estimada = aforo - numerados.
  - Función agotada completa: ocupación 100%.
"""
from .fechas import dia_semana
from .util import normalizar

ORDEN_CONFIANZA = ["ALTA", "MEDIA", "BAJA"]


def completar_sectores(funcion, capacidades):
    """Agrega capacidad_usada / vendidos_usados / fuente a cada sector."""
    filas = []
    for s in funcion["sectores"]:
        f = dict(s)
        if s["asientos_totales"]:
            f.update(capacidad_usada=s["asientos_totales"], vendidos_usados=s["asientos_vendidos"],
                     fuente_capacidad="MEDIDO")
        elif s["tipo"] == "NUMERADO":
            cap, fuente = capacidades.buscar(funcion["lugar"], funcion["evento"], funcion["fecha"], s["sector_id"])
            f.update(capacidad_usada=cap, fuente_capacidad=fuente,
                     vendidos_usados=cap if (cap and s["agotado"]) else None)
            if not s["agotado"]:
                f["fuente_capacidad"] = "SIN_LECTURA/" + fuente
        else:
            f.update(capacidad_usada=None, vendidos_usados=None, fuente_capacidad="GENERAL_SIN_CONTEO")
        f["ocupacion_sector"] = (f["vendidos_usados"] / f["capacidad_usada"]
                                 if f["capacidad_usada"] and f["vendidos_usados"] is not None else None)
        f.update(evento=funcion["evento"], fecha=funcion["fecha"], hora=funcion["hora"], lugar=funcion["lugar"],
                 fecha_scraping=funcion["fecha_scraping"], url_compra=funcion["url_compra"])
        filas.append(f)
    return filas


def resumir_funcion(funcion, filas_sector, aforos):
    numerados = [s for s in filas_sector if s["tipo"] == "NUMERADO"]
    generales = [s for s in filas_sector if s["tipo"] == "GENERAL"]
    con_dato = [s for s in numerados if s["capacidad_usada"] and s["vendidos_usados"] is not None]
    total = sum(s["capacidad_usada"] for s in con_dato)
    vendidos = sum(s["vendidos_usados"] for s in con_dato)
    sin_ref = [s for s in numerados if s not in con_dato]

    if filas_sector:
        agotada = all(s["agotado"] for s in filas_sector)
        estado = "AGOTADO" if agotada else "DISPONIBLE"
    elif funcion["agotado_landing"] or funcion["agotado_catalogo"]:
        estado, agotada = "AGOTADO", True
    elif funcion["accesible"]:
        estado, agotada = "SIN SECTORES VISIBLES", False
    else:
        estado, agotada = "SIN INFORMACIÓN", False

    ocup_num = vendidos / total if total else (1.0 if agotada else None)

    aforo = aforos.get(normalizar(funcion["lugar"]))
    cancha_est = aforo - total if (aforo and generales and total and aforo > total) else None
    if agotada:
        ocup_total = 1.0
    elif aforo and cancha_est and all(g["agotado"] for g in generales):
        ocup_total = (vendidos + cancha_est) / aforo
    elif not generales and total:
        ocup_total = vendidos / total
    else:
        ocup_total = None

    fuentes = {s["fuente_capacidad"] for s in numerados}
    if not filas_sector:
        # Agotada según catálogo/landing sin poder ver el mapa: el estado es
        # confiable salvo casos como Anuel, pero no hay conteo de asientos.
        confianza = "MEDIA" if agotada else "BAJA"
    elif sin_ref or any(f.startswith(("REF_RECINTO", "SIN_")) for f in fuentes):
        confianza = "BAJA"
    elif fuentes - {"MEDIDO"}:
        confianza = "MEDIA"
    else:
        confianza = "ALTA"

    def lista(sectores):
        return "; ".join(f"{s['sector']} ({'AGOTADO' if s['agotado'] else s['estado_lista'] or 'DISPONIBLE'})"
                         for s in sectores)

    return {
        "evento": funcion["evento"],
        "fecha": funcion["fecha"],
        "dia": dia_semana(funcion["fecha_obj"]),
        "hora": funcion["hora"] or "NO DETECTADA",
        "lugar": funcion["lugar"],
        "genero": funcion["genero"],
        "estado": estado,
        "agotado": "SI" if agotada else "NO",
        "estado_landing": "AGOTADO" if funcion["agotado_landing"] else "DISPONIBLE",
        "sectores_numerados": len(numerados),
        "sectores_numerados_agotados": sum(1 for s in numerados if s["agotado"]),
        "asientos_numerados_totales": total or None,
        "asientos_vendidos": vendidos if total else None,
        "asientos_disponibles": (total - vendidos) if total else None,
        "ocupacion_numerada": ocup_num,
        "sectores_sin_capacidad": "; ".join(s["sector_id"] for s in sin_ref),
        "sectores_generales": lista(generales),
        "aforo_recinto": aforo,
        "cancha_estimada": cancha_est,
        "ocupacion_total_estimada": ocup_total,
        "confianza": confianza,
        "fecha_texto_original": funcion["fecha_texto"],
        "fecha_scraping": funcion["fecha_scraping"],
        "url_evento": funcion["url_evento"],
        "url_compra": funcion["url_compra"],
        "alertas": " | ".join(funcion["alertas"]),
    }
