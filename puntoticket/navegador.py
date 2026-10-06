"""Navegación robusta: reintentos, detección de cola virtual / Cloudflare,
captura de respuestas JSON de la red y volcado de diagnóstico."""
import json
import re
import time
from collections import deque

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .util import aviso, log, paso, slug

# Señales de que la página NO es el contenido sino una barrera.
JS_BARRERA = r"""
() => {
    const url = location.href.toLowerCase();
    const titulo = (document.title || '').toLowerCase();
    const texto = (document.body ? document.body.innerText : '').slice(0, 4000).toLowerCase();
    if (document.querySelector('#challenge-form, #cf-challenge-running, .cf-browser-verification, iframe[src*="challenges.cloudflare.com"]')
        || /just a moment|un momento|attention required|checking your browser|verificando/.test(titulo)
        || /verify you are human|verifica que eres humano|checking if the site connection is secure/.test(texto)) {
        return 'cloudflare';
    }
    if (/queue|enqueue|queue-it|waitingroom|sala-de-espera/.test(url)) return 'cola';
    // Por texto solo si la página no tiene contenido real (un footer que diga
    // "sala de espera" no debe frenar el scraper).
    const hayContenido = document.querySelector('article.event-item, li.sector, [data-id_sector], .button-block, svg .interactive-sector');
    if (!hayContenido && (/fila virtual|sala de espera|estás en la fila|estas en la fila|your place in line|tu lugar en la fila|queue-it/.test(texto))) {
        return 'cola';
    }
    return '';
}
"""


class RedJSON:
    """Guarda las últimas respuestas JSON (XHR/fetch) que hace la página.

    Sirve para descubrir APIs internas del sitio (con --diagnostico) y como
    fuente alternativa de eventos si cambia el HTML del catálogo.
    """

    def __init__(self, page, maximo=200, max_bytes=2_000_000):
        self.respuestas = deque(maxlen=maximo)
        self.max_bytes = max_bytes
        page.on("response", self._on_response)

    def _on_response(self, resp):
        try:
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            tipo = (resp.headers.get("content-type") or "").lower()
            if "json" not in tipo:
                return
            cuerpo = resp.body()
            if len(cuerpo) > self.max_bytes:
                return
            self.respuestas.append({"url": resp.url, "status": resp.status, "json": json.loads(cuerpo)})
        except Exception:  # noqa: BLE001  (respuestas canceladas, cuerpos no JSON, etc.)
            pass

    def desde(self, n):
        return list(self.respuestas)[n:]

    def __len__(self):
        return len(self.respuestas)


def detectar_barrera(page):
    try:
        return page.evaluate(JS_BARRERA) or ""
    except Exception:  # noqa: BLE001  (navegación en curso)
        return "navegando"


def esperar_sin_barrera(page, max_seg):
    """Espera a que la página deje de ser cola virtual / Cloudflare.

    Detecta explícitamente la redirección: no devuelve True hasta que la página
    ya no tiene señales de barrera. Nunca espera más de `max_seg`.
    """
    barrera = detectar_barrera(page)
    if not barrera:
        return True
    url_inicial = page.url
    if barrera == "cloudflare":
        aviso(f"Cloudflare / captcha en {url_inicial[:80]}: resolvelo a mano en la pestaña del scraper "
              f"(espero hasta {max_seg}s)")
    else:
        log(f"      cola virtual detectada en {url_inicial[:80]} (espero hasta {max_seg}s)")
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    paso(f"esperando que suelte {barrera}")
    inicio = time.time()
    ultimo_aviso = inicio
    while time.time() - inicio < max_seg:
        page.wait_for_timeout(2000)
        barrera = detectar_barrera(page)
        if not barrera:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            log(f"      barrera superada en {time.time() - inicio:.0f}s -> {page.url[:80]}")
            return True
        if time.time() - ultimo_aviso >= 15:
            ultimo_aviso = time.time()
            log(f"      sigue en {barrera} ({time.time() - inicio:.0f}/{max_seg}s) url={page.url[:80]}")
    return False


JS_ESTADO = r"""
() => ({
    url: location.href,
    titulo: document.title || '',
    listo: document.readyState,
    elementos: document.body ? document.body.getElementsByTagName('*').length : 0,
})
"""


def estado_pagina(page):
    try:
        return page.evaluate(JS_ESTADO)
    except Exception as e:  # noqa: BLE001  (navegación en curso)
        return {"url": page.url, "titulo": "", "listo": f"error: {str(e).splitlines()[0][:60]}", "elementos": 0}


def _misma_pagina(a, b):
    def limpiar(u):
        return re.sub(r"^https?://(www\.)?", "", (u or "").split("#")[0]).rstrip("/").lower()
    return limpiar(a) == limpiar(b)


def ir(page, url, cfg, selector=None, nombre="pagina"):
    """Navega con reintentos y sin bloquearse. Devuelve (ok, motivo).

    - goto con wait_until="commit" y timeout corto: no espera el evento "load"
      (scripts de analytics o Cloudflare pueden retenerlo para siempre).
    - Después espera domcontentloaded con timeout propio; si vence, sigue con
      el DOM que haya si ya es usable.
    - Detecta redirecciones y barreras (cola / Cloudflare) y avisa en vez de
      quedarse esperando en silencio.
    ok=True si hay una página usable, sin barrera y (si se pidió) con el selector.
    """
    motivo = ""
    for intento in range(1, cfg.reintentos + 1):
        log(f"      -> abriendo {url[:90]} (intento {intento}/{cfg.reintentos}, "
            f"timeout {cfg.timeout_carga_ms / 1000:.0f}s)")
        paso(f"cargando {url[:80]}")
        inicio = time.time()
        try:
            page.goto(url, timeout=cfg.timeout_carga_ms, wait_until="commit")
        except PlaywrightTimeout:
            log(f"      goto venció a los {cfg.timeout_carga_ms / 1000:.0f}s; reviso si el DOM ya sirve")
        except Exception as e:  # noqa: BLE001  (DNS, conexión rechazada, pestaña cerrada...)
            motivo = f"error de navegación ({str(e).splitlines()[0][:120]})"
            log(f"      {motivo}")
            page.wait_for_timeout(1500 * intento)
            continue
        try:
            page.wait_for_load_state("domcontentloaded", timeout=cfg.timeout_dom_ms)
        except Exception:  # noqa: BLE001
            log(f"      domcontentloaded no llegó en {cfg.timeout_dom_ms / 1000:.0f}s; sigo con lo que haya")
        est = estado_pagina(page)
        log(f"      <- {time.time() - inicio:.1f}s | {est['listo']} | {est['elementos']} elementos | "
            f"título: {est['titulo'][:60]!r}")
        if est["url"].startswith(("about:", "chrome-error:")) or est["elementos"] == 0:
            motivo = f"la página quedó en blanco ({est['url'][:60]})"
            log(f"      {motivo}; reintento")
            page.wait_for_timeout(1500 * intento)
            continue
        if not _misma_pagina(est["url"], url):
            log(f"      redirigido a {est['url'][:100]}")

        if not esperar_sin_barrera(page, cfg.espera_cola_seg):
            motivo = f"quedó en {detectar_barrera(page)} después de {cfg.espera_cola_seg}s"
            aviso(f"{nombre}: {motivo} ({page.url[:80]}). Si es un captcha, resolvelo y volvé a correr "
                  "(o subí --espera-cola).")
            return False, motivo
        paso(f"esperando que la red se calme en {page.url[:80]}")
        try:
            page.wait_for_load_state("networkidle", timeout=cfg.timeout_red_ms)
        except Exception:  # noqa: BLE001  (sitios con polling nunca quedan idle)
            pass
        if not selector:
            paso("")
            return True, ""
        paso(f"esperando '{selector}'")
        try:
            page.wait_for_selector(selector, timeout=cfg.timeout_elementos_ms, state="attached")
            paso("")
            return True, ""
        except Exception:  # noqa: BLE001
            motivo = f"no apareció ningún elemento '{selector}' en {cfg.timeout_elementos_ms / 1000:.0f}s"
            log(f"      {motivo}")
    paso("")
    return False, motivo


JS_CONTEO_SELECTORES = r"""
(selectores) => Object.fromEntries(selectores.map(s => {
    try { return [s, document.querySelectorAll(s).length]; } catch (e) { return [s, -1]; }
}))
"""

SELECTORES_DIAGNOSTICO = [
    "article.event-item", "article", "a[href] h3", "a[href] h2", "p.fecha", "[class*='event']", "[class*='card']",
    ".button-block", ".box-fechas", "a.boton", "address time",
    "li.sector", "[data-id_sector]", "svg .interactive-sector", "svg [id^='TT']",
    ".contenedor_filas_asientos", "li.asiento", "[class*='asiento']", "[class*='seat']", "iframe",
]


def volcar_diagnostico(page, cfg, nombre, red=None, desde=0):
    """Guarda HTML, captura, conteo de selectores y JSON de red en salida/diagnostico."""
    carpeta = cfg.salida / "diagnostico"
    carpeta.mkdir(parents=True, exist_ok=True)
    base = carpeta / slug(nombre)
    try:
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log(f"   no pude guardar el HTML: {e}")
    try:
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    info = {"url": page.url, "titulo": "", "barrera": detectar_barrera(page), "selectores": {}, "frames": []}
    try:
        info["titulo"] = page.title()
        info["selectores"] = page.evaluate(JS_CONTEO_SELECTORES, SELECTORES_DIAGNOSTICO)
        info["frames"] = [f.url for f in page.frames]
    except Exception:  # noqa: BLE001
        pass
    if red is not None:
        info["json_red"] = [{"url": r["url"], "status": r["status"]} for r in red.desde(desde)]
        with open(base.parent / f"{base.name}_red.json", "w", encoding="utf-8") as f:
            json.dump(red.desde(desde), f, ensure_ascii=False, indent=1, default=str)
    with open(base.parent / f"{base.name}_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    log(f"   diagnóstico guardado: {base}.* (selectores: "
        + ", ".join(f"{k}={v}" for k, v in info["selectores"].items() if v) + ")")
    return info


def es_url_puntoticket(url):
    return bool(re.search(r"puntoticket\.com", url or "", re.I))
