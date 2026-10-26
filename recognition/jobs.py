"""Cancellation and time limits for local recognition and PDF discovery.

A CancelToken is checked inside the computation: before every encoder/decoder/resizer forward pass of pix2tex
(one decoder pass per generated token) and between PDF pages. Raising from the check unwinds the computation, so a
cancelled or timed-out job stops within one model step or one page instead of running to completion in the
background. The checks do not change any recognition setting or numeric result.
"""
import contextlib
import contextvars
import socket
import select
import threading
import time

CLIENT_DISCONNECTED = 'client_disconnected'
TIME_LIMIT = 'time_limit'
CLOSED = 'closed'


_CURRENT = contextvars.ContextVar('saythemath_job_token', default=None)


@contextlib.contextmanager
def use(token):
    """Make token the current job's token for code running in this thread (keeps call signatures unchanged)."""
    reset = _CURRENT.set(token)
    try:
        yield token
    finally:
        _CURRENT.reset(reset)


def current():
    return _CURRENT.get()


class RecognitionStopped(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class CancelToken:
    def __init__(self, limit_s=None, clock=time.monotonic):
        self._clock = clock
        self._event = threading.Event()
        self.reason = None
        self.limit_s = limit_s
        self.started = clock()
        self.deadline = self.started + limit_s if limit_s else None
        self.stopped_at = None

    def cancel(self, reason='cancelled'):
        if self.reason is None:
            self.reason = reason
            self.stopped_at = self._clock()
        self._event.set()

    @property
    def cancelled(self):
        if not self._event.is_set() and self.deadline is not None and self._clock() > self.deadline:
            self.cancel(TIME_LIMIT)
        return self._event.is_set()

    def check(self):
        if self.cancelled:
            raise RecognitionStopped(self.reason)

    def elapsed(self):
        return self._clock() - self.started


class DisconnectWatcher:
    """Cancel a token when the HTTP client closes its connection (e.g. the browser aborted fetch()).

    The request body has already been read, so the socket only becomes readable again if the client closed it
    (recv returns b'') or reset it. Pipelined data is not expected from browsers; if seen, watching stops.
    """

    def __init__(self, sock, token, interval=0.1):
        self.sock, self.token, self.interval = sock, token, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name='disconnect-watcher')

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self):
        while not self._stop.is_set() and not self.token.cancelled:
            try:
                readable, _, _ = select.select([self.sock], [], [], self.interval)
            except (OSError, ValueError):
                return
            if not readable:
                continue
            try:
                data = self.sock.recv(1, socket.MSG_PEEK)
            except BlockingIOError:
                continue
            except (ConnectionError, OSError):
                self.token.cancel(CLIENT_DISCONNECTED)
                return
            if data == b'':
                self.token.cancel(CLIENT_DISCONNECTED)
            return
