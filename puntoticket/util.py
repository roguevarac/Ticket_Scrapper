import re
import unicodedata

AVISOS = []  # advertencias de la corrida, se repiten en el resumen final


def log(msg):
    print(f"[PUNTOTICKET] {msg}", flush=True)


def aviso(msg):
    """Advertencia visible: se imprime ahora y se repite al final de la corrida."""
    AVISOS.append(msg)
    print(f"[PUNTOTICKET] *** ADVERTENCIA: {msg}", flush=True)


def normalizar(texto):
    """Mayúsculas, sin tildes y con espacios simples (para comparar lugares)."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def slug(texto):
    return re.sub(r"_+", "_", "".join(c if c.isalnum() else "_" for c in normalizar(texto))).strip("_")[:60].lower() or "pagina"


def a_int(valor):
    try:
        if valor in ("", None):
            return None
        return int(float(valor))
    except (TypeError, ValueError):
        return None


class Vigia:
    """Hilo que avisa en consola si un paso tarda demasiado.

    No interrumpe nada (Playwright sync no se puede cortar desde otro hilo),
    pero evita que la consola quede muda: dice en qué paso está esperando y
    hace cuánto, con una pista de qué revisar en Chrome.
    """

    def __init__(self, cada_seg=15):
        import threading
        import time
        self._time = time
        self.cada_seg = cada_seg
        self.paso_actual, self.desde = "", time.time()
        self._fin = threading.Event()
        self._hilo = threading.Thread(target=self._vigilar, daemon=True)
        self._hilo.start()

    def paso(self, texto):
        self.paso_actual, self.desde = texto, self._time.time()

    def _vigilar(self):
        while not self._fin.wait(self.cada_seg):
            if not self.paso_actual:
                continue
            seg = self._time.time() - self.desde
            if seg >= self.cada_seg:
                print(f"[PUNTOTICKET]    ... sigue esperando: {self.paso_actual} ({seg:.0f}s). "
                      "Mirá la pestaña que abrió el scraper en Chrome: si hay captcha/Cloudflare "
                      "resolvelo a mano.", flush=True)

    def terminar(self):
        self._fin.set()


VIGIA = None


def paso(texto):
    """Marca el paso actual para el vigía (si está activo)."""
    if VIGIA:
        VIGIA.paso(texto)
