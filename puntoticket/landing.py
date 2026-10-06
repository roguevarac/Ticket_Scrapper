"""Landing de cada evento: separa las funciones (una por fecha) y sus links de compra.

Templates confirmados en la versión anterior del scraper:
  A  .button-block con <h4> de fecha propio y <small>AGOTADO/DISPONIBLE</small>.
  C  la fecha está en un <h5> o en el alt de una <img> que aparece ANTES del
     bloque, en un div hermano (ej. Karol G). El alt puede decir "sold out".
  E  link a.boton y el <small> de estado es hermano del <a> (ej. Jamiroquai).
  D  sin botones, fecha/lugar en <address><time datetime="DD-MM-YYYY">
     (ej. Jeff Mills).
Se recorre el documento en orden y cada bloque toma la fecha del último
marcador visto (o la suya propia si su h3/h4 trae una fecha).

Ojo (caso Anuel): que la landing diga AGOTADO no garantiza que la función esté
agotada. Si el bloque tiene un link de compra distinto de la landing, igual se
entra a verificar; el estado de la landing queda como dato aparte.
"""
from .navegador import ir
from .util import log

JS_FUNCIONES = r"""
() => {
    const origin = window.location.origin;
    const patronFecha = /\d{1,2}\s+de\s+[a-záéíóúñ]+/i;

    let bloques = Array.from(document.querySelectorAll('.button-block, .box-fechas'));
    document.querySelectorAll('a.boton').forEach(a => {
        const w = a.closest('div') || a.parentElement;
        if (w && !bloques.some(b => b === w || b.contains(w) || w.contains(b))) bloques.push(w);
    });
    // Si un bloque contiene a otro (ej. .box-fechas con varios .button-block
    // adentro) se queda el interior; el <h4> del exterior pasa a ser marcador.
    bloques = bloques.filter(b => !bloques.some(o => o !== b && b.contains(o)));
    let estrategia = 'bloques';
    if (bloques.length === 0) {
        // Respaldo si cambiaron las clases: links que parecen de compra
        // (por URL o por texto), fuera del header/nav/footer.
        const pareceCompra = a => {
            const crudo = (a.getAttribute('href') || '').toLowerCase();
            const txt = (a.innerText || '').trim();
            if (!crudo || crudo.startsWith('#') || crudo.startsWith('javascript')) return false;
            // Solo ruta y query: el dominio "puntoticket" no debe contar como "ticket".
            const href = (a.pathname + a.search).toLowerCase();
            if (a.href.split('#')[0] === location.href.split('#')[0]) return false;
            return /queue|enqueue|compra|checkout|ticket|cal=|biz\d/.test(href) ||
                   /^(comprar|compra tus entradas|comprar entradas|entradas|tickets|buy)/i.test(txt);
        };
        Array.from(document.querySelectorAll('a[href]'))
            .filter(a => !a.closest('header, nav, footer') && pareceCompra(a))
            .forEach((a, _i, links) => {
                // Se sube hasta el contenedor más cercano que tenga una fecha,
                // siempre que no abarque otro link de compra.
                let w = a.parentElement && a.parentElement !== document.body ? a.parentElement : a;
                let nodo = w;
                for (let n = 0; n < 4 && nodo && nodo !== document.body; n++, nodo = nodo.parentElement) {
                    if (links.some(o => o !== a && nodo.contains(o))) break;
                    if (patronFecha.test(nodo.innerText || '')) { w = nodo; break; }
                }
                if (!bloques.includes(w)) bloques.push(w);
            });
        bloques = bloques.filter(b => !bloques.some(o => o !== b && b.contains(o)));
        estrategia = 'links de compra (respaldo)';
    }
    if (bloques.length === 0) return null;

    const marcadores = Array.from(document.querySelectorAll('h3, h4, h5, img[alt]'))
        .filter(el => !bloques.some(b => b.contains(el)))
        .map(el => {
            const texto = (el.tagName === 'IMG' ? (el.getAttribute('alt') || '') : el.innerText).replace(/\s+/g, ' ').trim();
            // "8, 9, 10 y 14 de septiembre" no es UNA fecha: se ignora (caso Morat).
            if (/\d+\s*,\s*\d+/.test(texto)) return null;
            if (!patronFecha.test(texto)) return null;
            return { tipo: 'fecha', nodo: el, texto, agotado: /sold\s*out|agotad[oa]/i.test(texto) };
        })
        .filter(Boolean);

    const items = [...marcadores, ...bloques.map(b => ({ tipo: 'bloque', nodo: b }))];
    items.sort((a, b) => {
        const pos = a.nodo.compareDocumentPosition(b.nodo);
        if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
        if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        return 0;
    });

    const res = [];
    let marcador = null;
    items.forEach(item => {
        if (item.tipo === 'fecha') { marcador = item; return; }
        const bloque = item.nodo;
        const links = Array.from(bloque.querySelectorAll('a[href]'));
        if (links.length === 0) return;
        const texto = (bloque.innerText || '').replace(/\s+/g, ' ').trim();
        const h = bloque.querySelector('h3, h4');
        const hTexto = h ? h.innerText.replace(/\s+/g, ' ').trim() : '';
        let fechaTexto = '';
        if (patronFecha.test(hTexto)) fechaTexto = hTexto;
        else if (patronFecha.test(texto)) fechaTexto = texto;
        else if (marcador) fechaTexto = marcador.texto;

        const small = bloque.querySelector('small');
        const smallTxt = small ? small.innerText.toUpperCase() : '';
        let agotado;
        if (smallTxt.includes('AGOTADO') || smallTxt.includes('DISPONIBLE')) {
            agotado = smallTxt.includes('AGOTADO');
        } else {
            agotado = links[0].classList.contains('inactive') || /AGOTAD[OA]|SOLD\s*OUT/.test(texto.toUpperCase()) ||
                      (!!marcador && marcador.agotado && fechaTexto === marcador.texto);
        }
        links.forEach(a => {
            const href = a.getAttribute('href') || '';
            if (!href || href.startsWith('#') || href.startsWith('javascript')) return;
            res.push({
                fecha_texto: fechaTexto,
                texto_bloque: texto,
                etiqueta: (a.innerText || '').replace(/\s+/g, ' ').trim(),
                agotado_landing: agotado,
                estrategia,
                url_compra: href.startsWith('http') ? href : origin + (href.startsWith('/') ? '' : '/') + href,
            });
        });
    });
    return res;
}
"""

JS_ADDRESS = r"""
() => {
    const addr = document.querySelector('address');
    if (!addr) return null;
    const times = Array.from(addr.querySelectorAll('time'));
    return {
        fecha: times[0] ? (times[0].getAttribute('datetime') || times[0].innerText) : '',
        texto: (addr.innerText || '').replace(/\s+/g, ' ').trim(),
        lugar: (addr.childNodes[0] && addr.childNodes[0].textContent || '').trim(),
    };
}
"""


def _esperar_bloques(page, intentos=5, espera_ms=1200):
    """Los .button-block pueden aparecer después del domcontentloaded (Aespa: 10
    reales, una lectura apurada vio 3). Se espera a que el conteo se estabilice."""
    for _ in range(4):
        page.evaluate("window.scrollBy(0, 900)")
        page.wait_for_timeout(350)
    anterior = -1
    for _ in range(intentos):
        actual = page.evaluate("document.querySelectorAll('.button-block, .box-fechas, a.boton').length")
        if actual == anterior and actual > 0:
            return
        anterior = actual
        page.wait_for_timeout(espera_ms)


def leer_landing(page, url, cfg):
    """Devuelve (botones, address, motivo_error). `botones` puede ser lista vacía."""
    ok, motivo = ir(page, url, cfg, nombre="landing")
    if not ok:
        return [], None, motivo
    _esperar_bloques(page)
    try:
        botones = page.evaluate(JS_FUNCIONES)
    except Exception as e:  # noqa: BLE001
        log(f"   error leyendo botones: {e}")
        botones = None
    try:
        address = page.evaluate(JS_ADDRESS)
    except Exception:  # noqa: BLE001
        address = None
    return botones or [], address, ""
