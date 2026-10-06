"""Lectura del catálogo https://www.puntoticket.com/musica.

Se prueban varias estrategias en orden y se usa la primera que devuelve eventos:

  1. tarjetas  : article.event-item (estructura confirmada con el HTML real de Aitana):
       <article class="event-item"><a href="/aitana">
         <p class="descripcion"><strong>Movistar Arena - Santiago Centro</strong> / Rock</p>
         <h3 title="Aitana ">Aitana</h3><p class="fecha">19 de octubre 2026</p></a></article>
  2. enlaces   : cualquier <a> del mismo sitio con un título (h2-h4, [title]) y un
                 texto con fecha ("19 de octubre"). Sirve si cambian las clases.
  3. red JSON  : objetos con nombre + url/slug en las respuestas XHR/fetch que hizo
                 la página (por si el catálogo pasa a cargarse desde una API).
"""
import re
import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .navegador import ir, volcar_diagnostico
from .util import aviso, log, paso

JS_TARJETAS = r"""
() => {
    const eventos = [];
    document.querySelectorAll('article.event-item, article[class*="event"], div.event-item').forEach(art => {
        const a = art.querySelector('a[href]') || art.closest('a[href]');
        if (!a) return;
        const h = a.querySelector('h3[title], h2[title], h4[title]') || a.querySelector('h3, h2, h4') ||
                  art.querySelector('h3, h2, h4');
        const titulo = h ? (h.getAttribute('title') || h.innerText).trim() : '';
        if (!titulo) return;
        const strong = art.querySelector('p.descripcion strong, .descripcion strong, [class*="lugar"], [class*="venue"]');
        const desc = art.querySelector('p.descripcion, .descripcion');
        let lugar = strong ? strong.innerText.trim() : '';
        let genero = '';
        if (desc) {
            const partes = desc.innerText.split('/');
            if (!lugar) lugar = partes[0].trim();
            if (partes.length > 1) genero = partes.slice(1).join('/').trim();
        }
        const pFecha = art.querySelector('p.fecha, .fecha, [class*="fecha"], [class*="date"], time');
        const fecha = pFecha ? pFecha.innerText.replace(/\s+/g, ' ').trim() : '';
        const agotado = /agotad[oa]|sold\s*out/i.test(art.innerText) ||
            !!art.querySelector('img[alt*="agotado" i], [class*="agotado" i], [class*="sold" i]');
        eventos.push({ titulo, url: a.href, lugar, genero, fecha_catalogo: fecha, agotado_catalogo: agotado });
    });
    return eventos;
}
"""

JS_ENLACES = r"""
() => {
    const patronFecha = /\d{1,2}\s+de\s+[a-záéíóúñ]+|\d{1,2}[-/]\d{1,2}[-/]20\d{2}/i;
    const eventos = [];
    document.querySelectorAll('a[href]').forEach(a => {
        if (a.closest('header, nav, footer')) return;
        if (a.origin !== location.origin) return;
        const texto = (a.innerText || '').replace(/\s+/g, ' ').trim();
        const m = texto.match(patronFecha);
        if (!m) return;
        const h = a.querySelector('h2, h3, h4, [title]');
        const titulo = h ? (h.getAttribute('title') || h.innerText).trim()
                         : texto.replace(m[0], '').split('|')[0].trim().slice(0, 120);
        if (!titulo) return;
        // Textos de los elementos "hoja" (sin hijos) + líneas: así funciona
        // tanto con <p> separados como con <span> en la misma línea.
        const hojas = Array.from(a.querySelectorAll('*')).filter(e => e.children.length === 0)
            .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim());
        const lineas = [...hojas, ...(a.innerText || '').split('\n').map(l => l.trim())].filter(Boolean);
        const lineaFecha = lineas.find(l => patronFecha.test(l)) || m[0];
        const lineaLugar = lineas.find(l => l !== titulo && l !== lineaFecha && !/^\$|comprar|ver m[aá]s/i.test(l)) || '';
        eventos.push({
            titulo, url: a.href, lugar: lineaLugar.split('/')[0].trim(),
            genero: lineaLugar.includes('/') ? lineaLugar.split('/').slice(1).join('/').trim() : '',
            fecha_catalogo: lineaFecha, agotado_catalogo: /agotad[oa]|sold\s*out/i.test(texto),
        });
    });
    return eventos;
}
"""

JS_CLICK_VER_MAS = r"""
() => {
    const b = Array.from(document.querySelectorAll('button, a'))
        .find(el => /^\s*(ver|cargar|mostrar)\s+m[aá]s\s*(eventos)?\s*$/i.test(el.innerText || '')
                    && el.offsetParent !== null);
    if (!b) return false;
    b.click();
    return true;
}
"""

SELECTOR_CATALOGO = "article.event-item, article, a[href] h3, a[href] h2"

_CLAVES_NOMBRE = ("nombre", "name", "titulo", "title", "evento", "eventName")
_CLAVES_URL = ("url", "link", "href", "slug", "permalink", "urlEvento")
_CLAVES_FECHA = ("fecha", "date", "fechaEvento", "startDate", "fecha_inicio", "fechas")
_CLAVES_LUGAR = ("lugar", "venue", "recinto", "location", "place")


def _primero(d, claves):
    for k in claves:
        v = d.get(k)
        if isinstance(v, dict):
            v = _primero(v, _CLAVES_NOMBRE) or _primero(v, _CLAVES_URL)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v).strip()
    return ""


def eventos_desde_json(respuestas, base_url):
    """Busca listas de objetos con nombre + url dentro de respuestas JSON."""
    eventos, vistos = [], set()

    def recorrer(nodo):
        if isinstance(nodo, list):
            for x in nodo:
                recorrer(x)
        elif isinstance(nodo, dict):
            nombre, url = _primero(nodo, _CLAVES_NOMBRE), _primero(nodo, _CLAVES_URL)
            if nombre and url and not url.startswith(("javascript", "#")) and not re.match(r"^https?://(?!.*puntoticket)", url):
                completa = urljoin(base_url, url if "/" in url or url.startswith("http") else "/" + url)
                if completa not in vistos:
                    vistos.add(completa)
                    eventos.append({"titulo": nombre, "url": completa, "lugar": _primero(nodo, _CLAVES_LUGAR),
                                    "genero": "", "fecha_catalogo": _primero(nodo, _CLAVES_FECHA),
                                    "agotado_catalogo": bool(re.search(r"agotad|sold", str(nodo), re.I))})
            for v in nodo.values():
                recorrer(v)

    for r in respuestas:
        recorrer(r["json"])
    return eventos


def _deduplicar(eventos, base_url):
    """Una entrada por URL; si una copia no trae fecha y otra sí, gana la completa."""
    por_url = {}
    for e in eventos:
        url = e["url"].split("#")[0].rstrip("/")
        if url.rstrip("/") == base_url.rstrip("/"):
            continue
        e["url"] = url
        if url not in por_url or (not por_url[url]["fecha_catalogo"] and e["fecha_catalogo"]):
            por_url[url] = e
    return list(por_url.values())


def _misma_ruta(a, b):
    def ruta(u):
        p = urlparse(u or "")
        return (p.netloc.lower().removeprefix("www."), p.path.rstrip("/").lower())
    return ruta(a) == ruta(b)


def _scroll_completo(page, max_seg=45):
    """Scroll (y "ver más") hasta que la cantidad de enlaces deje de crecer.
    Acotado a `max_seg` para que una grilla infinita no lo deje girando."""
    anterior, quietos = -1, 0
    fin = time.time() + max_seg
    for _ in range(40):
        if time.time() > fin:
            log(f"   scroll cortado a los {max_seg}s")
            break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(700)
        clic = page.evaluate(JS_CLICK_VER_MAS)
        if clic:
            page.wait_for_timeout(1500)
        actual = page.evaluate("document.querySelectorAll('a[href]').length")
        quietos = quietos + 1 if actual == anterior and not clic else 0
        if quietos >= 3:
            break
        anterior = actual


def leer_catalogo(page, cfg, red=None):
    """Devuelve la lista de eventos. Lista vacía si no se pudo leer (con diagnóstico)."""
    log(f"Cargando catálogo {cfg.catalogo_url} ...")
    inicio = time.time()
    inicio_red = len(red) if red is not None else 0
    ok, motivo = ir(page, cfg.catalogo_url, cfg, nombre="catalogo")
    if not ok:
        aviso(f"el catálogo no cargó: {motivo}")
        volcar_diagnostico(page, cfg, "catalogo", red, inicio_red)
        return []
    log(f"Catálogo abierto en {time.time() - inicio:.1f}s: {page.url}")
    if not _misma_ruta(page.url, cfg.catalogo_url):
        aviso(f"el catálogo redirigió a {page.url}: puede requerir interacción manual "
              "(login, captcha, aviso de cookies). Revisá la pestaña del scraper.")

    # Espera acotada y no bloqueante: si las tarjetas no aparecen se prueban
    # igual las otras estrategias (enlaces genéricos, JSON de la red).
    espera_ms = min(cfg.timeout_elementos_ms, 10000)
    paso(f"esperando tarjetas del catálogo ({SELECTOR_CATALOGO})")
    try:
        page.wait_for_selector(SELECTOR_CATALOGO, timeout=espera_ms, state="attached")
        log("   tarjetas visibles, haciendo scroll para cargar todas...")
    except PlaywrightTimeout:
        log(f"   no apareció '{SELECTOR_CATALOGO}' en {espera_ms / 1000:.0f}s; pruebo otras estrategias")
    except Exception as e:  # noqa: BLE001  (navegación en curso, pestaña cerrada)
        log(f"   error esperando las tarjetas ({str(e).splitlines()[0][:100]}); pruebo otras estrategias")
    paso("scroll del catálogo")
    _scroll_completo(page)
    paso("leyendo tarjetas del catálogo")

    eventos, estrategia = [], ""
    for intento in range(3):
        tarjetas = page.evaluate(JS_TARJETAS) or []
        if tarjetas:
            eventos, estrategia = tarjetas, "tarjetas (article.event-item)"
        else:
            enlaces = page.evaluate(JS_ENLACES) or []
            if enlaces:
                eventos, estrategia = enlaces, "enlaces con fecha (selector genérico)"
            elif red is not None:
                desde_red = eventos_desde_json(red.desde(inicio_red), page.url)
                if desde_red:
                    eventos, estrategia = desde_red, "JSON de la red (XHR/fetch)"
        eventos = _deduplicar(eventos, cfg.catalogo_url)
        if eventos and all(e["fecha_catalogo"] for e in eventos):
            break
        page.wait_for_timeout(1500)

    if not eventos:
        aviso("el catálogo cargó pero no encontré eventos con ninguna estrategia "
              "(¿cambió el HTML de PuntoTicket?). Revisá reportes/diagnostico/catalogo.*")
        volcar_diagnostico(page, cfg, "catalogo", red, inicio_red)
        return []

    sin_fecha = [e["titulo"] for e in eventos if not e["fecha_catalogo"]]
    log(f"Catálogo: {len(eventos)} eventos detectados (estrategia: {estrategia})")
    if sin_fecha:
        log(f"   {len(sin_fecha)} sin fecha en la tarjeta: {', '.join(sin_fecha[:8])}")
    if cfg.debug:
        volcar_diagnostico(page, cfg, "catalogo", red, inicio_red)
    return eventos
