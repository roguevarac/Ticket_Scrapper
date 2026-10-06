import csv
import re
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9222"
CATALOGO_URL = "https://www.puntoticket.com/musica"
CSV_PATH = "reporte_todos_eventos_musica_v3.csv"

# Si tiene texto, imprime el detalle crudo (evento del catálogo + fechas
# detectadas en la landing) para cualquier evento cuyo título lo contenga,
# en el momento exacto en que el script lo procesa. Poner en None para
# desactivar.
DEBUG_TITULO = "aespa"

COLUMNAS = [
    "nombre_evento",
    "tipo_evento",
    "fecha_evento",
    "lugar_evento",
    "sector",
    "sector_id",
    "precio_sector",
    "agotado",
    "asientos_disponibles",
    "asientos_ocupados",
    "asientos_totales",
    "porcentaje_ocupacion",
    "fecha_scraping",
    "url_evento"
]


def log(msg):
    print(f"[CRAWLER] {msg}")


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def normalizar_hex(hex_str):
    if not hex_str:
        return ""
    hex_str = hex_str.strip().lower()
    if hex_str.startswith("#"):
        return hex_str
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*\)", hex_str)
    if m:
        r, g, b = map(int, m.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return hex_str


# ---------------------------------------------------------------------------
# CATÁLOGO
# ---------------------------------------------------------------------------
# Confirmado con el HTML real de la tarjeta de Aitana:
#   <a href="/aitana">
#     <p class="descripcion text-truncate"><strong>Movistar Arena - Santiago Centro</strong> / Rock</p>
#     <h3 title="Aitana ">Aitana</h3>
#     <p class="fecha">19 de octubre 2026</p>
#   </a>
# El bug anterior usaba a.innerText.split('\n')[0], que agarraba la primera
# línea del <a> (el lugar/género), no el título. Además, iterar TODOS los
# a[href] del documento hacía que un link duplicado (ej. versión mobile del
# mismo href) "ganara" la deduplicación con texto tipo "VER MÁS".
# Ahora se escanea directamente cada article.event-item (48 tarjetas reales
# confirmadas) y se toma el h3[title] de adentro, sin ambigüedad.
def obtener_todos_los_eventos_catalogo(page):
    log(f"Cargando catálogo en {CATALOGO_URL}...")
    page.goto(CATALOGO_URL, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    log("Haciendo scroll dinámico en la grilla...")
    for _ in range(8):
        page.evaluate("window.scrollBy(0, 800);")
        page.wait_for_timeout(600)

    js_extraer_catalogo = r"""
    () => {
        const eventos = [];
        const articulos = document.querySelectorAll('article.event-item');

        articulos.forEach(art => {
            const a = art.querySelector('a[href]');
            if (!a) return;

            const href = a.href;

            const h3 = a.querySelector('h3[title]') || a.querySelector('h3');
            const titulo = h3 ? (h3.getAttribute('title') || h3.innerText).trim() : '';
            if (!titulo) return;

            // NO CONFIRMADO con HTML real: en MANA y Babasónicos la fecha salió
            // bien pero el lugar quedó vacío, lo que sugiere que esas tarjetas
            // podrían no tener el <strong> dentro de p.descripcion. Se agrega un
            // fallback al texto completo del párrafo (separado por " / ") sin
            // asumir que resuelve el caso real hasta confirmarlo con el HTML.
            const pDescStrong = a.querySelector('p.descripcion strong');
            const pDescCompleto = a.querySelector('p.descripcion');
            let lugar = pDescStrong ? pDescStrong.innerText.trim() : '';
            if (!lugar && pDescCompleto) {
                lugar = pDescCompleto.innerText.split('/')[0].trim();
            }

            const pFecha = a.querySelector('p.fecha');
            const fechaCatalogo = pFecha ? pFecha.innerText.replace(/\s+/g, ' ').trim() : '';

            const agotadoEvento = /agotado/i.test(art.innerText) ||
                                   !!art.querySelector('img[alt*="agotado" i], [class*="agotado" i], [class*="sold" i]');

            const nuevo = { titulo, url: href, lugar_catalogo: lugar, fecha_catalogo: fechaCatalogo, agotado_evento: agotadoEvento };
            const existenteIdx = eventos.findIndex(e => e.url === href);

            if (existenteIdx === -1) {
                eventos.push(nuevo);
            } else if (!eventos[existenteIdx].fecha_catalogo && fechaCatalogo) {
                // Si la primera copia de esta URL quedó incompleta (posible timing
                // de render), y esta segunda copia sí trae fecha, se reemplaza.
                eventos[existenteIdx] = nuevo;
            }
        });

        return eventos;
    }
    """
    eventos = page.evaluate(js_extraer_catalogo) or []

    # Defensa reforzada: si algún evento quedó sin fecha_catalogo (posible
    # timing de render de la grilla), se reintenta varias veces con espera
    # entre cada una, hasta que no falte ninguna o se agoten los intentos.
    for intento in range(4):
        incompletos = [e for e in eventos if not e.get("fecha_catalogo")]
        if not incompletos:
            break
        log(f"   -> {len(incompletos)} evento(s) sin fecha (intento {intento + 1}/4), reintentando...")
        page.wait_for_timeout(1500)
        eventos_reintento = page.evaluate(js_extraer_catalogo) or []
        por_url = {e["url"]: e for e in eventos_reintento}
        for i, ev in enumerate(eventos):
            if not ev.get("fecha_catalogo") and ev["url"] in por_url and por_url[ev["url"]].get("fecha_catalogo"):
                eventos[i] = por_url[ev["url"]]

    faltantes_final = [e["titulo"] for e in eventos if not e.get("fecha_catalogo")]
    if faltantes_final:
        log(f"   -> Persisten sin fecha tras todos los reintentos: {faltantes_final}")

    return eventos


# ---------------------------------------------------------------------------
# FECHAS Y LINKS DE COMPRA (dos templates confirmados + fallback)
# ---------------------------------------------------------------------------
# ALGORITMO UNIFICADO (reemplaza la lógica por template separado):
# Confirmado con múltiples eventos reales que la fecha de un .button-block
# no siempre está adentro de su mismo contenedor — a veces es un <h5> o una
# <img alt="..."> que aparece ANTES en el documento, en un div hermano
# distinto (ej. Karol G: la imagen de fecha y sus 2 botones son hermanos
# sueltos dentro de un .row común, no un wrapper por fecha).
#
# Se recorre el documento en orden real y se van tratando como "marcadores
# de fecha" los <h5> y <img alt="..."> cuyo texto matchea el patrón de
# fecha. Cada .button-block toma la fecha del marcador más reciente visto
# antes que él (o su propio h4, si ESE h4 matchea el patrón de fecha).
#
# Estado (agotado): confirmado que hay dos casos reales distintos —
#   - Si el bloque tiene su propio <small>AGOTADO</small>/<small>DISPONIBLE</small>
#     explícito (ej. Karol G), esa señal manda siempre, ignorando el banner
#     de la imagen (evita marcar agotada una categoría que en realidad sí
#     vende, solo porque el banner de esa fecha dice "sold out").
#   - Si el bloque NO tiene esa señal propia (ej. Arcángel: el botón dice
#     "DISPONIBLE" siempre, sin importar la realidad), se usa el estado del
#     banner de la imagen más cercana (ej. "sold out" en el alt) — decisión
#     de negocio confirmada.
def extraer_fechas_y_links_js(page):
    js_script = r"""
    () => {
        const origin = window.location.origin;
        const patronFecha = /\d{1,2}\s+de\s+[a-záéíóúñ]+/i;

        const bloques = Array.from(document.querySelectorAll('.button-block'));

        // Template E (confirmado con Jamiroquai): el link tiene clase "boton"
        // (sin "-block"), y el <small> de estado es HERMANO del <a>, no
        // descendiente — por eso se normaliza al div contenedor (que sí
        // envuelve tanto el <a> como el <p><small>), para reusar la misma
        // lógica de abajo sin duplicar código.
        document.querySelectorAll('a.boton').forEach(a => {
            const wrapper = a.closest('div') || a.parentElement;
            if (wrapper && !bloques.includes(wrapper)) bloques.push(wrapper);
        });
        if (bloques.length === 0) return null;

        const marcadores = Array.from(document.querySelectorAll('h5, img[alt]'))
            .map(el => {
                const texto = el.tagName === 'IMG' ? (el.getAttribute('alt') || '') : el.innerText;

                // Un banner con varias fechas juntas (ej. "8, 9, 10, 14, 15 y 16 de
                // septiembre") no es un marcador de UNA fecha puntual — se ignora,
                // porque si no todos los bloques posteriores heredarían la misma
                // fecha equivocada (confirmado con Morat).
                if (/\d+\s*,\s*\d+/.test(texto)) return null;

                const m = texto.match(patronFecha);
                if (!m) return null;
                return {
                    tipo: 'fecha',
                    nodo: el,
                    fecha: m[0],
                    agotadoBanner: /sold\s*out|agotad[oa]/i.test(texto)
                };
            })
            .filter(Boolean);

        const eventos = [
            ...marcadores,
            ...bloques.map(b => ({ tipo: 'bloque', nodo: b }))
        ];

        eventos.sort((a, b) => {
            const pos = a.nodo.compareDocumentPosition(b.nodo);
            if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
            if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
            return 0;
        });

        const resultados = [];
        let fechaActual = '';
        let agotadoBannerActual = false;

        eventos.forEach(item => {
            if (item.tipo === 'fecha') {
                fechaActual = item.fecha;
                agotadoBannerActual = item.agotadoBanner;
                return;
            }

            const bloque = item.nodo;
            const a = bloque.querySelector('a[href]');
            if (!a) return;

            const href = a.getAttribute('href') || a.href || '';

            const h4 = bloque.querySelector('h3, h4');
            const h4Texto = h4 ? h4.innerText.replace(/\s+/g, ' ').trim() : '';
            const fecha = patronFecha.test(h4Texto) ? h4Texto : fechaActual;

            const smallEl = bloque.querySelector('small');
            const smallTxt = smallEl ? smallEl.innerText.toUpperCase() : '';
            const tieneSmallStatus = smallTxt.includes('AGOTADO') || smallTxt.includes('DISPONIBLE');

            let agotado;
            if (tieneSmallStatus) {
                agotado = smallTxt.includes('AGOTADO');
            } else {
                const textoAgotado = a.classList.contains('inactive') ||
                                      bloque.innerText.toUpperCase().includes('AGOTADO');
                agotado = textoAgotado || agotadoBannerActual;
            }

            resultados.push({
                fecha_exacta: fecha,
                estado: agotado ? 'AGOTADO' : 'DISPONIBLE',
                url_compra: href.startsWith('http') ? href : origin + href
            });
        });

        return resultados;
    }
    """
    try:
        return page.evaluate(js_script)
    except Exception:
        return []


# TEMPLATE D (confirmado con Jeff Mills): landings sin ningún .button-block,
# con la fecha/hora/lugar en <address><time datetime="DD-MM-YYYY">. Todavía
# NO se confirmó cómo es el botón de compra en este template, así que solo
# sirve para mejorar la fecha/lugar de la fila de fallback, no para separar
# sectores.
def extraer_fallback_address_js(page):
    js = r"""
    () => {
        const addr = document.querySelector('address');
        if (!addr) return null;
        const times = Array.from(addr.querySelectorAll('time'));
        const fecha = times[0]?.getAttribute('datetime') || '';
        const lugar = addr.childNodes[0]?.textContent?.trim() || '';
        return fecha ? { fecha, lugar } : null;
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return None


def construir_mapa_colores_dinamico(page) -> dict:
    js = r"""
    () => {
        const resultado = {};
        const elementos = document.querySelectorAll('li.sector, .btn--map');
        elementos.forEach(el => {
            const circulo = el.querySelector('.circulo--map');
            if (!circulo) return;
            const color = circulo.style.backgroundColor || "";
            const id_sector = el.getAttribute('data-id_sector') || "";
            const txt = (el.innerText || '').replace(/\n/g, ' ').trim();
            const matchPrecio = txt.match(/\$\s*([\d\.]+)/);
            const precio = matchPrecio ? matchPrecio[0] : "";
            let nombre = txt.replace(precio, '').replace(/AGOTADO|Casi Agotado/gi, '').trim();
            if (color) resultado[color] = { nombre: nombre, precio: precio, id_sector: id_sector };
        });
        return resultado;
    }
    """
    try:
        raw_map = page.evaluate(js) or {}
        return {normalizar_hex(k): v for k, v in raw_map.items()}
    except Exception:
        return {}


# Confirmado con el mapa real de Aitana/Arcángel: el número que sigue a "TT"
# en el id de cada <path> (ej. "TT4S7R-97" -> "4") coincide con el
# data-id_sector del <li> de la lista de precios (ej. data-id_sector="4").
# Esto es MÁS CONFIABLE que el color como puente, porque el color se rompe
# justo en los sectores agotados: el sitio les pone un gris genérico
# (#B9B7BD) que pisa a otros sectores agotados con el mismo placeholder
# (ej. PRIMERAS FILAS, TRIBUNA y PLATEA ALTA SILVER comparten ese gris y se
# sobreescriben entre sí en el mapa de colores).
def construir_mapa_por_id_sector(page) -> dict:
    js = r"""
    () => {
        const resultado = {};
        document.querySelectorAll('li.sector').forEach(li => {
            const idSector = li.getAttribute('data-id_sector') || '';
            if (!idSector) return;
            const txt = (li.innerText || '').replace(/\n/g, ' ').trim();
            const matchPrecio = txt.match(/\$\s*([\d\.]+)/);
            const precio = matchPrecio ? matchPrecio[0] : '';
            const nombre = txt.replace(precio, '').replace(/AGOTADO|Casi Agotado/gi, '').trim();
            resultado[idSector] = { nombre, precio };
        });
        return resultado;
    }
    """
    try:
        return page.evaluate(js) or {}
    except Exception:
        return {}


def extraer_metricas_asientos(page) -> dict | None:
    js = r"""
    () => {
        const contenedor = document.querySelector('.contenedor_filas_asientos');
        if (!contenedor) return null;
        const todos = Array.from(contenedor.querySelectorAll('ul li.asiento'));
        if (todos.length === 0) return null;

        const disponibles = todos.filter(el => !el.classList.contains('notvacant') && !el.classList.contains('selected')).length;
        const ocupados = todos.filter(el => el.classList.contains('notvacant')).length;
        const seleccionados = todos.filter(el => el.classList.contains('selected')).length;
        const total = disponibles + ocupados + seleccionados;

        return total === 0 ? null : { disponibles, ocupados, seleccionados, total };
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return None


def procesar_sector_mapa(page, evento_info, url_origen, fecha_puntual, agotado_default="NO"):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

    mapa_colores = construir_mapa_colores_dinamico(page)
    mapa_por_id = construir_mapa_por_id_sector(page)

    try:
        sectores_svg = page.evaluate(r"""
        () => {
            const elementos = Array.from(document.querySelectorAll('svg .interactive-sector'));
            const vistos = new Set();
            const res = [];
            elementos.forEach((el, i) => {
                const id = el.getAttribute('id') || `SVG_SEC_${i+1}`;
                if (!vistos.has(id)) {
                    vistos.add(id);
                    res.push({ id: id, fill: el.getAttribute('fill') || "", no_disponible: el.classList.contains('no_disponible') });
                }
            });
            return res;
        }
        """) or []
    except Exception:
        sectores_svg = []

    if not sectores_svg:
        # Sin mapa de sectores visible: se respeta el estado ya detectado
        # para esa fecha/categoría (agotado_default), en vez de forzar "NO".
        return [{
            "nombre_evento": evento_info.get("titulo", "N/A"),
            "tipo_evento": "Música",
            "fecha_evento": fecha_puntual,
            "lugar_evento": evento_info.get("lugar_catalogo", "N/A"),
            "sector": "SIN MAPA / GENERAL",
            "sector_id": "N/A",
            "precio_sector": "N/A",
            "agotado": agotado_default,
            "asientos_disponibles": "N/A",
            "asientos_ocupados": "N/A",
            "asientos_totales": "N/A",
            "porcentaje_ocupacion": "N/A",
            "fecha_scraping": timestamp(),
            "url_evento": url_origen
        }]

    registros = []
    for sec in sectores_svg:
        sec_id = sec["id"]
        fill_color = normalizar_hex(sec["fill"])
        es_no_disp = sec["no_disponible"]

        # Prioridad: número extraído del sector_id (ej. "TT4S7R-97" -> "4")
        # contra el mapa por id_sector — funciona incluso para sectores
        # agotados, donde el color queda pisado por el gris placeholder.
        # Si no matchea, cae al color, y por último a un nombre genérico.
        match_numero = re.match(r"^TT(\d+)", sec_id)
        numero_sector = match_numero.group(1) if match_numero else None

        if numero_sector and numero_sector in mapa_por_id and mapa_por_id[numero_sector].get("nombre"):
            info = mapa_por_id[numero_sector]
        else:
            info = mapa_colores.get(fill_color, {"nombre": f"Sector {sec_id}", "precio": ""})

        metricas = None

        if not es_no_disp:
            js_click = r"""
            (targetId) => {
                const cont = document.querySelector('.contenedor_filas_asientos');
                if (cont) cont.innerHTML = '';
                const el = document.getElementById(targetId);
                if (!el) return false;
                const opts = { bubbles: true, cancelable: true, view: window };
                el.dispatchEvent(new MouseEvent('click', opts));
                return true;
            }
            """
            try:
                if page.evaluate(js_click, sec_id):
                    page.wait_for_timeout(600)
                    for _ in range(3):
                        metricas = extraer_metricas_asientos(page)
                        if metricas:
                            break
                        page.wait_for_timeout(300)
            except Exception:
                pass

        if metricas:
            tot, ocu, disp = metricas["total"], metricas["ocupados"], metricas["disponibles"]
            porc = f"{(ocu / tot * 100):.2f}%"
            agotado = "SI" if disp == 0 else "NO"
        else:
            tot, ocu, disp, porc = "", "", "", ""
            agotado = "SI" if es_no_disp else "NO"

        registros.append({
            "nombre_evento": evento_info.get("titulo", "N/A"),
            "tipo_evento": "Música",
            "fecha_evento": fecha_puntual,
            "lugar_evento": evento_info.get("lugar_catalogo", "N/A"),
            "sector": info["nombre"],
            "sector_id": sec_id,
            "precio_sector": info["precio"],
            "agotado": agotado,
            "asientos_disponibles": disp,
            "asientos_ocupados": ocu,
            "asientos_totales": tot,
            "porcentaje_ocupacion": porc,
            "fecha_scraping": timestamp(),
            "url_evento": url_origen
        })

    return registros


def completar_anio(fecha_txt, evento_info):
    """
    Las fechas sacadas del alt de la imagen (Template C) o del h4 del botón
    (Template A multi-fecha) vienen sin año, ej: '31 de agosto'. Se completa
    con el año detectado en la fecha ya confirmada del catálogo
    (ej: '31 de agosto 2026 - 02 de septiembre 2026').
    """
    if not fecha_txt or re.search(r"\b20\d{2}\b", fecha_txt):
        return fecha_txt
    m = re.search(r"\b(20\d{2})\b", evento_info.get("fecha_catalogo", ""))
    return f"{fecha_txt} {m.group(1)}" if m else fecha_txt


def fila_agotada(evento_info, fecha_txt, url_origen):
    return {
        "nombre_evento": evento_info["titulo"],
        "tipo_evento": "Música",
        "fecha_evento": fecha_txt,
        "lugar_evento": evento_info.get("lugar_catalogo", "N/A"),
        "sector": "EVENTO COMPLETO",
        "sector_id": "N/A",
        "precio_sector": "N/A",
        "agotado": "SI",
        "asientos_disponibles": 0,
        "asientos_ocupados": "N/A",
        "asientos_totales": "N/A",
        "porcentaje_ocupacion": "100%",
        "fecha_scraping": timestamp(),
        "url_evento": url_origen
    }


def esperar_bloques_estables(page, intentos=4, espera_ms=1200):
    """
    Los banners de canal de venta (.button-block) pueden terminar de cargar
    un momento después del domcontentloaded (confirmado: en Aespa hay 10
    bloques reales, pero una lectura apurada solo capturó 3). Se espera a
    que el conteo de bloques relevantes deje de crecer entre dos lecturas
    antes de extraer fechas/links.

    HIPÓTESIS NO CONFIRMADA: en Anuel AA se detectaron solo 2 de 4 fechas
    reales (.box-fechas). No se pudo confirmar la causa exacta, pero es
    consistente con contenido que carga recién al hacer scroll (como pasa
    en la grilla del catálogo) — se agrega un scroll defensivo por las
    dudas. Si el problema persiste, hay que confirmarlo con el HTML real
    de esa landing en el momento exacto de la falla.
    """
    for _ in range(3):
        page.evaluate("window.scrollBy(0, 900);")
        page.wait_for_timeout(400)

    anterior = -1
    for _ in range(intentos):
        actual = page.evaluate(
            "document.querySelectorAll('.button-block, .box-fechas, a.boton').length"
        )
        if actual == anterior and actual > 0:
            return
        anterior = actual
        page.wait_for_timeout(espera_ms)


def ingresar_y_procesar_evento(page, evento_info):
    log(f"Procesando: {evento_info['titulo']}")
    registros_totales = []

    try:
        page.goto(evento_info["url"], timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    except Exception as e:
        log(f" Error de carga en evento: {e}")
        return []

    esperar_bloques_estables(page)
    fechas = extraer_fechas_y_links_js(page)

    if fechas is None:
        # Template D (ej. Jeff Mills): no hay .button-block en absoluto.
        # Se intenta mejorar al menos fecha/lugar con <address><time>, pero
        # todavía no está confirmado el botón de compra de este template,
        # así que queda como fila única de fallback.
        log("   -> Sin .button-block detectado, probando fallback <address>/<time>...")
        addr = extraer_fallback_address_js(page)
        if addr and addr.get("fecha"):
            evento_info = dict(evento_info)
            evento_info["fecha_catalogo"] = evento_info.get("fecha_catalogo") or addr["fecha"]
            evento_info["lugar_catalogo"] = addr.get("lugar") or evento_info.get("lugar_catalogo")
        fechas = []

    log(f"   -> {len(fechas)} fecha(s) / función(es) detectada(s).")

    if DEBUG_TITULO and DEBUG_TITULO.lower() in evento_info["titulo"].lower():
        log(f"   [DEBUG] evento_info completo: {evento_info}")
        log(f"   [DEBUG] fechas crudas detectadas en la landing: {fechas}")

    if not fechas:
        # Sin fechas detectadas (Template D, o página sin .button-block ni
        # box-fechas): se registra una fila única de fallback con lo mejor
        # que se pudo confirmar (catálogo + <address> si aplicó).
        fecha_txt = completar_anio(evento_info.get("fecha_catalogo") or "FECHA NO DETECTADA", evento_info)
        registros_totales.append({
            "nombre_evento": evento_info["titulo"],
            "tipo_evento": "Música",
            "fecha_evento": fecha_txt,
            "lugar_evento": evento_info.get("lugar_catalogo", "N/A"),
            "sector": "SIN BOTÓN DE COMPRA DETECTADO",
            "sector_id": "N/A",
            "precio_sector": "N/A",
            "agotado": "N/A",
            "asientos_disponibles": "N/A",
            "asientos_ocupados": "N/A",
            "asientos_totales": "N/A",
            "porcentaje_ocupacion": "N/A",
            "fecha_scraping": timestamp(),
            "url_evento": evento_info["url"]
        })
        return registros_totales

    for f in fechas:
        # Si el bloque de fecha no traía texto propio (ej. fallback de fecha
        # única), se completa con la fecha ya confirmada en el catálogo.
        fecha_txt = f["fecha_exacta"] or evento_info.get("fecha_catalogo") or "FECHA NO DETECTADA"
        fecha_txt = completar_anio(fecha_txt, evento_info)
        es_agotado = f["estado"] == "AGOTADO"
        href = f["url_compra"]

        if es_agotado or not href or href == evento_info["url"]:
            registros_totales.append(fila_agotada(evento_info, fecha_txt, evento_info["url"]))
            continue

        try:
            page.goto(href, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception as e:
            log(f"      Error al entrar a la fecha ({fecha_txt}): {e}")
            continue

        # Los links tipo /queue/enqueue/ (confirmado en Aitana) son una sala
        # de espera, no la pasarela final. El comportamiento del redirect
        # NO está confirmado con un caso real, así que en vez de asumir que
        # redirige solo, se le da tiempo extra y se registra si sigue
        # estancado ahí (para poder detectarlo en los logs y ajustarlo).
        if "queue/enqueue" in page.url:
            log("      Detectada sala de espera (queue/enqueue), esperando redirect...")
            page.wait_for_timeout(4000)
            if "queue/enqueue" in page.url:
                log("      Seguimos en la sala de espera tras la espera extra — revisar manualmente este caso.")

        registros_fecha = procesar_sector_mapa(
            page, evento_info, href, fecha_puntual=fecha_txt,
            agotado_default="SI" if es_agotado else "NO"
        )
        registros_totales.extend(registros_fecha)

    return registros_totales


def main():
    todos_los_registros = []

    with sync_playwright() as p:
        log(f"Conectando a Chrome vía CDP ({CDP_URL})...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        eventos = obtener_todos_los_eventos_catalogo(page)
        log(f"¡Éxito! Se detectaron {len(eventos)} eventos de Música.")

        if DEBUG_TITULO:
            for e in eventos:
                if DEBUG_TITULO.lower() in e["titulo"].lower():
                    log(f"   [DEBUG] Entrada cruda del catálogo para '{e['titulo']}': {e}")

        for idx, ev in enumerate(eventos, start=1):
            log(f"\n--- Evento [{idx}/{len(eventos)}] ---")

            if ev.get("agotado_evento"):
                log("   -> Evento marcado agotado a nivel de tarjeta, se registra directo.")
                todos_los_registros.append(fila_agotada(ev, ev.get("fecha_catalogo") or "FECHA NO DETECTADA", ev["url"]))
            else:
                try:
                    registros = ingresar_y_procesar_evento(page, ev)
                    todos_los_registros.extend(registros)
                except Exception as err:
                    log(f"Error procesando evento {idx}: {err}")

            if todos_los_registros:
                with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=COLUMNAS)
                    writer.writeheader()
                    writer.writerows(todos_los_registros)

        log(f"\n=======================================================")
        log(f"Proceso finalizado. Total de filas guardadas: {len(todos_los_registros)}")
        log(f"Guardado en: {CSV_PATH}")
        log(f"=======================================================")


if __name__ == "__main__":
    main()