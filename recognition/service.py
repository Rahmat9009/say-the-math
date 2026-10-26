"""Reader service: status, /api/read and /api/format logic, independent of the HTTP layer."""
import importlib.util
import logging
import threading
import time

from . import config, errors, images
from .mathconv import MathWorker, MathWorkerError, worker_problems
from .jobs import CancelToken, RecognitionStopped, TIME_LIMIT, current as current_job
from .model import ModelMissing, Pix2TexReader, checkpoint_problems
from .selection import alternatives, choose, confidence

log = logging.getLogger('saythemath')
PY_MODULES = ('torch', 'torchvision', 'pix2tex', 'timm', 'x_transformers', 'transformers', 'albumentations', 'cv2', 'munch', 'yaml')


def stopped_error(reason, token):
    """Explicit failed/incomplete state for a reading that was stopped. No partial reading is returned."""
    if reason == TIME_LIMIT:
        return errors.ApiError(504, 'RECOGNITION_TIMEOUT',
                               f'Recognition stopped after the {token.limit_s:g}-second limit without a result. No reading was '
                               'produced. This equation may be too long or complex for the local reader; try a tighter crop.')
    return errors.ApiError(409, 'RECOGNITION_CANCELLED', 'Recognition was cancelled before it finished. No reading was produced.')


def python_problems():
    return [f'Python package {m} is not installed' for m in PY_MODULES if importlib.util.find_spec(m) is None]


class ReaderService:
    def __init__(self, reader=None, worker=None, verify_hashes=True):
        self.reader = reader or Pix2TexReader()
        self.worker = worker or MathWorker()
        self._infer_lock = threading.Lock()
        self._current_token = None
        self.last_stop = None
        self.model_error = None
        self.math_error = None
        # Setup checks apply to the real reader/worker; explicit test doubles skip them.
        real_reader = isinstance(self.reader, Pix2TexReader)
        self.model_problems = (python_problems() + checkpoint_problems(self.reader.models_dir, verify_hash=verify_hashes)
                               if real_reader else [])
        self.math_problems = worker_problems() if isinstance(self.worker, MathWorker) else []

    # ---- readiness -------------------------------------------------------------------------
    @property
    def model_available(self):
        return not self.model_problems and self.model_error is None

    @property
    def math_available(self):
        return not self.math_problems and self.math_error is None

    def warm_up(self):
        """Load the model and start the math worker (call in a background thread)."""
        if self.math_available:
            try:
                self.worker.ensure_started()
            except Exception as e:
                self.math_error = 'The local math converter could not start.'
                log.warning('math worker failed to start: %s', type(e).__name__)
        if self.model_available:
            # Not under the inference lock: a read arriving during warm-up waits on the reader's load lock.
            try:
                self.reader.load()
            except ModelMissing:
                self.model_error = 'The model files are missing or do not match their pinned checksums. Run setup again.'
            except Exception as e:
                self.model_error = 'The local model could not be loaded. Run setup again.'
                log.warning('model failed to load: %s', type(e).__name__)

    def status(self):
        ready = self.model_available and self.math_available
        if ready:
            message = 'Local reader is ready.'
            if not getattr(self.reader, 'loaded', True):
                message = 'Local reader is ready. The first reading also loads the model, so it takes longer.'
        else:
            parts = []
            if self.model_problems:
                parts.append('The recognition model is not set up (' + '; '.join(self.model_problems[:3]) + ').')
            elif self.model_error:
                parts.append(self.model_error)
            if self.math_problems:
                parts.append('The math converter is not set up (' + '; '.join(self.math_problems[:3]) + ').')
            elif self.math_error:
                parts.append(self.math_error)
            parts.append('Run Start-Windows.cmd (Windows) or ./start.sh (macOS/Linux) to finish setup.')
            message = ' '.join(parts)
        params = getattr(self.reader, 'parameters', None) or config.EXPECTED_PARAMETERS
        return {'ready': ready, 'model_available': self.model_available, 'math_available': self.math_available,
                'message': message, 'model': {'name': config.MODEL_NAME, 'parameters': params['total']}}

    def _require(self, model=True):
        st = self.status()
        if (model and not st['model_available']) or not st['math_available']:
            raise errors.not_ready(st['message'])

    # ---- conversion ------------------------------------------------------------------------
    def _convert(self, latex):
        try:
            out = self.worker.convert(latex)
        except MathWorkerError as e:
            if e.code in ('WORKER_EXITED', 'NOT_READY'):
                raise errors.ApiError(500, 'INTERNAL_ERROR', 'The local math converter stopped. Try again.')
            if e.code == 'TIMEOUT':
                raise errors.math_failed('Converting this reading to MathML took too long.')
            raise errors.math_failed('This reading could not be converted to MathML and speech '
                                     f'({e.message}). Try another image or an alternative reading.')
        return out

    # ---- endpoints -------------------------------------------------------------------------
    def acquire_inference(self, token):
        """Serialize model access. Wait briefly only when the running job is already stopping (cancelled,
        disconnected or over its limit) so a newly chosen equation is not refused while the old job unwinds;
        otherwise refuse with BUSY as before. Returns the stop latency observed, if any."""
        if self._infer_lock.acquire(blocking=False):
            return None
        current = self._current_token
        if current is not None and current.cancelled:
            t0 = time.perf_counter()
            if self._infer_lock.acquire(timeout=config.STOP_WAIT_S):
                return time.perf_counter() - t0
        raise errors.busy()

    def read(self, payload, token=None):
        """token: jobs.CancelToken. Defaults to the current job's token (set by the HTTP layer), otherwise a new
        token with the default recognition time limit."""
        token = token or current_job() or CancelToken(config.READ_TIME_LIMIT_S)
        if not isinstance(payload, dict):
            raise errors.bad_request('Send a JSON object.')
        unknown = set(payload) - {'image_base64', 'filename'}
        if unknown:
            raise errors.bad_request('Unexpected fields in the request.')
        fn = payload.get('filename')
        if fn is not None and (not isinstance(fn, str) or len(fn) > 255):
            raise errors.bad_request('filename must be a short string.')
        self._require(model=True)
        data = images.decode_base64(payload.get('image_base64'))
        img = images.load_image(data)
        del data
        if not images.has_visible_content(img):
            raise errors.invalid_image('The image looks blank. Choose a tight crop that shows the equation.')
        self.acquire_inference(token)
        self._current_token = token
        t0 = time.perf_counter()
        try:
            try:
                reads = self.reader.read_scales(img, token)
            except RecognitionStopped as stop:
                # Diagnostics only (never returned to clients): how quickly the computation unwound after the stop.
                self.last_stop = {'reason': stop.reason, 'after_s': round(token.elapsed(), 3),
                                  'unwind_s': round(time.monotonic() - (token.stopped_at or time.monotonic()), 3)}
                raise stopped_error(stop.reason, token)
            except ModelMissing:
                self.model_error = 'The model files are missing or do not match their pinned checksums. Run setup again.'
                raise errors.not_ready(self.model_error)
            except errors.ApiError:
                raise
            except Exception as e:
                log.warning('recognition failed: %s', type(e).__name__)
                raise errors.recognition_failed()
        finally:
            self._current_token = None
            self._infer_lock.release()
        if token.reason is not None and token.reason != TIME_LIMIT:
            # The client cancelled or went away after decoding finished: do not convert or return a stale reading.
            raise stopped_error(token.reason, token)
        chosen, agreeing = choose(reads)
        if not chosen['latex'].strip():
            raise errors.ApiError(422, 'NO_READING', 'The model did not produce a reading for this image. Try a tighter crop or a clearer image.')
        conf = confidence(chosen, agreeing, len(reads))
        conv = self._convert(chosen['latex'])
        return {
            'latex': chosen['latex'],
            'speech': conv['speech'],
            'mathml': conv['mathml'],
            'confidence': conf,
            'root_id': conv['root_id'],
            'nodes': conv['nodes'],
            'tree_truncated': conv['truncated'],
            'alternatives': alternatives(reads, chosen),
            'elapsed_ms': round((time.perf_counter() - t0) * 1000),
        }

    def format(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'latex'}:
            raise errors.bad_request('Send a JSON object with a latex field.')
        latex = payload.get('latex')
        if not isinstance(latex, str) or not latex.strip():
            raise errors.bad_request('latex must be a non-empty string.')
        if len(latex) > config.MAX_LATEX_CHARS:
            raise errors.ApiError(413, 'LATEX_TOO_LONG', f'The reading is longer than {config.MAX_LATEX_CHARS} characters.')
        self._require(model=False)
        conv = self._convert(latex)
        return {'latex': latex, 'speech': conv['speech'], 'mathml': conv['mathml'], 'root_id': conv['root_id'],
                'nodes': conv['nodes'], 'tree_truncated': conv['truncated']}

    def close(self):
        self.worker.close()
