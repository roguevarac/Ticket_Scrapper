"""Reporte de eventos de Música de PuntoTicket con ocupación por sector.

Uso típico (Chrome abierto con abrir_chrome.bat y sesión iniciada en PuntoTicket):
    python scraper_puntoticket.py
    python scraper_puntoticket.py --solo aitana --solo "paulo londra"
    python scraper_puntoticket.py --limite 3 --debug
Ver README.md.
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from puntoticket.config import RAIZ, Config
from puntoticket.scraper import correr
from puntoticket.util import log


def argumentos(argv=None):
    p = argparse.ArgumentParser(description="Scraper de Música de PuntoTicket")
    p.add_argument("--cdp", default=Config.cdp_url, help="URL de depuración del Chrome abierto (default %(default)s)")
    p.add_argument("--lanzar", action="store_true",
                   help="abrir un Chromium propio (perfil en ./perfil_chrome) en vez de conectarse al Chrome abierto")
    p.add_argument("--catalogo", default=Config.catalogo_url)
    p.add_argument("--solo", action="append", default=[], metavar="TEXTO",
                   help="procesar solo eventos cuyo título contenga TEXTO (se puede repetir)")
    p.add_argument("--limite", type=int, default=0, help="máximo de eventos a procesar")
    p.add_argument("--sin-asientos", action="store_true", help="no entrar a los sectores (más rápido)")
    p.add_argument("--espera-cola", type=int, default=90, help="segundos máximos en la sala de espera")
    p.add_argument("--salida", default=str(RAIZ / "reportes"))
    p.add_argument("--debug", action="store_true", help="guardar HTML y captura de cada página de compra")
    return p.parse_args(argv)


def main(argv=None):
    a = argumentos(argv)
    cfg = Config(catalogo_url=a.catalogo, cdp_url=a.cdp, salida=Path(a.salida), filtro_titulos=a.solo,
                 limite=a.limite, leer_asientos=not a.sin_asientos, espera_cola_seg=a.espera_cola, debug=a.debug)
    with sync_playwright() as p:
        if a.lanzar:
            contexto = p.chromium.launch_persistent_context(str(RAIZ / "perfil_chrome"), headless=False,
                                                            viewport={"width": 1400, "height": 900})
            navegador = None
        else:
            log(f"Conectando al Chrome abierto en {a.cdp}")
            try:
                navegador = p.chromium.connect_over_cdp(a.cdp)
            except Exception as e:  # noqa: BLE001
                log(f"No pude conectarme a {a.cdp}: {e}")
                log("Abrí Chrome con abrir_chrome.bat (o usá --lanzar) y volvé a intentar.")
                return 1
            contexto = navegador.contexts[0] if navegador.contexts else navegador.new_context()
        # Pestaña propia: no toca las pestañas que ya tenías abiertas.
        page = contexto.new_page()
        try:
            correr(page, cfg)
        finally:
            page.close()
            if a.lanzar:
                contexto.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
