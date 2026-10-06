"""Capacidad de referencia de sectores agotados.

Un sector agotado no deja ver sus asientos, así que su capacidad se toma de
lecturas anteriores. La planilla de avance (04-08-2026) mostró que el mismo
sector_id en el mismo recinto cambia de capacidad entre eventos (ej. Movistar
Arena TT2S1: 72, 90, 144, 234 y 288 según el montaje), pero NUNCA dentro de una
misma función. Por eso el orden de búsqueda es:

  1. HISTORIAL_FUNCION : misma función (evento + fecha) y mismo sector_id.
  2. HISTORIAL_EVENTO  : mismo evento, otra fecha, mismo sector_id.
  3. REF_RECINTO       : mismo recinto y sector_id en otros eventos (mediana).
     Es solo una aproximación: otro montaje puede tener otra capacidad.

Conviene correr el scraper seguido: cuanto antes se lea un sector (cuando aún
tiene asientos libres), mejor queda su capacidad para cuando se agote.
"""
import csv
import statistics
from collections import defaultdict

from .util import a_int, normalizar

COLUMNAS_HISTORIAL = [
    "fecha_scraping", "recinto", "evento", "fecha_funcion", "hora", "sector_id",
    "sector", "asientos_totales", "asientos_vendidos",
]


class Capacidades:
    def __init__(self):
        self.funcion = defaultdict(int)   # (evento, fecha, sector_id) -> máx
        self.evento = defaultdict(int)    # (evento, sector_id) -> máx
        self.recinto = defaultdict(list)  # (recinto, sector_id) -> [máx por evento]
        self._recinto_evento = defaultdict(int)
        self._sucio = False

    def agregar(self, recinto, evento, fecha_funcion, sector_id, total):
        total = a_int(total)
        if not total or not sector_id:
            return
        ev, rc = normalizar(evento), normalizar(recinto)
        k = (ev, fecha_funcion or "", sector_id)
        self.funcion[k] = max(self.funcion[k], total)
        self.evento[(ev, sector_id)] = max(self.evento[(ev, sector_id)], total)
        self._recinto_evento[(rc, sector_id, ev)] = max(self._recinto_evento[(rc, sector_id, ev)], total)
        self._sucio = True

    def _armar_recinto(self):
        self.recinto = defaultdict(list)
        for (rc, sid, _ev), total in self._recinto_evento.items():
            self.recinto[(rc, sid)].append(total)
        self._sucio = False

    def buscar(self, recinto, evento, fecha_funcion, sector_id):
        """Devuelve (capacidad, fuente) o (None, "SIN_REFERENCIA")."""
        ev, rc = normalizar(evento), normalizar(recinto)
        v = self.funcion.get((ev, fecha_funcion or "", sector_id))
        if v:
            return v, "HISTORIAL_FUNCION"
        v = self.evento.get((ev, sector_id))
        if v:
            return v, "HISTORIAL_EVENTO"
        if self._sucio:
            self._armar_recinto()
        vals = self.recinto.get((rc, sector_id))
        if vals:
            return int(statistics.median(vals)), "REF_RECINTO"
        return None, "SIN_REFERENCIA"

    @classmethod
    def desde_historial(cls, ruta):
        cap = cls()
        if ruta.exists():
            with open(ruta, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    cap.agregar(r["recinto"], r["evento"], r["fecha_funcion"], r["sector_id"], r["asientos_totales"])
        return cap


def guardar_en_historial(ruta, filas_sector):
    """Agrega al historial las lecturas medidas de esta corrida."""
    nuevo = not ruta.exists()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_HISTORIAL)
        if nuevo:
            w.writeheader()
        for s in filas_sector:
            if s.get("fuente_capacidad") != "MEDIDO":
                continue
            w.writerow({
                "fecha_scraping": s["fecha_scraping"], "recinto": s["lugar"], "evento": s["evento"],
                "fecha_funcion": s["fecha"], "hora": s["hora"], "sector_id": s["sector_id"],
                "sector": s["sector"], "asientos_totales": s["asientos_totales"],
                "asientos_vendidos": s["asientos_vendidos"],
            })


def cargar_aforos(ruta):
    """recinto normalizado -> aforo total (personas). Filas sin aforo se ignoran."""
    aforos = {}
    if not ruta.exists():
        return aforos
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            v = a_int(r.get("aforo_total"))
            if v:
                aforos[normalizar(r["recinto"])] = v
    return aforos
