"""Orquestación: catálogo -> landing de cada evento -> compra de cada función -> reporte."""
from datetime import datetime

from .capacidades import Capacidades, cargar_aforos, guardar_en_historial
from .catalogo import leer_catalogo
from .compra import leer_funcion
from .excel import COLUMNAS_FUNCIONES, COLUMNAS_SECTORES, escribir_csv, escribir_excel
from .fechas import ahora_txt, anio_en, parsear_fecha, parsear_hora
from .landing import leer_landing
from .resumen import completar_sectores, resumir_funcion
from .util import log, normalizar


def _slug(texto):
    return "".join(c if c.isalnum() else "_" for c in normalizar(texto))[:50]


def _nueva_funcion(ev, fecha_texto, hora, url_compra):
    fecha_obj = parsear_fecha(fecha_texto, anio_en(ev.get("fecha_catalogo")))
    return {
        "evento": ev["titulo"], "lugar": ev.get("lugar", ""), "genero": ev.get("genero", ""),
        "url_evento": ev["url"], "url_compra": url_compra or "",
        "fecha_texto": fecha_texto or "", "fecha_obj": fecha_obj,
        "fecha": fecha_obj.isoformat() if fecha_obj else (fecha_texto or "FECHA NO DETECTADA"),
        "hora": hora or "", "agotado_landing": False, "agotado_catalogo": bool(ev.get("agotado_catalogo")),
        "accesible": False, "sectores": [], "alertas": [], "fecha_scraping": ahora_txt(),
    }


def _fusionar(destino, origen):
    """Une dos lecturas de la misma función (ej. dos botones para la misma fecha)."""
    por_id = {s["sector_id"]: s for s in destino["sectores"]}
    for s in origen["sectores"]:
        actual = por_id.get(s["sector_id"])
        if actual is None or (not actual["asientos_totales"] and s["asientos_totales"]):
            por_id[s["sector_id"]] = s
    destino["sectores"] = list(por_id.values())
    destino["agotado_landing"] = destino["agotado_landing"] and origen["agotado_landing"]
    destino["accesible"] = destino["accesible"] or origen["accesible"]
    destino["alertas"] += [a for a in origen["alertas"] if a not in destino["alertas"]]
    if origen["url_compra"] and origen["url_compra"] not in destino["url_compra"]:
        destino["url_compra"] = (destino["url_compra"] + " " + origen["url_compra"]).strip()


def procesar_evento(page, ev, cfg):
    botones, address = leer_landing(page, ev["url"])
    if address and address.get("lugar") and not ev.get("lugar"):
        ev["lugar"] = address["lugar"]

    vistos, utiles = set(), []
    for b in botones:
        url = b["url_compra"].split("#")[0]
        if url.rstrip("/") == ev["url"].rstrip("/"):
            url = ""
        clave = (url, b["fecha_texto"])
        if clave in vistos:
            continue
        vistos.add(clave)
        utiles.append(dict(b, url_compra=url))

    if not utiles:
        fecha_texto = ev.get("fecha_catalogo") or (address or {}).get("fecha", "")
        f = _nueva_funcion(ev, fecha_texto, parsear_hora((address or {}).get("texto", "")), "")
        f["alertas"].append("sin botón de compra en la landing")
        if " - " in (ev.get("fecha_catalogo") or ""):
            f["alertas"].append(f"el catálogo muestra un rango de fechas: {ev['fecha_catalogo']}")
        return [f]

    funciones = {}
    for i, b in enumerate(utiles, start=1):
        fecha_texto = b["fecha_texto"] or ev.get("fecha_catalogo", "")
        f = _nueva_funcion(ev, fecha_texto, parsear_hora(b["texto_bloque"]), b["url_compra"])
        f["agotado_landing"] = b["agotado_landing"]
        if not b["url_compra"]:
            if not b["agotado_landing"]:
                f["alertas"].append("botón sin link de compra y sin marca de agotado")
        else:
            log(f"   función {i}/{len(utiles)}: {f['fecha']} {f['hora']} -> {b['url_compra'][:90]}")
            lectura = leer_funcion(page, b["url_compra"], cfg, debug_nombre=f"{_slug(ev['titulo'])}_{i}")
            f["hora"] = lectura["hora"] or f["hora"]
            f["sectores"] = lectura["sectores"]
            f["accesible"] = lectura["accesible"]
            f["alertas"] += lectura["alertas"]
            if not b["fecha_texto"] and lectura["fecha_texto_compra"]:
                otra = parsear_fecha(lectura["fecha_texto_compra"], anio_en(ev.get("fecha_catalogo")))
                if otra:
                    f["fecha_obj"], f["fecha"], f["fecha_texto"] = otra, otra.isoformat(), lectura["fecha_texto_compra"]
        if not f["fecha_obj"]:
            f["alertas"].append(f"fecha no interpretada: '{fecha_texto}'")
        clave = (f["fecha"], f["hora"])
        if clave in funciones:
            _fusionar(funciones[clave], f)
        else:
            funciones[clave] = f
    return list(funciones.values())


def armar_reporte(funciones_crudas, cfg):
    capacidades = Capacidades.desde_historial(cfg.historial)
    for f in funciones_crudas:
        for s in f["sectores"]:
            if s["asientos_totales"]:
                capacidades.agregar(f["lugar"], f["evento"], f["fecha"], s["sector_id"], s["asientos_totales"])
    aforos = cargar_aforos(cfg.aforos)
    filas_funcion, filas_sector, alertas = [], [], []
    for f in funciones_crudas:
        sectores = completar_sectores(f, capacidades)
        filas_sector += sectores
        filas_funcion.append(resumir_funcion(f, sectores, aforos))
        for a in f["alertas"]:
            alertas.append((f"{f['evento']} {f['fecha']} {f['hora']}", a))
    filas_funcion.sort(key=lambda r: (r["fecha"], r["hora"], r["evento"]))
    return filas_funcion, filas_sector, alertas


def guardar(funciones_crudas, cfg, sello, final=False):
    funciones, sectores, alertas = armar_reporte(funciones_crudas, cfg)
    base = cfg.salida / f"puntoticket_musica_{sello}"
    escribir_excel(base.with_suffix(".xlsx"), funciones, sectores, alertas)
    escribir_csv(base.parent / f"{base.name}_funciones.csv", funciones, COLUMNAS_FUNCIONES)
    escribir_csv(base.parent / f"{base.name}_sectores.csv", sectores, COLUMNAS_SECTORES)
    if final:
        guardar_en_historial(cfg.historial, sectores)
    return base.with_suffix(".xlsx"), funciones


def correr(page, cfg):
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    eventos = leer_catalogo(page, cfg.catalogo_url)
    if cfg.filtro_titulos:
        filtros = [normalizar(t) for t in cfg.filtro_titulos]
        eventos = [e for e in eventos if any(t in normalizar(e["titulo"]) for t in filtros)]
    if cfg.limite:
        eventos = eventos[:cfg.limite]

    funciones = []
    for i, ev in enumerate(eventos, start=1):
        log(f"[{i}/{len(eventos)}] {ev['titulo']} ({ev.get('fecha_catalogo', '')})")
        try:
            nuevas = procesar_evento(page, ev, cfg)
        except Exception as e:  # noqa: BLE001
            log(f"   error: {e}")
            nuevas = [_nueva_funcion(ev, ev.get("fecha_catalogo", ""), "", "")]
            nuevas[0]["alertas"].append(f"error procesando el evento: {e}")
        funciones += nuevas
        log(f"   {len(nuevas)} función(es)")
        guardar(funciones, cfg, sello)
        page.wait_for_timeout(cfg.pausa_entre_eventos_ms)

    ruta, filas = guardar(funciones, cfg, sello, final=True)
    agotadas = sum(1 for r in filas if r["agotado"] == "SI")
    log(f"Listo: {len(eventos)} eventos, {len(filas)} funciones ({agotadas} agotadas).")
    log(f"Reporte: {ruta}")
    return ruta
