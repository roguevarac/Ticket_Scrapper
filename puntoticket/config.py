from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    catalogo_url: str = "https://www.puntoticket.com/musica"
    cdp_url: str = "http://127.0.0.1:9222"
    # Carpeta donde quedan los reportes de cada corrida.
    salida: Path = RAIZ / "reportes"
    # Historial acumulado de lecturas por sector (sirve para estimar la capacidad
    # de un sector cuando ya está agotado y no muestra asientos).
    historial: Path = RAIZ / "data" / "historial_sectores.csv"
    # Aforo total por recinto (lo completa el usuario) para estimar la cancha.
    aforos: Path = RAIZ / "data" / "aforo_recintos.csv"
    # Solo procesa eventos cuyo título contenga alguno de estos textos.
    filtro_titulos: list = field(default_factory=list)
    # Máximo de eventos a procesar (0 = todos).
    limite: int = 0
    # Si es False no entra a los mapas (solo fechas y estado).
    leer_asientos: bool = True
    # Segundos máximos esperando que la cola virtual o Cloudflare suelten.
    espera_cola_seg: int = 90
    # Pausa entre eventos para no saturar el sitio.
    pausa_entre_eventos_ms: int = 1500
    # Reintentos de carga de cada página (catálogo, landing, compra).
    reintentos: int = 3
    # Timeouts (milisegundos).
    timeout_carga_ms: int = 45000       # navegación (goto)
    timeout_red_ms: int = 8000          # esperar a que la red quede quieta (best effort)
    timeout_elementos_ms: int = 15000   # esperar a que aparezcan tarjetas / sectores
    timeout_asientos_ms: int = 5000     # esperar asientos después de click en un sector
    # Reintentos de click por sector cuando no aparecen los asientos.
    reintentos_sector: int = 1
    # Guarda HTML, captura y JSON de red de cada página de compra en salida/diagnostico.
    debug: bool = False
