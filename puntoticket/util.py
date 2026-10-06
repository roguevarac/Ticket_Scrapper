import re
import unicodedata


def log(msg):
    print(f"[PUNTOTICKET] {msg}", flush=True)


def normalizar(texto):
    """Mayúsculas, sin tildes y con espacios simples (para comparar lugares)."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def a_int(valor):
    try:
        if valor in ("", None):
            return None
        return int(float(valor))
    except (TypeError, ValueError):
        return None
