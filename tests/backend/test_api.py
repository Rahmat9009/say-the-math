"""HTTP API behaviour against the real server code and real math worker.

Recognition is replaced by an explicit test double (StubReader) here so that error, busy and
not-ready paths can be forced deterministically. Real-model HTTP tests are in test_real_model.py.
"""
import base64
import http.client
import io
import json
import threading
import time

import numpy as np
import pytest
from PIL import Image

import app as app_module
from recognition import config
from recognition.service import ReaderService
from treecheck import check_tree

GOOD = config.LOGPROB_THRESHOLD + 1e-4


class StubReader:
    """TEST DOUBLE. Returns scripted reads; never used by the app."""

    def __init__(self):
        self.models_dir = config.MODELS_DIR
        self.loaded = True
        self.parameters = dict(config.EXPECTED_PARAMETERS)
        self.reads = [{'scale': s, 'latex': r'\frac{x+1}{2}', 'lp_mean': GOOD} for s in config.SCALES]
        self.gate = None
        self.raise_exc = None
        self.calls = 0

    def load(self):
        pass

    def read_scales(self, img, token=None):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(10)
        if self.raise_exc:
            raise self.raise_exc
        return [dict(r) for r in self.reads]


@pytest.fixture(scope='module')
def server():
    reader = StubReader()
    svc = ReaderService(reader=reader)
    httpd = app_module.make_server(0, svc)
    t = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
    t.start()
    yield httpd, reader, svc
    httpd.shutdown()
    httpd.server_close()
    svc.close()


@pytest.fixture(autouse=True)
def reset(server):
    _, reader, svc = server
    reader.reads = [{'scale': s, 'latex': r'\frac{x+1}{2}', 'lp_mean': GOOD} for s in config.SCALES]
    reader.gate = None
    reader.raise_exc = None
    svc.model_error = None
    svc.math_error = None
    svc.model_problems = []


def png_b64(size=(120, 40), blank=False):
    a = np.full((size[1], size[0], 3), 255, np.uint8)
    if not blank:
        a[15:25, 10:size[0] - 10] = 0
    b = io.BytesIO()
    Image.fromarray(a).save(b, format='PNG')
    return base64.b64encode(b.getvalue()).decode()


def request(server, method, path, body=None, headers=None, raw=None):
    httpd = server[0]
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    h = {'Host': f'127.0.0.1:{port}'}
    if body is not None or raw is not None:
        h['Content-Type'] = 'application/json'
        h['Origin'] = f'http://127.0.0.1:{port}'
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    conn.request(method, path, body=data, headers=h)
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    ctype = resp.getheader('Content-Type') or ''
    return resp.status, (json.loads(payload) if 'json' in ctype else payload), resp


def err_code(result):
    return result[0], result[1]['error']['code']


def test_status_shape(server):
    status, body, resp = request(server, 'GET', '/api/status')
    assert status == 200
    assert set(body) == {'ready', 'model_available', 'math_available', 'message', 'model'}
    assert body['ready'] is True and body['model'] == {'name': 'pix2tex', 'parameters': 30351829}
    assert resp.getheader('Cache-Control') == 'no-store'
    assert "default-src 'self'" in resp.getheader('Content-Security-Policy')
    assert 'models' not in body['message'] and ':\\' not in body['message']


def test_read_success_matches_contract(server):
    status, body, _ = request(server, 'POST', '/api/read', {'image_base64': png_b64(), 'filename': 'eq.png'})
    assert status == 200
    for k in ('latex', 'speech', 'mathml', 'confidence', 'root_id', 'nodes', 'alternatives', 'elapsed_ms'):
        assert k in body
    assert body['confidence'] == {'level': 'higher', 'message': config.HIGHER_MESSAGE, 'agreeing_reads': 3, 'total_reads': 3}
    assert body['alternatives'] == [{'latex': r'\frac{x+1}{2}', 'count': 3}]
    check_tree(body)


def test_uncertain_and_alternatives(server):
    _, reader, _ = server
    reader.reads = [{'scale': 1.0, 'latex': 'x^{3}', 'lp_mean': -0.2}, {'scale': 0.75, 'latex': 'x^{8}', 'lp_mean': -0.1},
                    {'scale': 0.55, 'latex': 'x^{3}', 'lp_mean': -0.3}]
    status, body, _ = request(server, 'POST', '/api/read', {'image_base64': png_b64()})
    assert status == 200 and body['latex'] == 'x^{3}'
    assert body['confidence']['level'] == 'uncertain' and body['confidence']['agreeing_reads'] == 2
    assert body['alternatives'] == [{'latex': 'x^{3}', 'count': 2}, {'latex': 'x^{8}', 'count': 1}]


def test_format_endpoint(server):
    status, body, _ = request(server, 'POST', '/api/format', {'latex': 'x^{8}'})
    assert status == 200 and set(body) >= {'latex', 'speech', 'mathml', 'root_id', 'nodes'}
    assert 'confidence' not in body and body['speech'] == 'x to the eighth power'
    check_tree(body)
    assert err_code(request(server, 'POST', '/api/format', {'latex': r'\frac{1}{'})) == (422, 'MATH_CONVERSION_FAILED')
    assert err_code(request(server, 'POST', '/api/format', {'latex': 'x' * 2001})) == (413, 'LATEX_TOO_LONG')
    assert err_code(request(server, 'POST', '/api/format', {'latex': ''})) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/format', {'latex': 'x', 'extra': 1})) == (400, 'BAD_REQUEST')


def test_math_failure_on_read(server):
    _, reader, _ = server
    reader.reads = [{'scale': s, 'latex': r'\frac{1}{', 'lp_mean': GOOD} for s in config.SCALES]
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64()})) == (422, 'MATH_CONVERSION_FAILED')


def test_model_error(server):
    _, reader, _ = server
    reader.raise_exc = RuntimeError('boom')
    status, body, _ = request(server, 'POST', '/api/read', {'image_base64': png_b64()})
    assert (status, body['error']['code']) == (500, 'RECOGNITION_FAILED')
    assert 'boom' not in json.dumps(body)


def test_empty_reading(server):
    _, reader, _ = server
    reader.reads = [{'scale': s, 'latex': '', 'lp_mean': -1.0} for s in config.SCALES]
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64()})) == (422, 'NO_READING')


def test_not_ready(server):
    _, _, svc = server
    svc.model_problems = ['weights.pth is missing']
    st = request(server, 'GET', '/api/status')[1]
    assert st['ready'] is False and st['model_available'] is False and 'setup' in st['message'].lower()
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64()})) == (503, 'NOT_READY')
    # formatting alternatives does not need the model
    assert request(server, 'POST', '/api/format', {'latex': 'x'})[0] == 200


def test_busy(server):
    _, reader, _ = server
    reader.gate = threading.Event()
    results = {}

    def first():
        results['first'] = request(server, 'POST', '/api/read', {'image_base64': png_b64()})[0]
    t = threading.Thread(target=first)
    t.start()
    deadline = time.time() + 5
    calls = reader.calls
    while reader.calls == calls and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    second = request(server, 'POST', '/api/read', {'image_base64': png_b64()})
    reader.gate.set()
    t.join(10)
    assert err_code(second) == (409, 'BUSY')
    assert results['first'] == 200


def test_bad_requests(server):
    assert err_code(request(server, 'POST', '/api/read', raw=b'{not json')) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/read', raw=b'[]')) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/read', {})) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': 'data:image/png;base64,' + png_b64()})) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64(), 'path': 'C:/x'})) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64(), 'filename': 5})) == (400, 'BAD_REQUEST')
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': base64.b64encode(b'hello').decode()}))[0] == 422
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64(blank=True)})) == (422, 'INVALID_IMAGE')
    assert err_code(request(server, 'POST', '/api/read', {'image_base64': png_b64()},
                            headers={'Content-Type': 'text/plain'})) == (415, 'UNSUPPORTED_MEDIA_TYPE')
    assert err_code(request(server, 'POST', '/api/nope', {}))[0] == 404
    assert err_code(request(server, 'GET', '/api/nope'))[0] == 404


def test_oversized_body_gets_413(server):
    httpd = server[0]
    port = httpd.server_address[1]
    body = b'{"image_base64":"' + b'A' * (config.MAX_BODY_BYTES + 1) + b'"}'
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    conn.request('POST', '/api/read', body=body, headers={'Host': f'127.0.0.1:{port}', 'Content-Type': 'application/json'})
    resp = conn.getresponse()
    assert resp.status == 413 and json.loads(resp.read())['error']['code'] == 'IMAGE_TOO_LARGE'
    conn.close()


def test_huge_declared_length_is_not_read(server):
    httpd = server[0]
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.putrequest('POST', '/api/read', skip_host=True)
    conn.putheader('Host', f'127.0.0.1:{port}')
    conn.putheader('Content-Type', 'application/json')
    conn.putheader('Content-Length', str(app_module.DRAIN_LIMIT + 1))
    conn.endheaders()
    resp = conn.getresponse()   # answered immediately; the server never waits for the body
    assert resp.status == 413 and resp.getheader('Connection') == 'close'
    conn.close()


def test_host_and_origin_checks(server):
    port = server[0].server_address[1]
    assert err_code(request(server, 'GET', '/api/status', headers={'Host': f'evil.example:{port}'})) == (403, 'FORBIDDEN_HOST')
    assert err_code(request(server, 'GET', '/api/status', headers={'Host': 'localhost:1'})) == (403, 'FORBIDDEN_HOST')
    assert request(server, 'GET', '/api/status', headers={'Host': f'localhost:{port}'})[0] == 200
    assert request(server, 'GET', '/', headers={'Host': f'rebind.attacker.test:{port}'})[0] == 403
    bad_origin = {'Origin': 'http://evil.example'}
    assert err_code(request(server, 'POST', '/api/format', {'latex': 'x'}, headers=bad_origin)) == (403, 'FORBIDDEN_ORIGIN')
    assert err_code(request(server, 'POST', '/api/format', {'latex': 'x'}, headers={'Origin': 'null'})) == (403, 'FORBIDDEN_ORIGIN')
    assert err_code(request(server, 'POST', '/api/format', {'latex': 'x'},
                            headers={'Sec-Fetch-Site': 'cross-site'})) == (403, 'FORBIDDEN_ORIGIN')
    status, body, resp = request(server, 'OPTIONS', '/api/read', headers={'Origin': 'http://evil.example',
                                                                          'Access-Control-Request-Method': 'POST'})
    assert status == 405 and resp.getheader('Access-Control-Allow-Origin') is None


def test_static_files_and_traversal(server):
    status, body, resp = request(server, 'GET', '/')
    assert status == 200 and b'Say the Math' in body and resp.getheader('Content-Type').startswith('text/html')
    assert request(server, 'GET', '/style.css')[0] == 200
    for p in ('/../app.py', '/%2e%2e/app.py', '/..\\app.py', '/.hidden', '/missing.js', '/../models/weights.pth'):
        assert request(server, 'GET', p)[0] == 404, p
