"""Bounded execution and cancellation with the real model, real HTTP server and known slow crops.

Known slow example: arxiv_2610.01958-p13-e117 (exceeded the browser's 180 s wait in Codex's integration run).
These tests time the stop itself, check that the next request is served with its own result (no stale reading,
no lasting BUSY), and that the stop hooks leave readings unchanged.
"""
import base64
import http.client
import json
import socket
import threading
import time
from pathlib import Path

import pytest

import app as app_module
import make_images
from recognition import config
from recognition.jobs import CLIENT_DISCONNECTED, TIME_LIMIT
from recognition.model import checkpoint_problems
from recognition.service import ReaderService

ROOT = Path(__file__).resolve().parents[2]
CROPS = ROOT / 'research' / 'pdf_feasibility' / 'results' / 'candidate_crops'
SLOW = CROPS / 'arxiv_2610.01958-p13-e117.png'
PDF = ROOT / 'research' / 'pdf_feasibility' / 'external' / 'arxiv_2610.01958.pdf'
pytestmark = pytest.mark.real_model
if checkpoint_problems(verify_hash=False) or not SLOW.exists():
    pytest.skip('model or slow research crop not available', allow_module_level=True)
RESULTS = {}


@pytest.fixture(scope='module')
def images(tmp_path_factory):
    d = tmp_path_factory.mktemp('authored')
    make_images.main(d)
    return d


@pytest.fixture(scope='module')
def server():
    svc = ReaderService()
    svc.warm_up()
    httpd = app_module.make_server(0, svc)
    threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
    yield httpd, svc
    httpd.shutdown()
    httpd.server_close()
    svc.close()
    out = ROOT / 'test-output' / 'cancellation_real.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=1), encoding='utf-8')


def headers(port):
    return {'Host': f'127.0.0.1:{port}', 'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json'}


def post(httpd, path, body, timeout=300):
    port = httpd.server_address[1]
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    c.request('POST', path, body=json.dumps(body).encode(), headers=headers(port))
    r = c.getresponse()
    out = (r.status, json.loads(r.read()))
    c.close()
    return out


def raw_post(httpd, path, body):
    port = httpd.server_address[1]
    data = json.dumps(body).encode()
    s = socket.create_connection(('127.0.0.1', port))
    head = ''.join(f'{k}: {v}\r\n' for k, v in headers(port).items())
    s.sendall(f'POST {path} HTTP/1.1\r\n{head}Content-Length: {len(data)}\r\n\r\n'.encode() + data)
    return s


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def wait_busy(svc, limit=30):
    end = time.monotonic() + limit
    while svc._current_token is None and time.monotonic() < end:
        time.sleep(0.02)
    return svc._current_token is not None


def test_readings_unchanged_by_stop_hooks(server, images):
    httpd, _ = server
    before = json.loads((ROOT / 'test-output' / 'real_inference.json').read_text(encoding='utf-8'))['results'] \
        if (ROOT / 'test-output' / 'real_inference.json').exists() else []
    expected = {r['file']: (r['latex'], r['confidence']['level'], r['confidence']['agreeing_reads']) for r in before if 'latex' in r}
    checked = 0
    for name in ('fraction_cm.png', 'integral_cm.png', 'cube_root_cm.png', 'relation_stix.png'):
        status, body = post(httpd, '/api/read', {'image_base64': b64(images / name)})
        assert status == 200
        if name in expected:
            assert (body['latex'], body['confidence']['level'], body['confidence']['agreeing_reads']) == expected[name]
            checked += 1
    RESULTS['readings_compared_with_pre_change_run'] = checked


def test_real_disconnect_stops_model_and_next_read_is_fresh(server, images):
    httpd, svc = server
    s = raw_post(httpd, '/api/read', {'image_base64': b64(SLOW)})
    assert wait_busy(svc)
    time.sleep(3.0)
    t_close = time.monotonic()
    s.close()                                                  # browser Cancel / choosing another image
    status, body = post(httpd, '/api/read', {'image_base64': b64(images / 'fraction_cm.png')})
    total = time.monotonic() - t_close
    assert status == 200 and body['latex'] == r'\frac{3y-5}{2y+7}'  # the new image's own reading
    assert svc.last_stop['reason'] == CLIENT_DISCONNECTED
    RESULTS['image_disconnect'] = {'stop': svc.last_stop, 'next_read_total_s': round(total, 2),
                                   'next_read_model_ms': body['elapsed_ms']}
    assert svc.last_stop['unwind_s'] < 2.0
    assert total < config.STOP_WAIT_S + body['elapsed_ms'] / 1000 + 2


def test_real_time_limit_on_known_slow_crop(server, images, monkeypatch):
    httpd, svc = server
    monkeypatch.setattr(config, 'READ_TIME_LIMIT_S', 8.0)
    t0 = time.monotonic()
    status, body = post(httpd, '/api/read', {'image_base64': b64(SLOW)})
    took = time.monotonic() - t0
    assert status == 504 and body['error']['code'] == 'RECOGNITION_TIMEOUT'
    assert 'latex' not in body and 'confidence' not in body
    assert svc.last_stop['reason'] == TIME_LIMIT
    RESULTS['image_time_limit_8s'] = {'response_s': round(took, 2), 'stop': svc.last_stop}
    assert took < 8.0 + 2.0
    monkeypatch.setattr(config, 'READ_TIME_LIMIT_S', 120.0)
    status, body = post(httpd, '/api/read', {'image_base64': b64(images / 'integral_cm.png')})
    assert status == 200 and body['latex'].startswith(r'\int_{1}^{4}')


def test_real_pdf_read_cancel_then_other_candidate(server):
    httpd, svc = server
    status, doc = post(httpd, '/api/pdf/open', {'pdf_base64': b64(PDF), 'filename': 'arxiv_2610.01958.pdf'})
    assert status == 200, doc
    did = doc['document_id']
    try:
        slow = next(e for e in doc['equations'] if e['page_index'] == 13 and e['order'] == 117)
        other = next(e for e in doc['equations'] if e['page_index'] == 13 and e['order'] == 118)
        s = raw_post(httpd, '/api/pdf/read', {'document_id': did, 'equation_id': slow['id']})
        assert wait_busy(svc)
        time.sleep(3.0)
        t_close = time.monotonic()
        s.close()
        status, body = post(httpd, '/api/pdf/read', {'document_id': did, 'equation_id': other['id']})
        total = time.monotonic() - t_close
        assert status == 200 and body['equation_id'] == other['id'] and body['from_cache'] is False
        assert body['region_completeness']['state'] == 'unknown'
        assert svc.last_stop['reason'] == CLIENT_DISCONNECTED
        RESULTS['pdf_read_disconnect'] = {'stop': svc.last_stop, 'next_read_total_s': round(total, 2),
                                          'next_latex': body['latex']}
        # Only the completed reading is cached; the cancelled candidate left no entry that could be replayed later.
        assert len(svc_cache_keys(httpd, did)) == 1
    finally:
        post(httpd, '/api/pdf/close', {'document_id': did})


def svc_cache_keys(httpd, did):
    doc = httpd.pdf.documents.get(did)
    return list(doc['cache']) if doc else []


def recv_status(sock, limit=60):
    sock.settimeout(limit)
    sep = b'\r\n\r\n'
    data = b''
    while sep not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    head, _, rest = data.partition(sep)
    lines = head.split(b'\r\n')
    length = int([l.split(b':')[1] for l in lines if l.lower().startswith(b'content-length')][0])
    while len(rest) < length:
        rest += sock.recv(65536)
    return int(lines[0].split()[1]), json.loads(rest[:length])


def wait_open_job(httpd, limit=30):
    end = time.monotonic() + limit
    while httpd.pdf._open_job is None and time.monotonic() < end:
        time.sleep(0.02)
    return httpd.pdf._open_job is not None


def test_real_pdf_open_close_token_stops_discovery(server):
    """Explicit close by open_token while the client stays connected: discovery itself must stop."""
    httpd, _ = server
    wiki = ROOT / 'research' / 'pdf_feasibility' / 'external' / 'wiki_Pythagorean_theorem.pdf'
    if not wiki.exists():
        pytest.skip('slow research PDF not available')
    s = raw_post(httpd, '/api/pdf/open', {'pdf_base64': b64(wiki), 'filename': 'w.pdf', 'open_token': 'close-me'})
    assert wait_open_job(httpd)
    time.sleep(2.0)
    t_close = time.monotonic()
    post(httpd, '/api/pdf/close', {'open_token': 'close-me'})
    status, body = recv_status(s)
    took = time.monotonic() - t_close
    s.close()
    assert status == 409 and body['error']['code'] == 'PDF_CANCELLED'
    assert httpd.pdf.last_open_stop['reason'] == 'closed' and not httpd.pdf.documents
    RESULTS['pdf_open_close_token'] = {'response_after_close_s': round(took, 2), 'stop': httpd.pdf.last_open_stop}
    assert took < config.STOP_WAIT_S


def test_real_pdf_open_disconnect_then_open_another(server):
    httpd, _ = server
    wiki = ROOT / 'research' / 'pdf_feasibility' / 'external' / 'wiki_Pythagorean_theorem.pdf'
    if not wiki.exists():
        pytest.skip('slow research PDF not available')
    s = raw_post(httpd, '/api/pdf/open', {'pdf_base64': b64(wiki), 'filename': 'w.pdf', 'open_token': 'drop-me'})
    assert wait_open_job(httpd)
    time.sleep(2.0)
    t_close = time.monotonic()
    s.close()                                     # browser abort; the frontend also posts close(open_token)
    status, doc = post(httpd, '/api/pdf/open', {'pdf_base64': b64(PDF), 'filename': 'a.pdf'})
    total = time.monotonic() - t_close
    assert status == 200 and doc['page_count'] == 34
    assert httpd.pdf.last_open_stop['reason'] == CLIENT_DISCONNECTED
    RESULTS['pdf_open_disconnect'] = {'stop': httpd.pdf.last_open_stop, 'next_open_total_s': round(total, 2)}
    assert len(httpd.pdf.documents) == 1          # the cancelled discovery left no session behind
    post(httpd, '/api/pdf/close', {'document_id': doc['document_id']})
