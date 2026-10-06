"""Página de compra de una función: sala de espera, sectores del mapa y asientos.

Estructura confirmada (Aitana, Arcángel, Paulo Londra):
  - Lista de precios: <li class="sector" data-id_sector="4"> con nombre, precio
    y a veces "AGOTADO" / "Casi Agotado"; tiene un .circulo--map con el color.
  - Mapa SVG: elementos .interactive-sector con id tipo "TT4S7R-97". El número
    después de "TT" es el data-id_sector de la lista (más confiable que el
    color: los sectores agotados comparten un gris genérico). La clase
    .no_disponible marca sectores sin venta.
  - Al hacer click en un sector numerado se dibujan los asientos en
    .contenedor_filas_asientos ul li.asiento; .notvacant = vendido,
    .selected = en tu carrito.
"""
import re
import time

from .fechas import parsear_hora
from .util import log

JS_LISTA_SECTORES = r"""
() => {
    const res = {};
    document.querySelectorAll('li.sector, .btn--map').forEach(li => {
        const id = li.getAttribute('data-id_sector') || '';
        const txt = (li.innerText || '').replace(/\s+/g, ' ').trim();
        const mPrecio = txt.match(/\$\s*[\d\.]+/);
        const precio = mPrecio ? mPrecio[0].replace(/\s+/g, '') : '';
        let estado = 'DISPONIBLE';
        if (/casi\s+agotado/i.test(txt)) estado = 'CASI AGOTADO';
        else if (/agotado/i.test(txt) || /agotado|disabled|no_disponible/i.test(li.className)) estado = 'AGOTADO';
        const nombre = txt.replace(precio, '').replace(/\$\s*[\d\.]+/g, '')
            .replace(/casi\s+agotado|agotado/gi, '').replace(/\s+/g, ' ').trim();
        const circulo = li.querySelector('.circulo--map');
        const color = circulo ? (circulo.style.backgroundColor || '') : '';
        const clave = id || ('color:' + color) || ('nombre:' + nombre);
        if (!res[clave] || !res[clave].nombre) res[clave] = { id_sector: id, nombre, precio, estado, color };
    });
    return Object.values(res);
}
"""

JS_SECTORES_SVG = r"""
() => {
    const vistos = new Set();
    const res = [];
    document.querySelectorAll('svg .interactive-sector').forEach((el, i) => {
        const id = el.getAttribute('id') || `SVG_SEC_${i + 1}`;
        if (vistos.has(id)) return;
        vistos.add(id);
        res.push({
            id,
            fill: el.getAttribute('fill') || el.style.fill || '',
            no_disponible: el.classList.contains('no_disponible'),
        });
    });
    return res;
}
"""

JS_LIMPIAR_Y_CLICK = r"""
(id) => {
    const cont = document.querySelector('.contenedor_filas_asientos');
    if (cont) cont.innerHTML = '';
    const el = document.getElementById(id);
    if (!el) return false;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
}
"""

JS_ASIENTOS = r"""
() => {
    const cont = document.querySelector('.contenedor_filas_asientos');
    if (!cont) return null;
    const todos = Array.from(cont.querySelectorAll('ul li.asiento'));
    if (todos.length === 0) return null;
    const ocupados = todos.filter(e => e.classList.contains('notvacant')).length;
    const seleccionados = todos.filter(e => !e.classList.contains('notvacant') && e.classList.contains('selected')).length;
    const primero = todos[0];
    const firma = todos.length + '|' + (primero.id || primero.getAttribute('data-id') || primero.getAttribute('title') || primero.outerHTML.slice(0, 80));
    return { total: todos.length, ocupados, seleccionados, disponibles: todos.length - ocupados - seleccionados, firma };
}
"""

JS_TEXTO = "() => (document.body ? document.body.innerText : '')"

_RE_FECHA_LINEA = re.compile(r"\d{1,2}\s+de\s+[a-záéíóúñ]+|\d{1,2}[-/]\d{1,2}[-/]20\d{2}", re.I)


def esperar_cola(page, max_seg):
    """Las URLs /queue/enqueue/ son una sala de espera. Se espera a que suelte."""
    if "queue" not in page.url.lower():
        return True
    log("      sala de espera (queue), esperando...")
    fin = time.time() + max_seg
    while time.time() < fin:
        page.wait_for_timeout(2000)
        if "queue" not in page.url.lower():
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)
            return True
    return False


def hora_y_fecha_en_pagina(page):
    """Busca en la página de compra una línea con fecha y hora de la función."""
    try:
        texto = page.evaluate(JS_TEXTO) or ""
    except Exception:  # noqa: BLE001
        return "", ""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    for linea in lineas:
        if _RE_FECHA_LINEA.search(linea):
            hora = parsear_hora(linea)
            if hora:
                return hora, linea[:150]
    fecha = next((l[:150] for l in lineas if _RE_FECHA_LINEA.search(l)), "")
    for linea in lineas:
        if re.search(r"\b(hrs?|horas)\b|apertura|inicio|show", linea, re.I):
            hora = parsear_hora(linea)
            if hora:
                return hora, fecha
    return "", fecha


def _leer_asientos(page, intentos=12, espera_ms=350):
    """Espera a que los asientos aparezcan y su cantidad se estabilice (una
    lectura apurada puede contar un sector a medio dibujar)."""
    previo = None
    for _ in range(intentos):
        page.wait_for_timeout(espera_ms)
        try:
            actual = page.evaluate(JS_ASIENTOS)
        except Exception:  # noqa: BLE001
            actual = None
        if actual and previo and actual["firma"] == previo["firma"] and actual["ocupados"] == previo["ocupados"]:
            return actual
        previo = actual
    return previo


def numero_sector(svg_id):
    m = re.match(r"^TT(\d+)", svg_id or "")
    return m.group(1) if m else None


def _norm_color(c):
    c = (c or "").strip().lower()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", c)
    if m:
        return "#%02x%02x%02x" % tuple(int(x) for x in m.groups())
    return c


def leer_mapa(page, leer_asientos=True):
    """Devuelve (sectores, alertas). Cada sector es un dict con el detalle."""
    alertas = []
    lista = page.evaluate(JS_LISTA_SECTORES) or []
    svg = page.evaluate(JS_SECTORES_SVG) or []
    por_id = {s["id_sector"]: s for s in lista if s["id_sector"]}
    por_color = {_norm_color(s["color"]): s for s in lista if s["color"]}

    sectores = []
    usados = set()
    firma_anterior = None
    for sec in svg:
        num = numero_sector(sec["id"])
        info = por_id.get(num) if num else None
        if not info:
            info = por_color.get(_norm_color(sec["fill"]))
        if info:
            usados.add(info["id_sector"] or info["nombre"])
        else:
            alertas.append(f"sector {sec['id']} sin nombre en la lista de precios")
        fila = {
            "sector": (info or {}).get("nombre") or f"Sector {sec['id']}",
            "sector_id": sec["id"],
            "id_lista": (info or {}).get("id_sector", num or ""),
            "precio": (info or {}).get("precio", ""),
            "estado_lista": (info or {}).get("estado", ""),
            "no_disponible_mapa": sec["no_disponible"],
            "tipo": "",
            "asientos_totales": None,
            "asientos_vendidos": None,
            "asientos_disponibles": None,
            "asientos_en_carrito": None,
        }
        if leer_asientos and not sec["no_disponible"]:
            ok = page.evaluate(JS_LIMPIAR_Y_CLICK, sec["id"])
            met = _leer_asientos(page) if ok else None
            if met and met["firma"] == firma_anterior:
                # Misma lectura que el sector anterior: puede ser un dibujo viejo.
                page.wait_for_timeout(1500)
                met = page.evaluate(JS_ASIENTOS)
                if met and met["firma"] == firma_anterior:
                    alertas.append(f"sector {sec['id']}: asientos idénticos al sector anterior, revisar")
            if met:
                firma_anterior = met["firma"]
                fila.update(
                    tipo="NUMERADO",
                    asientos_totales=met["total"],
                    asientos_vendidos=met["ocupados"],
                    asientos_disponibles=met["disponibles"] + met["seleccionados"],
                    asientos_en_carrito=met["seleccionados"],
                )
            else:
                fila["tipo"] = "GENERAL"
        sectores.append(fila)

    # Sectores que están en la lista de precios pero no en el SVG (o páginas sin mapa).
    for s in lista:
        clave = s["id_sector"] or s["nombre"]
        if clave in usados or not s["nombre"]:
            continue
        sectores.append({
            "sector": s["nombre"], "sector_id": f"LISTA-{s['id_sector'] or s['nombre']}",
            "id_lista": s["id_sector"], "precio": s["precio"], "estado_lista": s["estado"],
            "no_disponible_mapa": False, "tipo": "GENERAL",
            "asientos_totales": None, "asientos_vendidos": None,
            "asientos_disponibles": None, "asientos_en_carrito": None,
        })

    for f in sectores:
        f["agotado"] = _sector_agotado(f)
        if not f["tipo"]:
            f["tipo"] = "NUMERADO" if f["sector_id"].startswith("TT") and re.search(r"S\d", f["sector_id"]) else "GENERAL"
    return sectores, alertas


def _sector_agotado(f):
    if f["asientos_totales"]:
        return f["asientos_disponibles"] == 0
    return f["no_disponible_mapa"] or f["estado_lista"] == "AGOTADO"


def leer_funcion(page, url, cfg, debug_nombre=None):
    """Abre la página de compra y devuelve un dict con hora, sectores y alertas."""
    res = {"hora": "", "fecha_texto_compra": "", "sectores": [], "alertas": [], "url_final": url, "accesible": False}
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
    except Exception as e:  # noqa: BLE001
        res["alertas"].append(f"no cargó la página de compra: {e}")
        return res
    if not esperar_cola(page, cfg.espera_cola_seg):
        res["alertas"].append("quedó en la sala de espera (queue); revisar a mano")
        return res
    res["url_final"] = page.url
    try:
        page.wait_for_selector("li.sector, svg .interactive-sector", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    res["hora"], res["fecha_texto_compra"] = hora_y_fecha_en_pagina(page)
    try:
        res["sectores"], alertas = leer_mapa(page, cfg.leer_asientos)
        res["alertas"].extend(alertas)
        res["accesible"] = True
    except Exception as e:  # noqa: BLE001
        res["alertas"].append(f"error leyendo el mapa: {e}")
    if cfg.debug and debug_nombre:
        destino = cfg.salida / "debug"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / f"{debug_nombre}.html").write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(destino / f"{debug_nombre}.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
    return res
