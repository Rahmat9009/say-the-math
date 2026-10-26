"""Experimental in-memory PDF navigation. No research data or source comparison at runtime.

Discovery uses a frozen glyph-layout heuristic, not a completeness test. PDFium access
is serialized (its API is not thread safe). Only a requested candidate is rendered/read.
"""
import base64
import binascii
import copy
import hashlib
import importlib.metadata as metadata
import importlib.util
import io
import json
import math
import logging
import secrets
import sys
import threading
import time
from collections import OrderedDict

from . import config, errors
from .jobs import CLOSED, TIME_LIMIT, CancelToken, RecognitionStopped, current as current_job, use as use_job

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_BODY = ((MAX_PDF_BYTES + 2) // 3) * 4 + 4096
MAX_PAGES = 500
MAX_DOCUMENTS = 2
MAX_CANDIDATES = 2000
MAX_PAGE_GLYPHS = 50000
MAX_TOTAL_GLYPHS = 2000000
MAX_RENDER_PIXELS = 16000000
IDLE_SECONDS = 15 * 60
CACHE_ITEMS = 24
CACHE_BYTES = 12 * 1024 * 1024
SCALE, PAD = 2.0, 4
REGION = {'state': 'unknown', 'basis': 'No completeness test exists. Automatic regions can omit parts of an equation, even with a higher-confidence reading.'}
ANNOUNCEMENTS = {
    'candidates': 'Automatic candidates may be incomplete, and detection can miss equations.',
    'no_candidates': 'No candidates detected. Detection can miss equations on this page.',
    'unsupported': 'Unsupported page. Equations may be drawn as graphics, scanned, or not detected.',
}
_PDFIUM_LOCK = threading.Lock()
_CODE_FILES = ('model.py', 'normalize.py', 'selection.py', 'images.py', 'service.py', 'mathconv.py', 'pdfnav.py')


def token_key(payload):
    value = payload.get('open_token') if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def availability():
    missing = [p for p in ('pdfplumber', 'pdfminer', 'pypdfium2') if importlib.util.find_spec(p) is None]
    return {'available': not missing, 'message': 'Experimental PDF navigation is available.' if not missing else
            'PDF navigation needs local PDF dependencies. Run Start-Windows.cmd setup or ./start.sh setup.'}


def _payload(payload, fields):
    if not isinstance(payload, dict) or set(payload) - set(fields):
        raise errors.bad_request('Send a JSON object containing only the documented fields.')


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise errors.bad_request('A session or candidate ID is missing or invalid.')
    return value


def _too_large(message):
    return errors.ApiError(413, 'PDF_TOO_LARGE', message)


def _invalid():
    return errors.ApiError(422, 'INVALID_PDF', 'This PDF could not be opened. Choose an unencrypted, undamaged PDF.')


def _context(page, top, col):
    # Same orientation-only extraction as the validated navigation export.
    words = [w for w in page.extract_words(keep_blank_chars=False, use_text_flow=True)
             if w['bottom'] <= top + 1 and col[0] - 2 <= w['x0'] <= col[1] + 2]
    if not words:
        return ''
    last = max(w['top'] for w in words)
    lines = [w for w in words if w['top'] >= last - 14]
    return ' '.join(w['text'] for w in sorted(lines, key=lambda w: (round(w['top']), w['x0'])))[-120:]


def _manifest(data, filename):
    token = current_job()
    check = token.check if token is not None else (lambda: None)
    import pdfplumber
    from .pdf_detector import detect_page
    # Parser diagnostics can quote document contents. Keep errors in our envelope.
    logging.getLogger('pdfminer').setLevel(logging.CRITICAL)

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if pdf.doc.encryption:
            raise _invalid()
        count = len(pdf.pages)
        if not count or count > MAX_PAGES:
            raise _too_large('Choose a PDF with between 1 and 500 pages.')
        labels = None
        if 'PageLabels' in pdf.doc.catalog:
            try:
                labels = list(pdf.doc.get_page_labels())
            except Exception:
                labels = None  # Never fabricate a printed label from a physical index.
        left, right, total, failed = math.inf, -math.inf, 0, set()
        for index, page in enumerate(pdf.pages):
            check()  # cancellation / time limit between pages
            try:
                chars = [c for c in page.chars if c['text'].strip()]
            except Exception:
                failed.add(index)
                page.close()
                continue
            total += len(chars)
            if len(chars) > MAX_PAGE_GLYPHS or total > MAX_TOTAL_GLYPHS:
                raise _too_large('This PDF is too complex for experimental discovery. Choose a smaller document.')
            if chars:
                left = min(left, min(c['x0'] for c in chars))
                right = max(right, max(c['x1'] for c in chars))
            page.close()
        col = (left, right) if left != math.inf else None
        pages, equations, raw_boxes = [], [], {}
        for index, page in enumerate(pdf.pages):
            check()
            printed = str(labels[index])[:100] if labels and index < len(labels) else None
            start = len(equations)
            try:
                if index in failed:
                    raise ValueError('unavailable text')
                found = detect_page(page, 'combined', col)
                chars = [c for c in page.chars if c['text'].strip()]
                reasons = []
                if found['unsupported']:
                    reasons.append('Vector drawings are not interpreted as equations; math may be drawn as paths.')
                if not chars:
                    reasons.append('No usable text layer; scanned or graphics-only math is unsupported.')
                candidates = sorted(found['candidates'], key=lambda c: (c['top'], c['x0']))
                state = 'candidates' if candidates else ('unsupported' if reasons else 'no_candidates')
                local_col = (min((c['x0'] for c in chars), default=0), max((c['x1'] for c in chars), default=page.width))
                for candidate in candidates:
                    if len(equations) >= MAX_CANDIDATES:
                        raise _too_large('This PDF has too many candidate regions. Choose a smaller document.')
                    order = len(equations)
                    eid = f'e-{index}-{order}'
                    box = [candidate[k] for k in ('x0', 'top', 'x1', 'bottom')]
                    if not all(math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
                        continue
                    layout = candidate['layout']
                    equations.append({'id': eid, 'page_index': index, 'printed_label': printed, 'order': order,
                                      'bbox_pt': [round(v, 1) for v in box], 'number': candidate['number'],
                                      'context_before': _context(page, candidate['top'], local_col), 'layout': layout,
                                      'region_completeness': dict(REGION), 'provenance': 'glyph_layout',
                                      'recognition': {'status': 'pending'} if layout == 'single-line' else
                                      {'status': 'not_attempted', 'reason': 'Multi-line candidate: recognition not attempted; outside the tested single-equation scope.'}})
                    raw_boxes[eid] = box  # Retain unrounded geometry for byte-identical export rendering.
                if state == 'candidates' and len(equations) == start:
                    state = 'unsupported'
                    reasons.append('No usable candidate geometry could be extracted.')
                pages.append({'index': index, 'printed_label': printed, 'status': state, 'reasons': reasons,
                              'candidate_count': len(equations) - start, 'announcement': ANNOUNCEMENTS[state]})
            except (errors.ApiError, RecognitionStopped):
                raise
            except Exception:
                # A page-level extraction failure must not silently remove a page.
                for item in equations[start:]:
                    raw_boxes.pop(item['id'], None)
                del equations[start:]
                pages.append({'index': index, 'printed_label': printed, 'status': 'unsupported',
                              'reasons': ['Text/layout extraction failed for this page.'], 'candidate_count': 0,
                              'announcement': ANNOUNCEMENTS['unsupported']})
            finally:
                page.close()
        return {'filename': filename, 'page_count': count, 'pages': pages, 'equations': equations}, raw_boxes


class PDFNavigation:
    def __init__(self, reader_service, clock=time.monotonic):
        self.reader = reader_service
        self.clock = clock
        self.documents = OrderedDict()
        self.lock = threading.RLock()
        self.open_lock = threading.Lock()
        self.read_lock = threading.Lock()
        self._fingerprint_files = {}
        self.cancelled_opens = OrderedDict()
        self.open_tokens = {}  # open_token -> CancelToken of the discovery running for it
        self._open_job = None  # CancelToken of the running discovery
        self.last_open_stop = None

    def _prune(self):
        for did in list(self.documents):
            if self.clock() - self.documents[did]['touched'] >= IDLE_SECONDS:
                del self.documents[did]
        for token in list(self.cancelled_opens):
            if self.clock() - self.cancelled_opens[token] >= IDLE_SECONDS:
                del self.cancelled_opens[token]

    def expire(self):
        with self.lock:
            self._prune()

    def open(self, payload, job=None):
        """job: jobs.CancelToken; defaults to the current job's token, else the PDF discovery time limit.
        (`token` below is the client's open_token string, unrelated to the cancel token.)"""
        job = job or current_job() or CancelToken(config.PDF_OPEN_TIME_LIMIT_S)
        _payload(payload, ('pdf_base64', 'filename', 'open_token'))
        token = payload.get('open_token')
        if token is not None:
            _identifier(token)
        if not availability()['available']:
            raise errors.not_ready(availability()['message'])
        value, filename = payload.get('pdf_base64'), payload.get('filename', 'document.pdf')
        if not isinstance(filename, str) or not filename or len(filename) > 255:
            raise errors.bad_request('filename must be a short display name.')
        filename = filename.replace('\\', '/').split('/')[-1] or 'document.pdf'
        if not isinstance(value, str) or not value or value.startswith('data:'):
            raise errors.bad_request('Send pdf_base64 as raw base64 without a data URL prefix.')
        if len(value) > ((MAX_PDF_BYTES + 2) // 3) * 4:
            raise _too_large('Choose a PDF no larger than 50 MiB.')
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise errors.bad_request('pdf_base64 is not valid base64.')
        if len(data) > MAX_PDF_BYTES:
            raise _too_large('Choose a PDF no larger than 50 MiB.')
        if b'%PDF-' not in data[:1024]:
            raise _invalid()
        if not self.open_lock.acquire(blocking=False):
            running = self._open_job
            if not (running is not None and running.cancelled and self.open_lock.acquire(timeout=config.STOP_WAIT_S)):
                raise errors.ApiError(409, 'BUSY', 'PDF discovery is still running locally. Wait for it to finish, then open the PDF again.')
        try:
            with self.lock:
                if token_id := token_key(payload):
                    if token_id in self.cancelled_opens:
                        raise errors.ApiError(409, 'PDF_CANCELLED', 'PDF discovery was cancelled. Open the PDF again when ready.')
                    self.open_tokens[token_id] = job
            self._open_job = job
            try:
                with use_job(job):
                    manifest, boxes = _manifest(data, filename)
            except RecognitionStopped as stop:
                # Diagnostics only: how quickly discovery stopped after cancellation.
                self.last_open_stop = {'reason': stop.reason, 'after_s': round(job.elapsed(), 3),
                                       'unwind_s': round(time.monotonic() - (job.stopped_at or time.monotonic()), 3)}
                if stop.reason == TIME_LIMIT:
                    raise errors.ApiError(504, 'PDF_DISCOVERY_TIMEOUT',
                                          f'PDF discovery stopped after the {job.limit_s:g}-second limit. No pages were listed. '
                                          'Try a shorter PDF.') from None
                raise errors.ApiError(409, 'PDF_CANCELLED', 'PDF discovery was cancelled. Open the PDF again when ready.') from None
            except errors.ApiError:
                raise
            except Exception:
                raise _invalid() from None
            with self.lock:
                self._prune()
                if token and token in self.cancelled_opens:
                    raise errors.ApiError(409, 'PDF_CANCELLED', 'PDF discovery was cancelled. Open the PDF again when ready.')
                if len(self.documents) >= MAX_DOCUMENTS:
                    raise errors.ApiError(409, 'PDF_SESSION_LIMIT', 'Close another PDF session, or wait for its idle timeout, before opening this PDF.')
                did = 'd-' + secrets.token_hex(16)
                manifest['document_id'] = did
                self.documents[did] = {'bytes': data, 'manifest': manifest, 'boxes': boxes, 'open_token': token,
                                       'touched': self.clock(), 'cache': OrderedDict(), 'cache_size': 0}
                return copy.deepcopy(manifest)
        finally:
            self._open_job = None
            with self.lock:
                if token_key(payload):
                    self.open_tokens.pop(token_key(payload), None)
            self.open_lock.release()

    def _candidate(self, payload):
        _payload(payload, ('document_id', 'equation_id'))
        did, eid = _identifier(payload.get('document_id')), _identifier(payload.get('equation_id'))
        with self.lock:
            self._prune()
            doc = self.documents.get(did)
            if doc is None:
                raise errors.ApiError(404, 'UNKNOWN_DOCUMENT', 'This PDF session has expired or was closed. Open the PDF again.')
            candidate = next((e for e in doc['manifest']['equations'] if e['id'] == eid), None)
            if candidate is None:
                raise errors.ApiError(404, 'UNKNOWN_EQUATION', 'This candidate is not in the current PDF session.')
            doc['touched'] = self.clock()
            return doc, candidate

    def _render(self, doc, candidate):
        import pypdfium2 as pdfium
        with _PDFIUM_LOCK:
            try:
                pdf = pdfium.PdfDocument(doc['bytes'])
                try:
                    page = pdf[candidate['page_index']]
                    try:
                        w, h = page.get_size()
                        if w * h * SCALE * SCALE > MAX_RENDER_PIXELS:
                            raise _too_large('This page is too large to render within the experimental memory limit.')
                        bitmap = page.render(scale=SCALE)
                        try:
                            image = bitmap.to_pil().convert('RGB')
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                finally:
                    pdf.close()
                x0, y0, x1, y1 = doc['boxes'][candidate['id']]
                crop = image.crop((max(0, int((x0 - PAD) * SCALE)), max(0, int((y0 - PAD) * SCALE)),
                                   int((x1 + PAD) * SCALE), int((y1 + PAD) * SCALE)))
                image.close()
                out = io.BytesIO()
                crop.save(out, format='PNG')
                crop.close()
                data = out.getvalue()
                if len(data) > config.MAX_IMAGE_BYTES:
                    raise _too_large('This candidate image exceeds the image reader limit.')
                return data
            except errors.ApiError:
                raise
            except Exception:
                raise errors.ApiError(422, 'PDF_RENDER_FAILED', 'This candidate could not be rendered. Try another candidate.') from None

    def crop(self, payload):
        doc, candidate = self._candidate(payload)
        data = self._render(doc, candidate)
        return {'image_base64': base64.b64encode(data).decode(), 'crop_sha256': hashlib.sha256(data).hexdigest(),
                'region_completeness': dict(REGION)}

    def _file_hash(self, path):
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        previous = self._fingerprint_files.get(str(path))
        if previous is None or previous[0] != signature:
            previous = (signature, hashlib.sha256(path.read_bytes()).hexdigest())
            self._fingerprint_files[str(path)] = previous
        return previous[1]

    def fingerprint(self):
        # Re-evaluated before every read, including hits. Never trust a filename/ID as a cache key.
        from .model import checkpoint_problems
        if checkpoint_problems(verify_hash=True):
            raise errors.not_ready('The model checkpoints are missing or changed. Run setup again before reading.')
        settings = {'cache_version': 1, 'scales': list(config.SCALES), 'temperature': config.TEMPERATURE,
                    'threshold': config.LOGPROB_THRESHOLD, 'min_agreeing': config.MIN_AGREEING,
                    'threads': config.TORCH_THREADS, 'python': sys.version,
                    'checkpoints': {name: self._file_hash(config.MODELS_DIR / name) for name in config.CHECKPOINTS},
                    'packages': {p: metadata.version(p) for p in ('torch', 'torchvision', 'pix2tex', 'timm',
                                 'x-transformers', 'transformers', 'tokenizers', 'Pillow', 'numpy', 'albumentations', 'pdfplumber', 'pypdfium2')},
                    'code': {f: self._file_hash(config.ROOT / 'recognition' / f) for f in _CODE_FILES},
                    'worker': self._file_hash(config.ROOT / 'math_worker.mjs'),
                    'node_lock': self._file_hash(config.ROOT / 'package-lock.json')}
        return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()

    def read(self, payload, token=None):
        """token: jobs.CancelToken; defaults to the current job's token, else the recognition time limit."""
        token = token or current_job() or CancelToken(config.READ_TIME_LIMIT_S)
        doc, candidate = self._candidate(payload)
        if candidate['layout'] != 'single-line':
            raise errors.ApiError(422, 'UNSUPPORTED_LAYOUT', 'Multi-line candidate: recognition not attempted; outside the tested single-equation scope.')
        if not self.read_lock.acquire(blocking=False):
            running = getattr(self.reader, '_current_token', None)
            if not (running is not None and running.cancelled and self.read_lock.acquire(timeout=config.STOP_WAIT_S)):
                raise errors.busy()
        try:
            self.reader._require(model=True)
            data = self._render(doc, candidate)
            sha, fingerprint = hashlib.sha256(data).hexdigest(), self.fingerprint()
            key = (sha, fingerprint)
            with self.lock:
                entry = doc['cache'].get(key)
                if entry:
                    doc['cache'].move_to_end(key)
            if entry:
                reading = copy.deepcopy(entry[0])
            else:
                with use_job(token):
                    reading = self.reader.read({'image_base64': base64.b64encode(data).decode()})
                if self.fingerprint() != fingerprint:
                    raise errors.ApiError(409, 'SETTINGS_CHANGED', 'Recognition settings changed while reading. Try this candidate again.')
                size = len(json.dumps(reading).encode())
                # Failures are not cached. Closed/expired sessions never gain a late cache entry.
                with self.lock:
                    if self.documents.get(payload['document_id']) is doc and size <= CACHE_BYTES:
                        doc['cache'][key] = (copy.deepcopy(reading), size)
                        doc['cache_size'] += size
                        while len(doc['cache']) > CACHE_ITEMS or doc['cache_size'] > CACHE_BYTES:
                            _, (_, old_size) = doc['cache'].popitem(last=False)
                            doc['cache_size'] -= old_size
            return {**reading, 'document_id': payload['document_id'], 'equation_id': candidate['id'],
                    'region_completeness': dict(REGION), 'crop_sha256': sha,
                    'settings_fingerprint': fingerprint, 'from_cache': bool(entry)}
        finally:
            self.read_lock.release()

    def close(self, payload):
        _payload(payload, ('document_id', 'open_token'))
        if ('document_id' in payload) == ('open_token' in payload):
            raise errors.bad_request('Close using either document_id or open_token.')
        with self.lock:
            if 'document_id' in payload:
                self.documents.pop(_identifier(payload['document_id']), None)
            else:
                token = _identifier(payload['open_token'])
                self.cancelled_opens[token] = self.clock()
                running = self.open_tokens.get(token)
                if running is not None:
                    running.cancel(CLOSED)  # stop discovery itself, not only discard its result
                while len(self.cancelled_opens) > 64:
                    self.cancelled_opens.popitem(last=False)
                for did in list(self.documents):
                    if self.documents[did]['open_token'] == token:
                        del self.documents[did]
        return {'closed': True}

    def clear(self):
        with self.lock:
            self.documents.clear()
            self.cancelled_opens.clear()
