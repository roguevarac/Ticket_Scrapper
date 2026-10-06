import functools
import http.server
import threading
from pathlib import Path

import pytest

SITIO = Path(__file__).parent / "sitio"


@pytest.fixture(scope="session")
def servidor():
    """Sirve tests/sitio (imitación del HTML de PuntoTicket) en un puerto local."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITIO))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
