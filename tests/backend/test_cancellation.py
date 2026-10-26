"""Bounded execution and cancellation (deterministic part).

SlowReader is an explicit TEST DOUBLE: it simulates a long decode as many small steps and calls token.check()
between them, exactly where the real model's forward pre-hooks call it. Real-model behaviour on known slow crops
is in test_cancellation_real.py.
"""
import base64
import http.client
import io
import json
import socket
import threading
import time

import numpy as np
import pytest
from PIL import Image

import app as app_module
from recognition import config, errors
from recognition.jobs import CLIENT_DISCONNECTED, TIME_LIMIT, CancelToken, DisconnectWatcher, RecognitionStopped, use
from recognition.service import ReaderService

GOOD = config.LOGPROB_THRESHOLD + 1e-4


class SlowReader:
    """TEST DOUBLE. Each read takes `steps` x `step_s`; the latex encodes the image width so results are traceable."""

    def __init__(self, steps=200, step_s=0.01):
        self.models_dir = config.MODELS_DIR
        self.loaded = True
        self.parameters = dict(config.EXPECTED_PARAMETERS)
        self.steps, self.step_s = steps, step_s
        self.active = 0
        self.max_active = 0
        self.started = 0
        self.finished = 0
        self.stopped = []
        self.lock = threading.Lock()

    def load(self):
        pass

    def read_scales(self, img, token=None):
        with self.lock:
            self.active += 1
            self.started += 1
            self.max_active = max(self.max_active, self.active)
        try:
            for _ in range(self.steps):
                if token is not None:
                    try:
                        token.check()
                    except RecognitionStopped as stop:
                        self.stopped.append((stop.reason, time.monotonic()))
                        raise
                time.sleep(self.step_s)
            with self.lock:
                self.finished += 1
            latex = f'w_{{{img.width}}}'
            return [{'scale': s, 'latex': latex, 'lp_mean': GOOD} for s in config.SCALES]
        finally:
            with self.lock:
                self.active -= 1


def png_b64(width):
    a = np.full((40, width, 3), 255, np.uint8)
    a[15:25, 10:width - 10] = 0
    b = io.BytesIO()
    Image.fromarray(a).save(b, format='PNG')
    return base64.b64encode(b.getvalue()).decode()


# ---- unit ----------------------------------------------------------------------------------
def test_token_time_limit_and_reason():
    now = [0.0]
    t = CancelToken(5, clock=lambda: now[0])
    t.check()
    now[0] = 5.1
    with pytest.raises(RecognitionStopped) as e:
        t.check()
    assert e.value.reason == TIME_LIMIT and t.cancelled
    t2 = CancelToken()
    t2.cancel(CLIENT_DISCONNECTED)
    t2.cancel('later reason')
    assert t2.reason == CLIENT_DISCONNECTED


def test_disconnect_watcher_detects_closed_peer():
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    client = socket.create_connection(srv.getsockname())
    conn, _ = srv.accept()
    token = CancelToken()
    with DisconnectWatcher(conn, token, interval=0.02):
        time.sleep(0.1)
        assert not token.cancelled
        client.close()
        deadline = time.monotonic() + 2
        while not token.cancelled and time.monotonic() < deadline:
            time.sleep(0.01)
    assert token.reason == CLIENT_DISCONNECTED
    conn.close()
    srv.close()


def test_service_time_limit_is_explicit_and_releases_lock():
    reader = SlowReader(steps=1000, step_s=0.01)
    svc = ReaderService(reader=reader)
    t0 = time.monotonic()
    with pytest.raises(errors.ApiError) as e, use(CancelToken(0.3)):
        svc.read({'image_base64': png_b64(120)})
    assert e.value.status == 504 and e.value.code == 'RECOGNITION_TIMEOUT'
    assert time.monotonic() - t0 < 1.0 and reader.finished == 0      # stopped inside the computation
    assert svc.last_stop['reason'] == TIME_LIMIT and svc.last_stop['unwind_s'] < 0.1
    reader.steps = 3
    assert svc.read({'image_base64': png_b64(130)})['latex'] == 'w_{130}'   # not left busy
    svc.close()


def test_service_cancel_from_another_thread():
    reader = SlowReader(steps=1000, step_s=0.01)
    svc = ReaderService(reader=reader)
    token = CancelToken()
    threading.Timer(0.2, token.cancel, args=(CLIENT_DISCONNECTED,)).start()
    with pytest.raises(errors.ApiError) as e, use(token):
        svc.read({'image_base64': png_b64(120)})
    assert e.value.code == 'RECOGNITION_CANCELLED' and reader.finished == 0
    svc.close()


def test_default_limit_applies_without_http(monkeypatch):
    monkeypatch.setattr(config, 'READ_TIME_LIMIT_S', 0.2)
    reader = SlowReader(steps=1000, step_s=0.01)
    svc = ReaderService(reader=reader)
    with pytest.raises(errors.ApiError) as e:
        svc.read({'image_base64': png_b64(120)})
    assert e.value.code == 'RECOGNITION_TIMEOUT'
    svc.close()


# ---- HTTP ----------------------------------------------------------------------------------
@pytest.fixture()
def server():
    reader = SlowReader(steps=300, step_s=0.01)   # ~3 s per read
    svc = ReaderService(reader=reader)
    httpd = app_module.make_server(0, svc)
    threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
    yield httpd, reader, svc
    httpd.shutdown()
    httpd.server_close()
    svc.close()


def raw_post(httpd, body):
    """Send a POST on a raw socket so the test can close the connection mid-request like an aborted fetch()."""
    port = httpd.server_address[1]
    data = json.dumps(body).encode()
    s = socket.create_connection(('127.0.0.1', port))
    s.sendall(f'POST /api/read HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n'
              f'Content-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n'.encode() + data)
    return s


def post(httpd, body, timeout=30):
    port = httpd.server_address[1]
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    c.request('POST', '/api/read', body=json.dumps(body).encode(), headers={
        'Host': f'127.0.0.1:{port}', 'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json'})
    r = c.getresponse()
    out = (r.status, json.loads(r.read()))
    c.close()
    return out


def wait_for(cond, limit=3.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


def test_abort_then_choose_another_is_not_busy_and_not_stale(server):
    httpd, reader, svc = server
    a = raw_post(httpd, {'image_base64': png_b64(120)})
    assert wait_for(lambda: reader.active == 1)
    a.close()                                            # user cancels / chooses another equation
    t0 = time.monotonic()
    status, body = post(httpd, {'image_base64': png_b64(200)})
    assert status == 200 and body['latex'] == 'w_{200}'  # the new image's result, never the old one
    assert reader.finished == 1 and reader.stopped and reader.stopped[0][0] == CLIENT_DISCONNECTED
    assert reader.max_active == 1                        # never two recognitions at once
    assert time.monotonic() - t0 < 3.0 + 1.0             # waited only for the old job to unwind, then ~3 s read
    assert wait_for(lambda: reader.active == 0)


def test_connected_client_still_gets_busy(server):
    httpd, reader, _ = server
    a = raw_post(httpd, {'image_base64': png_b64(120)})
    assert wait_for(lambda: reader.active == 1)
    t0 = time.monotonic()
    status, body = post(httpd, {'image_base64': png_b64(200)})
    assert status == 409 and body['error']['code'] == 'BUSY' and time.monotonic() - t0 < 0.5
    resp = a.recv(65536).decode()
    deadline = time.monotonic() + 10
    while 'w_{120}' not in resp and time.monotonic() < deadline:
        resp += a.recv(65536).decode()
    assert 'w_{120}' in resp                             # the connected client's own result
    a.close()


def test_rapid_reselection_does_not_accumulate_jobs(server):
    httpd, reader, _ = server
    for width in (110, 120, 130, 140, 150):
        s = raw_post(httpd, {'image_base64': png_b64(width)})
        assert wait_for(lambda: reader.active == 1)
        s.close()
        time.sleep(0.05)
    status, body = post(httpd, {'image_base64': png_b64(260)})
    assert status == 200 and body['latex'] == 'w_{260}'
    assert reader.max_active == 1 and reader.finished == 1 and len(reader.stopped) == 5
    assert all(r == CLIENT_DISCONNECTED for r, _ in reader.stopped)
    assert wait_for(lambda: reader.active == 0)


def test_http_time_limit_returns_explicit_state(server, monkeypatch):
    httpd, reader, _ = server
    monkeypatch.setattr(config, 'READ_TIME_LIMIT_S', 0.5)
    t0 = time.monotonic()
    status, body = post(httpd, {'image_base64': png_b64(120)})
    assert status == 504 and body['error']['code'] == 'RECOGNITION_TIMEOUT' and 'No reading was produced' in body['error']['message']
    assert time.monotonic() - t0 < 1.5 and reader.finished == 0
    monkeypatch.setattr(config, 'READ_TIME_LIMIT_S', 120)
    assert post(httpd, {'image_base64': png_b64(140)})[1]['latex'] == 'w_{140}'
