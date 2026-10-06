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
