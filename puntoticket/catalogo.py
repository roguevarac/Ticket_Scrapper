"""Lectura del catálogo https://www.puntoticket.com/musica.

Estructura confirmada de cada tarjeta (HTML real de Aitana):
    <article class="event-item">
      <a href="/aitana">
        <p class="descripcion text-truncate"><strong>Movistar Arena - Santiago Centro</strong> / Rock</p>
        <h3 title="Aitana ">Aitana</h3>
        <p class="fecha">19 de octubre 2026</p>
      </a>
    </article>
"""
from .util import log

JS_CATALOGO = r"""
() => {
    const eventos = [];
    document.querySelectorAll('article.event-item').forEach(art => {
        const a = art.querySelector('a[href]');
        if (!a) return;
        const h3 = a.querySelector('h3[title]') || a.querySelector('h3');
        const titulo = h3 ? (h3.getAttribute('title') || h3.innerText).trim() : '';
        if (!titulo) return;

        const strong = a.querySelector('p.descripcion strong');
        const desc = a.querySelector('p.descripcion');
        let lugar = strong ? strong.innerText.trim() : '';
        let genero = '';
        if (desc) {
            const partes = desc.innerText.split('/');
            if (!lugar) lugar = partes[0].trim();
            if (partes.length > 1) genero = partes.slice(1).join('/').trim();
        }
        const pFecha = a.querySelector('p.fecha');
        const fecha = pFecha ? pFecha.innerText.replace(/\s+/g, ' ').trim() : '';
        const agotado = /agotad[oa]|sold\s*out/i.test(art.innerText) ||
            !!art.querySelector('img[alt*="agotado" i], [class*="agotado" i], [class*="sold" i]');

        const nuevo = { titulo, url: a.href, lugar, genero, fecha_catalogo: fecha, agotado_catalogo: agotado };
        const i = eventos.findIndex(e => e.url === a.href);
        if (i === -1) eventos.push(nuevo);
        else if (!eventos[i].fecha_catalogo && fecha) eventos[i] = nuevo;
    });
    return eventos;
}
"""

# Botones de "cargar más" que algunas grillas usan en vez de scroll infinito.
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


def leer_catalogo(page, url):
    log(f"Cargando catálogo {url}")
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # Scroll (y "ver más") hasta que la cantidad de tarjetas deje de crecer.
    anterior, quietos = -1, 0
    for _ in range(40):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(700)
        clic = page.evaluate(JS_CLICK_VER_MAS)
        if clic:
            page.wait_for_timeout(1500)
        actual = page.evaluate("document.querySelectorAll('article.event-item').length")
        quietos = quietos + 1 if actual == anterior and not clic else 0
        if quietos >= 3:
            break
        anterior = actual

    eventos = page.evaluate(JS_CATALOGO) or []
    for intento in range(4):
        if all(e["fecha_catalogo"] for e in eventos):
            break
        page.wait_for_timeout(1500)
        por_url = {e["url"]: e for e in page.evaluate(JS_CATALOGO) or []}
        eventos = [por_url.get(e["url"], e) if not e["fecha_catalogo"] else e for e in eventos]

    log(f"{len(eventos)} eventos en el catálogo")
    return eventos
