"""Say the Math local server: serves web/ and the JSON API on 127.0.0.1 only.

  python app.py [--port 8765] [--open] [--no-warm]

Images are decoded in memory, never written to disk and never logged. Outbound network connections
are refused for the whole process (recognition.netguard) before any model code is imported.
"""
import argparse
import json
import logging
import os
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from recognition import netguard  # noqa: E402

netguard.install()

from recognition import config, errors  # noqa: E402
from recognition.jobs import CLIENT_DISCONNECTED, CancelToken, DisconnectWatcher, use as use_job  # noqa: E402

log = logging.getLogger('saythemath')

STATIC_TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
                '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
                '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8',
                '.webmanifest': 'application/manifest+json'}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
DRAIN_LIMIT = 64 * 1024 * 1024  # larger rejected bodies are not read; the connection is closed
SECURITY_HEADERS = {
    'Content-Security-Policy': CSP,
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'X-Frame-Options': 'DENY',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'SayTheMath'
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    timeout = 60

    # ---- plumbing --------------------------------------------------------------------------
    def log_message(self, fmt, *args):  # request lines only; bodies are never logged
        pass

    def log_request(self, code='-', size='-'):
        if self.server.verbose:
            path = urlsplit(self.path).path if isinstance(self.path, str) else '?'
            log.info('%s %s %s', self.command, path, code)

    def _send(self, status, body: bytes, ctype, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if self.close_connection:
            self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self._send(status, body, 'application/json; charset=utf-8', {'Cache-Control': 'no-store'})

    def _error(self, err: errors.ApiError):
        self._json(err.status, err.envelope())

    def _allowed_hosts(self):
        port = self.server.server_address[1]
        return {f'127.0.0.1:{port}', f'localhost:{port}'}

    def _check_host(self):
        host = (self.headers.get('Host') or '').strip().lower()
        if host not in self._allowed_hosts():
            raise errors.ApiError(403, 'FORBIDDEN_HOST', 'This local server only answers requests addressed to 127.0.0.1 or localhost.')

    def _check_origin(self):
        origin = self.headers.get('Origin')
        if origin is not None:
            if origin.lower() not in {f'http://{h}' for h in self._allowed_hosts()}:
                raise errors.ApiError(403, 'FORBIDDEN_ORIGIN', 'Cross-origin requests are not accepted.')
        site = self.headers.get('Sec-Fetch-Site')
        if site is not None and site not in ('same-origin', 'none'):
            raise errors.ApiError(403, 'FORBIDDEN_ORIGIN', 'Cross-origin requests are not accepted.')

    def _content_length(self):
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return None
        return length if length >= 0 else None

    def _discard_body(self, length):
        """Drain a rejected body (bounded) so the client reliably receives the error response."""
        if length is None or length > DRAIN_LIMIT:
            self.close_connection = True
            return
        while length > 0:
            chunk = self.rfile.read(min(length, 1 << 20))
            if not chunk:
                break
            length -= len(chunk)

    def _read_json(self, limit, pdf=False):
        length = self._content_length()
        if self.headers.get('Transfer-Encoding'):
            self.close_connection = True
            raise errors.bad_request('Chunked requests are not supported; send Content-Length.')
        if length is None:
            self.close_connection = True
            raise errors.bad_request('Content-Length is required.')
        ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if ctype != 'application/json':
            self._discard_body(length)
            raise errors.ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Send the request as application/json.')
        if length > limit:
            self._discard_body(length)
            if pdf:
                raise errors.ApiError(413, 'PDF_TOO_LARGE', 'The PDF request is too large. Choose a PDF under 50 MiB.')
            raise errors.too_large('The request is too large. Use an image under 8 MB.')
        raw = self.rfile.read(length)
        if len(raw) != length:
            self.close_connection = True
            raise errors.bad_request('The request body was incomplete.')
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise errors.bad_request('The request body is not valid JSON.')
        finally:
            del raw

    def _guard(self, fn):
        try:
            fn()
        except errors.ApiError as e:
            try:
                self._error(e)
            except (ConnectionError, OSError):  # e.g. the client aborted, so its cancellation error has no reader
                self.close_connection = True
        except (ConnectionError, socket.timeout):
            self.close_connection = True
        except Exception as e:
            log.error('internal error: %s', type(e).__name__)
            if self.server.verbose:
                log.exception('details')
            self.close_connection = True
            try:
                self._error(errors.internal())
            except Exception:
                pass

    # ---- routes ----------------------------------------------------------------------------
    def do_GET(self):
        self._guard(self._get)

    def do_HEAD(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _not_allowed(self):
        self._discard_body(self._content_length() or 0)  # no CORS preflight is ever granted
        self._error(errors.ApiError(405, 'METHOD_NOT_ALLOWED', 'Method not allowed.'))

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _not_allowed

    def _get(self):
        self._check_host()
        path = urlsplit(self.path).path
        if path == '/api/status':
            return self._json(200, self.server.service.status())
        if path == '/api/pdf/status':
            from recognition.pdfnav import availability
            return self._json(200, availability())
        if path.startswith('/api/'):
            raise errors.ApiError(404, 'NOT_FOUND', 'Unknown API endpoint.')
        self._static(path)

    def _post(self):
        try:
            self._check_host()
            self._check_origin()
        except errors.ApiError:
            self._discard_body(self._content_length())
            raise
        path = urlsplit(self.path).path
        if path == '/api/read':
            payload = self._read_json(config.MAX_BODY_BYTES)
            return self._json(200, self._watched(self.server.service.read, payload, config.READ_TIME_LIMIT_S))
        if path == '/api/format':
            payload = self._read_json(config.MAX_FORMAT_BODY_BYTES)
            return self._json(200, self.server.service.format(payload))
        if path in ('/api/pdf/open', '/api/pdf/crop', '/api/pdf/read', '/api/pdf/close'):
            from recognition.pdfnav import MAX_PDF_BODY
            payload = self._read_json(MAX_PDF_BODY if path.endswith('/open') else config.MAX_FORMAT_BODY_BYTES,
                                      pdf=path.endswith('/open'))
            operation = path.rsplit('/', 1)[1]
            if operation == 'read':
                return self._json(200, self._watched(self.server.pdf.read, payload, config.READ_TIME_LIMIT_S))
            if operation == 'open':
                return self._json(200, self._watched(self.server.pdf.open, payload, config.PDF_OPEN_TIME_LIMIT_S))
            return self._json(200, getattr(self.server.pdf, operation)(payload))
        self._discard_body(self._content_length())
        raise errors.ApiError(404, 'NOT_FOUND', 'Unknown API endpoint.')

    def _watched(self, operation, payload, limit_s):
        """Run a long operation with a time limit, cancelled as soon as the client disconnects (browser abort,
        Cancel, choosing another equation, closing the page). The computation itself stops; nothing keeps running."""
        token = CancelToken(limit_s)
        with DisconnectWatcher(self.connection, token), use_job(token):
            try:
                return operation(payload)
            finally:
                if token.reason == CLIENT_DISCONNECTED:
                    self.close_connection = True  # the client is gone; do not try to keep the connection alive
                    log.info('request stopped after client disconnect (%.1f s)', token.elapsed())

    def _static(self, path):
        if path in ('', '/'):
            path = '/index.html'
        try:
            rel = unquote(path, errors='strict').lstrip('/')
        except UnicodeDecodeError:
            rel = '..'
        bad = ('\\' in rel or '\x00' in rel or ':' in rel or any(part in ('', '.', '..') for part in rel.split('/'))
               or any(part.startswith('.') for part in rel.split('/')))
        web = config.WEB_DIR.resolve()
        target = (web / rel).resolve() if not bad else None
        if bad or target is None or web not in target.parents or not target.is_file():
            return self._send(404, b'Not found', 'text/plain; charset=utf-8', {'Cache-Control': 'no-store'})
        ctype = STATIC_TYPES.get(target.suffix.lower())
        if ctype is None:
            return self._send(404, b'Not found', 'text/plain; charset=utf-8', {'Cache-Control': 'no-store'})
        self._send(200, target.read_bytes(), ctype, {'Cache-Control': 'no-cache'})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # never share the port with another process

    def __init__(self, addr, service, verbose=False):
        super().__init__(addr, Handler)
        self.service = service
        from recognition.pdfnav import PDFNavigation
        self.pdf = PDFNavigation(service)
        self.verbose = verbose

    def service_actions(self):
        self.pdf.expire()

    def handle_error(self, request, client_address):
        # A browser resetting an idle keep-alive connection, or aborting a request, is normal; stay quiet.
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def server_close(self):
        if hasattr(self, 'pdf'):
            self.pdf.clear()
        super().server_close()


def make_server(port, service, verbose=False, tries=10):
    last = None
    for p in range(port, port + tries):
        try:
            return Server(('127.0.0.1', p), service, verbose)
        except OSError as e:
            last = e
    raise SystemExit(f'Could not open a local port between {port} and {port + tries - 1}: {last}')


def main():
    ap = argparse.ArgumentParser(description='Say the Math local server (127.0.0.1 only).')
    ap.add_argument('--port', type=int, default=config.DEFAULT_PORT)
    ap.add_argument('--open', action='store_true', help='open the app in the default browser')
    ap.add_argument('--no-warm', action='store_true', help='load the model on the first reading instead of at startup')
    ap.add_argument('--verbose', action='store_true', help='log request lines (never bodies) and error details')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    from recognition.service import ReaderService
    service = ReaderService()
    httpd = make_server(a.port, service, a.verbose)
    port = httpd.server_address[1]
    url = f'http://127.0.0.1:{port}/'
    st = service.status()
    print(f'Say the Math is running at {url}', flush=True)
    print(st['message'], flush=True)
    print('Press Ctrl+C to stop.', flush=True)
    if not a.no_warm and st['ready']:
        def warm():
            service.warm_up()
            print(service.status()['message'] if service.status()['ready'] else 'Setup problem: ' + service.status()['message'], flush=True)
        threading.Thread(target=warm, daemon=True, name='warm-up').start()
    if a.open and os.environ.get('SAYTHEMATH_NO_BROWSER') != '1':
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print('Stopping.', flush=True)
    finally:
        httpd.server_close()
        httpd.pdf.clear()
        service.close()


if __name__ == '__main__':
    main()
