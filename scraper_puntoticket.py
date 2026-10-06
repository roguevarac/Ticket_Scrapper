"""Reporte de eventos de Música de PuntoTicket con ocupación por sector.

Uso típico (Chrome abierto con abrir_chrome.bat y sesión iniciada en PuntoTicket):
    python scraper_puntoticket.py
    python scraper_puntoticket.py --solo aitana --solo "paulo londra"
    python scraper_puntoticket.py --diagnostico --solo aitana
Ver README.md.
"""
import argparse
import sys
from pathlib import Path

# Debe correrse desde la carpeta del proyecto (la que contiene "puntoticket\").
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from puntoticket.config import RAIZ, Config  # noqa: E402
from puntoticket.navegador import es_url_puntoticket  # noqa: E402
from puntoticket.scraper import correr  # noqa: E402
from puntoticket.util import log  # noqa: E402


def argumentos(argv=None):
    d = Config()
    p = argparse.ArgumentParser(description="Scraper de Música de PuntoTicket")
    p.add_argument("--cdp", default=d.cdp_url, help="URL de depuración del Chrome abierto (default %(default)s)")
    p.add_argument("--lanzar", action="store_true",
                   help="abrir un Chromium propio (perfil en ./perfil_chrome) en vez de conectarse al Chrome abierto")
    p.add_argument("--catalogo", default=d.catalogo_url)
    p.add_argument("--solo", action="append", default=[], metavar="TEXTO",
                   help="procesar solo eventos cuyo título contenga TEXTO (se puede repetir)")
    p.add_argument("--limite", type=int, default=0, help="máximo de eventos a procesar")
    p.add_argument("--sin-asientos", action="store_true", help="no entrar a los sectores (más rápido)")
    p.add_argument("--espera-cola", type=int, default=d.espera_cola_seg,
                   help="segundos máximos en la cola virtual / Cloudflare (default %(default)s)")
    p.add_argument("--reintentos", type=int, default=d.reintentos, help="reintentos de carga por página")
    p.add_argument("--reintentos-sector", type=int, default=d.reintentos_sector,
                   help="reintentos de click por sector si no aparecen asientos")
    p.add_argument("--timeout-carga", type=int, default=d.timeout_carga_ms // 1000,
                   help="segundos máximos de cada navegación (default %(default)s)")
    p.add_argument("--timeout-sectores", type=int, default=d.timeout_elementos_ms // 1000,
                   help="segundos esperando que aparezcan tarjetas/sectores (default %(default)s)")
    p.add_argument("--timeout-asientos", type=int, default=d.timeout_asientos_ms // 1000,
                   help="segundos esperando asientos después del click (default %(default)s)")
    p.add_argument("--salida", default=str(RAIZ / "reportes"))
    p.add_argument("--debug", action="store_true",
                   help="guardar HTML, captura y JSON de red de cada página en reportes/diagnostico")
    p.add_argument("--diagnostico", action="store_true",
                   help="prueba corta: --debug y solo 1 evento (o los de --solo)")
    return p.parse_args(argv)


def _contexto_cdp(navegador):
    """Elige el contexto donde está abierto PuntoTicket (ventana normal o
    incógnito); si no hay ninguno, el primero."""
    for ctx in navegador.contexts:
        if any(es_url_puntoticket(pg.url) for pg in ctx.pages):
            return ctx
    if navegador.contexts:
        return navegador.contexts[0]
    return navegador.new_context()


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = argumentos(argv)
    cfg = Config(catalogo_url=a.catalogo, cdp_url=a.cdp, salida=Path(a.salida), filtro_titulos=a.solo,
                 limite=a.limite or (1 if a.diagnostico and not a.solo else 0),
                 leer_asientos=not a.sin_asientos, espera_cola_seg=a.espera_cola,
                 reintentos=max(1, a.reintentos), reintentos_sector=max(0, a.reintentos_sector),
                 timeout_carga_ms=a.timeout_carga * 1000, timeout_elementos_ms=a.timeout_sectores * 1000, timeout_asientos_ms=a.timeout_asientos * 1000,
                 debug=a.debug or a.diagnostico)
    with sync_playwright() as p:
        if a.lanzar:
            contexto = p.chromium.launch_persistent_context(str(RAIZ / "perfil_chrome"), headless=False,
                                                            viewport={"width": 1400, "height": 900})
        else:
            log(f"Conectando al Chrome abierto en {a.cdp} ...")
            try:
                navegador = p.chromium.connect_over_cdp(a.cdp, timeout=15000)
            except Exception as e:  # noqa: BLE001
                log(f"No pude conectarme a {a.cdp}: {str(e).splitlines()[0]}")
                log("Cerrá Chrome, abrilo con abrir_chrome.bat (o usá --lanzar) y volvé a intentar.")
                return 1
            contexto = _contexto_cdp(navegador)
            abiertas = [pg.url for pg in contexto.pages]
            log(f"Contexto con {len(abiertas)} pestaña(s); PuntoTicket abierto: "
                f"{'sí' if any(es_url_puntoticket(u) for u in abiertas) else 'NO (iniciá sesión en esa ventana)'}")
        # Pestaña propia: no toca las pestañas que ya tenías abiertas.
        log("Abriendo una pestaña nueva para el scraper...")
        page = contexto.new_page()
        log("Pestaña abierta (no la cierres mientras corre).")
        try:
            ruta = correr(page, cfg)
        finally:
            page.close()
            if a.lanzar:
                contexto.close()
    return 0 if ruta else 2


if __name__ == "__main__":
    sys.exit(main())
