import functools
import http.server
import threading
import time
from pathlib import Path

import pytest

SITIO = Path(__file__).parent / "sitio"


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def do_GET(self):
        if self.path.startswith("/api/lento"):
            # Imita un long-polling / analytics: cabecera JSON y la respuesta nunca termina.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            self.wfile.write(b'{"ping": ')
            self.wfile.flush()
            time.sleep(120)
            return
        super().do_GET()


@pytest.fixture(scope="session")
def servidor():
    """Sirve tests/sitio (imitación del HTML de PuntoTicket) en un puerto local."""
    handler = functools.partial(Handler, directory=str(SITIO))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
