"""Real exported PDFs/crops; explicit test doubles only in the cache/limit unit cases.

No frozen evaluation records are rewritten. Runtime never imports these records.
"""
import base64
import copy
import hashlib
import http.client
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import app
from recognition import config, errors, netguard
from recognition.pdfnav import PDFNavigation, IDLE_SECONDS
from recognition.service import ReaderService

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / 'research' / 'pdf_feasibility'
if not all((RESEARCH / name).is_file() for name in
           ('results/pdf_navigation_manifest.json', 'results/pdf_contract_examples.json')):
    pytest.skip('Optional research export fixtures are not distributed; run test_pdf_portable.py for authored PDF checks.',
                allow_module_level=True)
MANIFEST = json.loads((RESEARCH / 'results/pdf_navigation_manifest.json').read_text(encoding='utf8'))
RECORDS = json.loads((RESEARCH / 'results/pdf_contract_examples.json').read_text(encoding='utf8'))


def upload(name, **extra):
    return {'pdf_base64': base64.b64encode((RESEARCH / 'external' / name).read_bytes()).decode(), 'filename': name, **extra}


@pytest.fixture(scope='module')
def live():
    service = ReaderService()
    server = app.make_server(0, service)
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()
    service.close()


def post(server, route, body, headers=None):
    port = server.server_address[1]
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=240)
    conn.request('POST', route, json.dumps(body), {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{port}', **(headers or {})})
    reply = conn.getresponse()
    result = reply.status, json.loads(reply.read())
    conn.close()
    return result


@pytest.mark.parametrize('exported', MANIFEST['documents'], ids=lambda d:d['filename'])
def test_every_page_and_all_96_exported_crops(live, exported):
    status, doc = post(live, '/api/pdf/open', upload(exported['filename']))
    assert status == 200, doc
    try:
        assert len(doc['pages']) == doc['page_count'] == exported['page_count']
        assert [p['index'] for p in doc['pages']] == list(range(doc['page_count']))
        assert all(p['printed_label'] is None for p in doc['pages'])  # Actual sample has no /PageLabels.
        for saved_page in exported['pages']:
            current = doc['pages'][saved_page['index']]
            assert (current['status'],current['candidate_count']) == (saved_page['status'],saved_page['candidate_count'])
            if current['status'] == 'no_candidates':
                assert current['announcement'].startswith('No candidates detected.')
            if current['status'] == 'unsupported':
                assert current['announcement'].startswith('Unsupported page.')
            assert 'no equations' not in current['announcement'].lower()
        for saved in exported['equations']:
            candidate = next(e for e in doc['equations'] if e['order'] == saved['order'])
            for key in ('page_index','bbox_pt','number','context_before','layout'):
                assert candidate[key] == saved[key], (saved['id'],key)
            assert candidate['region_completeness']['state'] == 'unknown'
            assert candidate['recognition']['status'] == ('not_attempted' if saved['layout']=='multi-line' else 'pending')
            status, crop = post(live, '/api/pdf/crop', {'document_id':doc['document_id'],'equation_id':candidate['id']})
            assert status == 200
            assert crop['crop_sha256'] == saved['crop_sha256']
            assert hashlib.sha256(base64.b64decode(crop['image_base64'])).hexdigest() == saved['crop_sha256']
        assert 'source_comparison' not in json.dumps(doc)
    finally:
        assert post(live,'/api/pdf/close',{'document_id':doc['document_id']}) == (200,{'closed':True})


def test_real_fragment_confidence_and_settings_cache_invalidation(live, monkeypatch):
    _, doc = post(live, '/api/pdf/open', upload('arxiv_2610.15393.pdf'))
    body = {'document_id':doc['document_id'],'equation_id':'e-16-39'}
    actual_read, calls = live.service.read, []
    def counted(payload):
        calls.append(1)
        return actual_read(payload)  # Actual model and converter; only count calls.
    monkeypatch.setattr(live.service,'read',counted)
    try:
        status, first = post(live,'/api/pdf/read',body)
        assert status == 200, first
        assert first['latex'] == r'd^{2}|_{1}+d^{2}|_{2}.'
        assert first['confidence']['level'] == 'higher'
        assert first['region_completeness']['state'] == 'unknown'
        assert first['from_cache'] is False
        _, second = post(live,'/api/pdf/read',body)
        assert second['from_cache'] is True and len(calls) == 1
        with monkeypatch.context() as change:
            change.setattr(config,'LOGPROB_THRESHOLD',0.0)
            status, changed = post(live,'/api/pdf/read',body)
            assert status == 200 and changed['from_cache'] is False and len(calls) == 2
            assert changed['settings_fingerprint'] != first['settings_fingerprint']
            assert changed['confidence']['level'] == 'uncertain'
            assert changed['region_completeness']['state'] == 'unknown'
        # Different PDF bytes and a new session must not reuse the previous session.
        post(live,'/api/pdf/close',{'document_id':doc['document_id']})
        changed_input = upload('arxiv_2610.15393.pdf')
        changed_input['pdf_base64'] = base64.b64encode(base64.b64decode(changed_input['pdf_base64']) + b'\n% cache-input-regression\n').decode()
        _, other = post(live,'/api/pdf/open',changed_input)
        body['document_id'] = other['document_id']
        _, fresh = post(live,'/api/pdf/read',body)
        assert fresh['from_cache'] is False and len(calls) == 3
        assert 'source_comparison_diagnostic' not in fresh and 'source_evidence' not in fresh
    finally:
        post(live,'/api/pdf/close',{'document_id':body['document_id']})


def test_real_conversion_failure_and_multiline_are_not_cached_or_fabricated(live, monkeypatch):
    _, doc = post(live,'/api/pdf/open',upload('arxiv_2610.15393.pdf'))
    original, calls = live.service.read, []
    def counted(payload):
        calls.append(1)
        return original(payload)
    monkeypatch.setattr(live.service,'read',counted)
    try:
        multiline = next(e for e in doc['equations'] if e['id']=='e-16-38')
        status, error = post(live,'/api/pdf/read',{'document_id':doc['document_id'],'equation_id':multiline['id']})
        assert status == 422 and error['error']['code'] == 'UNSUPPORTED_LAYOUT' and not calls
        post(live,'/api/pdf/close',{'document_id':doc['document_id']})
        _, doc = post(live,'/api/pdf/open',upload('arxiv_2610.19250.pdf'))
        body = {'document_id':doc['document_id'],'equation_id':'e-4-12'}
        for _ in range(2):
            status, error = post(live,'/api/pdf/read',body)
            assert status == 422 and error['error']['code'] == 'MATH_CONVERSION_FAILED'
            assert 'latex' not in error and 'confidence' not in error
        assert len(calls) == 2  # Actual failures reattempted, never a cached fake result.
    finally:
        post(live,'/api/pdf/close',{'document_id':doc['document_id']})


def test_closed_unknown_and_cross_origin(live):
    assert post(live,'/api/pdf/read',{'document_id':'closed','equation_id':'e-0-0'})[1]['error']['code']=='UNKNOWN_DOCUMENT'
    status, error = post(live,'/api/pdf/open',{},headers={'Origin':'https://example.com'})
    assert status == 403 and error['error']['code']=='FORBIDDEN_ORIGIN'
    for body in ({}, {'pdf_base64':'not base64'}, {'pdf_base64':base64.b64encode(b'not a PDF').decode()}):
        assert post(live,'/api/pdf/open',body)[0] in (400,422)


def test_cancel_open_drops_late_session(monkeypatch):
    import recognition.pdfnav as module
    nav = PDFNavigation(None)
    started, release = threading.Event(), threading.Event()
    def held(data, filename):
        started.set(); release.wait(5)
        return {'page_count':1,'pages':[],'equations':[]}, {}  # Explicit parser double for race only.
    monkeypatch.setattr(module,'_manifest',held)
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(nav.open, {'pdf_base64':base64.b64encode(b'%PDF- test-double').decode(),'open_token':'race'})
        assert started.wait(2)
        nav.close({'open_token':'race'})
        release.set()
        with pytest.raises(errors.ApiError) as caught:
            pending.result()
        assert caught.value.code == 'PDF_CANCELLED' and not nav.documents


def test_expiry_is_not_dependent_on_another_request():
    now = [0]
    nav = PDFNavigation(None,clock=lambda:now[0])
    nav.documents['test'] = {'touched':0,'bytes':b'private'}
    now[0] = IDLE_SECONDS + 1
    nav.expire()
    assert not nav.documents


def test_settings_change_during_read_is_not_cached(monkeypatch):
    from collections import OrderedDict
    class ChangingReader:
        def _require(self, model=True):
            pass
        def read(self, payload):
            monkeypatch.setattr(config,'LOGPROB_THRESHOLD',0.0)
            return {'latex':'test-double'}
    nav=PDFNavigation(ChangingReader())
    nav.documents['doc']={'touched':nav.clock(),'manifest':{'equations':[{'id':'e','layout':'single-line'}]},
                          'cache':OrderedDict(),'cache_size':0}
    monkeypatch.setattr(nav,'_render',lambda *args:b'exact test bytes')
    monkeypatch.setattr(nav,'fingerprint',lambda:str(config.LOGPROB_THRESHOLD))
    with pytest.raises(errors.ApiError) as caught:
        nav.read({'document_id':'doc','equation_id':'e'})
    assert caught.value.code=='SETTINGS_CHANGED' and not nav.documents['doc']['cache']


def test_fingerprint_invalidates_for_settings_assets_and_code(tmp_path,monkeypatch):
    from recognition import pdfnav
    (tmp_path/'recognition').mkdir()
    (tmp_path/'models').mkdir()
    for name in pdfnav._CODE_FILES:
        (tmp_path/'recognition'/name).write_text('code-v1')
    for name in ('math_worker.mjs','package-lock.json'):
        (tmp_path/name).write_text('v1')
    checkpoints = {}
    for name in config.CHECKPOINTS:
        data=b'unit-test-checkpoint'
        (tmp_path/'models'/name).write_bytes(data)
        checkpoints[name]={'sha256':hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(config,'ROOT',tmp_path)
    monkeypatch.setattr(config,'MODELS_DIR',tmp_path/'models')
    monkeypatch.setattr(config,'CHECKPOINTS',checkpoints)
    nav=PDFNavigation(None)
    first=nav.fingerprint()
    with monkeypatch.context() as change:
        change.setattr(config,'SCALES',(1.0,0.7,0.5))
        assert nav.fingerprint()!=first
    (tmp_path/'recognition/model.py').write_text('changed-code-v2')
    changed=nav.fingerprint()
    assert changed!=first
    (tmp_path/'models/weights.pth').write_bytes(b'changed weights')
    with pytest.raises(errors.ApiError) as caught:
        nav.fingerprint()
    assert caught.value.code=='NOT_READY'


def test_no_external_runtime_attempts(live):
    assert netguard.installed()
    assert not netguard.blocked_attempts
    assert live.service.worker.ping()['blocked_connections']==0
