"""Actual pix2tex inference through the real HTTP server, with outbound networking refused.

Uses newly authored equations rendered by make_images.py. These are smoke tests of the pipeline,
not an accuracy measurement: the assertions check structure and features that the higher-confidence
outputs of this pinned model produced on these images during development, not a correctness rate.
"""
import base64
import http.client
import json
import shutil
import threading
from pathlib import Path

import pytest

import app as app_module
import make_images
from recognition import config, netguard
from recognition.model import Pix2TexReader, checkpoint_problems
from recognition.service import ReaderService
from treecheck import check_tree

pytestmark = pytest.mark.real_model
BLOCKED_BEFORE = {'n': 0}  # attempts recorded by other test modules before this one starts
if checkpoint_problems(verify_hash=False):
    pytest.skip('model not set up; run setup_app.py', allow_module_level=True)


@pytest.fixture(scope='module')
def images(tmp_path_factory):
    d = tmp_path_factory.mktemp('authored')
    make_images.main(d)
    return d


@pytest.fixture(scope='module')
def server():
    BLOCKED_BEFORE['n'] = len(netguard.blocked_attempts)
    svc = ReaderService()
    assert svc.status()['ready'], svc.status()
    httpd = app_module.make_server(0, svc)
    threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True).start()
    yield httpd, svc
    httpd.shutdown()
    httpd.server_close()
    svc.close()


def post(httpd, path, obj):
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
    conn.request('POST', path, body=json.dumps(obj).encode(), headers={
        'Host': f'127.0.0.1:{port}', 'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{port}'})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


def read_file(server, path):
    return post(server[0], '/api/read', {'image_base64': base64.b64encode(Path(path).read_bytes()).decode(),
                                         'filename': Path(path).name})


def test_fraction(server, images):
    status, body = read_file(server, images / 'fraction_cm.png')
    assert status == 200, body
    check_tree(body)
    kinds = [n['kind'] for n in body['nodes']]
    assert 'fraction' in kinds and 'numerator' in kinds and 'denominator' in kinds
    assert body['confidence']['total_reads'] == 3
    assert 1 <= len(body['alternatives']) <= 3 and sum(a['count'] for a in body['alternatives']) == 3
    assert body['alternatives'][0]['latex'] == body['latex']


def test_root_and_powers(server, images):
    status, body = read_file(server, images / 'sqrt_powers_cm.png')
    assert status == 200
    kinds = [n['kind'] for n in body['nodes']]
    assert 'square_root' in kinds and 'radicand' in kinds and 'exponent' in kinds


def test_integral(server, images):
    status, body = read_file(server, images / 'integral_cm.png')
    assert status == 200
    kinds = [n['kind'] for n in body['nodes']]
    assert 'bounded_operator' in kinds and 'lower_bound' in kinds and 'upper_bound' in kinds
    assert body['speech'].startswith('the integral from')


def test_transparent_and_jpeg_variants(server, images):
    for name in ('fraction_transparent.png', 'fraction_cm.jpg'):
        status, body = read_file(server, images / name)
        assert status == 200 and 'fraction' in [n['kind'] for n in body['nodes']]


def test_alternative_formatting_uses_model_output(server, images):
    status, body = read_file(server, images / 'cube_root_cm.png')
    assert status == 200
    for alt in body['alternatives']:
        s, f = post(server[0], '/api/format', {'latex': alt['latex']})
        assert s in (200, 422)
        if s == 200:
            check_tree(f)
            assert 'confidence' not in f


def test_no_network_used(server):
    assert netguard.installed()
    assert len(netguard.blocked_attempts) == BLOCKED_BEFORE['n']
    assert server[1].worker.ping()['blocked_connections'] == 0


def test_missing_model_reports_not_ready(tmp_path):
    svc = ReaderService(reader=Pix2TexReader(models_dir=tmp_path))
    st = svc.status()
    assert st['ready'] is False and st['model_available'] is False
    assert 'weights.pth is missing' in st['message'] and str(tmp_path) not in st['message']
    svc.close()


def test_tampered_checkpoint_is_refused(tmp_path):
    for name in config.CHECKPOINTS:
        shutil.copy(config.MODELS_DIR / name, tmp_path / name)
    with open(tmp_path / 'image_resizer.pth', 'r+b') as f:
        f.seek(1000)
        f.write(b'\x00\x01\x02\x03')
    svc = ReaderService(reader=Pix2TexReader(models_dir=tmp_path))
    st = svc.status()
    assert st['ready'] is False and 'SHA256' in st['message']
    svc.close()
