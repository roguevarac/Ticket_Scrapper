"""Página de compra de una función: cola virtual, sectores del mapa y asientos.

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
Cada selector tiene respaldos más genéricos por si el sitio cambia clases, y
se busca también dentro de iframes.
"""
import re
import time

from .fechas import parsear_hora
from .navegador import detectar_barrera, ir, volcar_diagnostico
from .util import log

SEL_LISTA = "li.sector, .btn--map, [data-id_sector]"
SEL_SVG = "svg .interactive-sector"
SEL_SVG_RESPALDO = "svg [id^='TT']"
SEL_ALGUN_SECTOR = f"{SEL_LISTA}, {SEL_SVG}, {SEL_SVG_RESPALDO}"

JS_LISTA_SECTORES = r"""
(sel) => {
    const res = {};
    const elementos = Array.from(document.querySelectorAll(sel))
        // [data-id_sector] puede estar en un hijo del li: nos quedamos con el más externo.
        .filter((el, _i, todos) => !todos.some(o => o !== el && o.contains(el)));
    elementos.forEach(li => {
        const id = li.getAttribute('data-id_sector') ||
                   (li.querySelector('[data-id_sector]') || {getAttribute: () => ''}).getAttribute('data-id_sector') || '';
        const txt = (li.innerText || '').replace(/\s+/g, ' ').trim();
        const mPrecio = txt.match(/\$\s*[\d\.]+/);
        const precio = mPrecio ? mPrecio[0].replace(/\s+/g, '') : '';
        let estado = 'DISPONIBLE';
        if (/casi\s+agotado|[uú]ltimas/i.test(txt)) estado = 'CASI AGOTADO';
        else if (/agotado|sold\s*out/i.test(txt) || /agotado|disabled|no_disponible|soldout/i.test(li.className)) estado = 'AGOTADO';
        const nombre = txt.replace(/\$\s*[\d\.]+/g, '')
            .replace(/casi\s+agotado|agotado|sold\s*out|[uú]ltimas entradas/gi, '').replace(/\s+/g, ' ').trim();
        const circulo = li.querySelector('.circulo--map, [class*="circulo"], [class*="color"]');
        const color = circulo ? (circulo.style.backgroundColor || '') : '';
        const clave = id || ('color:' + color) || ('nombre:' + nombre);
        if (!res[clave] || !res[clave].nombre) res[clave] = { id_sector: id, nombre, precio, estado, color };
    });
    return Object.values(res);
}
"""

JS_SECTORES_SVG = r"""
([sel, respaldo]) => {
    let elementos = Array.from(document.querySelectorAll(sel));
    let fuente = 'interactive-sector';
    if (elementos.length === 0) {
        elementos = Array.from(document.querySelectorAll(respaldo)).filter(e => /^TT\d/.test(e.id));
        fuente = 'id TT*';
    }
    const vistos = new Set();
    const res = [];
    elementos.forEach((el, i) => {
        const id = el.getAttribute('id') || `SVG_SEC_${i + 1}`;
        if (vistos.has(id)) return;
        vistos.add(id);
        res.push({
            id, fuente,
            fill: el.getAttribute('fill') || el.style.fill || '',
            no_disponible: /no_disponible|disabled|agotado|soldout/i.test(el.getAttribute('class') || ''),
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
    const opts = { bubbles: true, cancelable: true, view: window };
    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(t => {
        const Ev = t.startsWith('pointer') && window.PointerEvent ? PointerEvent : MouseEvent;
        el.dispatchEvent(new Ev(t, opts));
    });
    return true;
}
"""

JS_ASIENTOS = r"""
() => {
    const cont = document.querySelector('.contenedor_filas_asientos');
    let todos = cont ? Array.from(cont.querySelectorAll('li.asiento')) : [];
    if (todos.length === 0) todos = Array.from(document.querySelectorAll('li.asiento, [class~="asiento"], [class~="seat"]'));
    if (todos.length === 0) return null;
    const vendido = e => /notvacant|ocupado|vendido|sold|unavailable/.test(e.className.baseVal || e.className);
    const ocupados = todos.filter(vendido).length;
    const seleccionados = todos.filter(e => !vendido(e) && e.classList.contains('selected')).length;
    const primero = todos[0], ultimo = todos[todos.length - 1];
    const ident = e => e.id || e.getAttribute('data-id') || e.getAttribute('title') || e.outerHTML.slice(0, 80);
    return {
        total: todos.length, ocupados, seleccionados,
        disponibles: todos.length - ocupados - seleccionados,
        firma: todos.length + '|' + ident(primero) + '|' + ident(ultimo),
    };
}
"""

JS_TEXTO = "() => (document.body ? document.body.innerText : '')"

_RE_FECHA_LINEA = re.compile(r"\d{1,2}\s+de\s+[a-záéíóúñ]+|\d{1,2}[-/]\d{1,2}[-/]20\d{2}", re.I)
_RE_SIN_ENTRADAS = re.compile(r"agotad[oa]|sold\s*out|no hay entradas|sin entradas disponibles|no quedan entradas", re.I)


def _frame_con_mapa(page):
    """El mapa puede estar en la página o en un iframe: devuelve el que lo tenga."""
    for frame in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
        try:
            if frame.evaluate(f"document.querySelectorAll(`{SEL_ALGUN_SECTOR}`).length") > 0:
                return frame
        except Exception:  # noqa: BLE001
            continue
    return None


def _esperar_mapa(page, timeout_ms):
    fin = time.time() + timeout_ms / 1000
    while time.time() < fin:
        frame = _frame_con_mapa(page)
        if frame:
            return frame
        page.wait_for_timeout(500)
    return None


def hora_y_fecha_en_pagina(frame):
    """Busca en la página de compra una línea con fecha y hora de la función."""
    try:
        texto = frame.evaluate(JS_TEXTO) or ""
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


def _leer_asientos(frame, timeout_ms, espera_ms=350):
    """Espera a que los asientos aparezcan y su cantidad se estabilice (una
    lectura apurada puede contar un sector a medio dibujar)."""
    previo = None
    fin = time.time() + timeout_ms / 1000
    while time.time() < fin:
        frame.wait_for_timeout(espera_ms)
        try:
            actual = frame.evaluate(JS_ASIENTOS)
        except Exception:  # noqa: BLE001
            actual = None
        if actual and previo and actual["firma"] == previo["firma"] and actual["ocupados"] == previo["ocupados"]:
            return actual
        previo = actual
    return previo


def _click_y_leer(frame, sec_id, cfg, firma_anterior):
    """Click en el sector y lectura de asientos, con reintentos.

    1º evento sintético (rápido y no depende de que el sector esté visible);
    si no aparecen asientos, click real del mouse sobre el elemento.
    """
    for intento in range(1 + cfg.reintentos_sector):
        if intento == 0:
            if not frame.evaluate(JS_LIMPIAR_Y_CLICK, sec_id):
                return None
        else:
            try:
                frame.evaluate("() => { const c = document.querySelector('.contenedor_filas_asientos'); if (c) c.innerHTML = ''; }")
                frame.locator(f"[id='{sec_id}']").first.click(force=True, timeout=3000)
            except Exception:  # noqa: BLE001
                frame.evaluate(JS_LIMPIAR_Y_CLICK, sec_id)
        met = _leer_asientos(frame, cfg.timeout_asientos_ms if intento == 0 else cfg.timeout_asientos_ms * 1.5)
        if met and met["firma"] != firma_anterior:
            return met
    return met if met else None


def numero_sector(svg_id):
    m = re.match(r"^TT(\d+)", svg_id or "")
    return m.group(1) if m else None


def _norm_color(c):
    c = (c or "").strip().lower()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", c)
    if m:
        return "#%02x%02x%02x" % tuple(int(x) for x in m.groups())
    return c


def _fila(nombre, sector_id, id_lista, precio, estado, no_disp, tipo=""):
    return {
        "sector": nombre, "sector_id": sector_id, "id_lista": id_lista, "precio": precio,
        "estado_lista": estado, "no_disponible_mapa": no_disp, "tipo": tipo,
        "asientos_totales": None, "asientos_vendidos": None,
        "asientos_disponibles": None, "asientos_en_carrito": None,
    }


def leer_mapa(frame, cfg):
    """Devuelve (sectores, alertas). Cada sector es un dict con el detalle."""
    alertas = []
    lista = frame.evaluate(JS_LISTA_SECTORES, SEL_LISTA) or []
    svg = frame.evaluate(JS_SECTORES_SVG, [SEL_SVG, SEL_SVG_RESPALDO]) or []
    if svg and svg[0]["fuente"] != "interactive-sector":
        alertas.append("mapa leído con selector de respaldo (id TT*): revisar si cambió el HTML")
    por_id = {s["id_sector"]: s for s in lista if s["id_sector"]}
    por_color = {_norm_color(s["color"]): s for s in lista if s["color"]}

    sectores, usados, firma_anterior = [], set(), None
    for sec in svg:
        num = numero_sector(sec["id"])
        info = por_id.get(num) if num else None
        if not info:
            info = por_color.get(_norm_color(sec["fill"]))
        if info:
            usados.add(info["id_sector"] or info["nombre"])
        else:
            alertas.append(f"sector {sec['id']} sin nombre en la lista de precios")
        info = info or {}
        fila = _fila(info.get("nombre") or f"Sector {sec['id']}", sec["id"], info.get("id_sector", num or ""),
                     info.get("precio", ""), info.get("estado", ""), sec["no_disponible"])
        if cfg.leer_asientos and not sec["no_disponible"]:
            met = _click_y_leer(frame, sec["id"], cfg, firma_anterior)
            if met and met["firma"] == firma_anterior:
                alertas.append(f"sector {sec['id']}: asientos idénticos al sector anterior, revisar")
            if met:
                firma_anterior = met["firma"]
                fila.update(tipo="NUMERADO", asientos_totales=met["total"], asientos_vendidos=met["ocupados"],
                            asientos_disponibles=met["disponibles"] + met["seleccionados"],
                            asientos_en_carrito=met["seleccionados"])
            else:
                fila["tipo"] = "GENERAL"
        sectores.append(fila)

    # Sectores que están en la lista de precios pero no en el SVG (o páginas sin mapa).
    for s in lista:
        clave = s["id_sector"] or s["nombre"]
        if clave in usados or not s["nombre"]:
            continue
        sectores.append(_fila(s["nombre"], f"LISTA-{s['id_sector'] or s['nombre']}", s["id_sector"],
                              s["precio"], s["estado"], False, "GENERAL"))

    for f in sectores:
        f["agotado"] = _sector_agotado(f)
        if not f["tipo"]:
            f["tipo"] = "NUMERADO" if re.match(r"^TT\d+S\d", f["sector_id"]) else "GENERAL"
    return sectores, alertas


def _sector_agotado(f):
    if f["asientos_totales"]:
        return f["asientos_disponibles"] == 0
    return f["no_disponible_mapa"] or f["estado_lista"] == "AGOTADO"


def resumen_sectores(sectores):
    numerados = [s for s in sectores if s["tipo"] == "NUMERADO"]
    leidos = [s for s in numerados if s["asientos_totales"]]
    return (f"{len(sectores)} sectores ({len(leidos)}/{len(numerados)} numerados con asientos leídos, "
            f"{len(sectores) - len(numerados)} generales, {sum(1 for s in sectores if s['agotado'])} agotados) | "
            f"asientos leídos: {sum(s['asientos_totales'] for s in leidos)}, "
            f"vendidos: {sum(s['asientos_vendidos'] for s in leidos)}")


def leer_funcion(page, url, cfg, nombre="compra", red=None):
    """Abre la página de compra y devuelve un dict con hora, sectores y alertas."""
    res = {"hora": "", "fecha_texto_compra": "", "sectores": [], "alertas": [], "url_final": url,
           "accesible": False, "sin_entradas_pagina": False}
    inicio_red = len(red) if red is not None else 0
    ok, motivo = ir(page, url, cfg, nombre=nombre)
    if not ok:
        res["alertas"].append(f"página de compra: {motivo}")
        volcar_diagnostico(page, cfg, nombre, red, inicio_red)
        return res
    res["url_final"] = page.url

    frame = _esperar_mapa(page, cfg.timeout_elementos_ms)
    if frame is None:
        # Un reintento: recargar por si el mapa quedó a medio cargar.
        log("      no aparecieron sectores, recargando una vez...")
        ok, motivo = ir(page, page.url, cfg, nombre=nombre)
        frame = _esperar_mapa(page, cfg.timeout_elementos_ms) if ok else None
    if frame is None:
        texto = ""
        try:
            texto = page.evaluate(JS_TEXTO) or ""
        except Exception:  # noqa: BLE001
            pass
        res["accesible"] = not detectar_barrera(page)
        res["sin_entradas_pagina"] = bool(_RE_SIN_ENTRADAS.search(texto))
        res["hora"], res["fecha_texto_compra"] = hora_y_fecha_en_pagina(page.main_frame)
        res["alertas"].append("la página de compra no mostró sectores"
                              + (" (dice agotado / sin entradas)" if res["sin_entradas_pagina"] else ""))
        volcar_diagnostico(page, cfg, nombre, red, inicio_red)
        return res

    res["hora"], res["fecha_texto_compra"] = hora_y_fecha_en_pagina(frame)
    try:
        res["sectores"], alertas = leer_mapa(frame, cfg)
        res["alertas"].extend(alertas)
        res["accesible"] = True
    except Exception as e:  # noqa: BLE001
        res["alertas"].append(f"error leyendo el mapa: {e}")
        volcar_diagnostico(page, cfg, nombre, red, inicio_red)
        return res
    log(f"      {resumen_sectores(res['sectores'])}")
    if cfg.debug:
        volcar_diagnostico(page, cfg, nombre, red, inicio_red)
    return res
