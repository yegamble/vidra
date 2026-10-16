"""Fixture-only readiness bridge for the unchanged restore script's curl check."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


class _QuietServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address

    def handle_error(self, request, client_address):
        pass  # Never print request state or backend exception values.


@contextmanager
def readiness_relay(host, *, port=8080):
    """Bind loopback for this context only; port=0 permits isolated HTTP tests."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def empty(self, status):
            self.close_connection = True
            self.send_response_only(status)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()

        def send_error(self, code, message=None, explain=None):
            self.empty(code)

        def do_GET(self):
            # BaseHTTPRequestHandler normalizes // prefixes; inspect the raw
            # target too so an alternate path cannot become an allowed one.
            if self.path != '/readyz' or self.requestline.split()[1] != '/readyz':
                self.empty(404)
                return
            try:
                status = host.readyz_status(timeout=2)
            except Exception:
                status = 503
            # curl -f accepts redirects and other 2xx statuses. Only backend
            # 200 proves readiness; preserve actual bounded HTTP failures.
            if type(status) is not int or not (status == 200 or 400 <= status <= 599):
                status = 503
            self.empty(status)

    server = _QuietServer(('127.0.0.1', port), Handler)
    worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02},
                    name='sealed-readiness-relay', daemon=True)
    try:
        worker.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}/readyz'
        finally:
            server.shutdown()
            worker.join()
    finally:
        server.server_close()
