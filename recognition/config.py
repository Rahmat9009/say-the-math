"""Fixed configuration for the local reader. Nothing here is read from the network."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / 'web'
MODELS_DIR = Path(os.environ.get('SAYTHEMATH_MODELS_DIR', ROOT / 'models'))
SETUP_RECORD = MODELS_DIR / 'setup-record.json'
WORKER_SCRIPT = ROOT / 'math_worker.mjs'
NODE_MODULES = ROOT / 'node_modules'

# pix2tex 0.1.4 release v0.0.1 checkpoints (https://github.com/lukas-blecher/LaTeX-OCR/releases/tag/v0.0.1).
CHECKPOINTS = {
    'weights.pth': {
        'url': 'https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/weights.pth',
        'sha256': 'a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa',
    },
    'image_resizer.pth': {
        'url': 'https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/image_resizer.pth',
        'sha256': '1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458',
    },
}
MODEL_NAME = 'pix2tex'
# Architecture size reported by the earlier experiment; the app recounts from the loaded modules.
EXPECTED_PARAMETERS = {'encoder': 12855232, 'decoder': 12643648, 'image_resizer': 4852949, 'total': 30351829}
MAX_PARAMETERS = 500_000_000

# Inference settings from the research notes (system v2).
SCALES = (1.0, 0.75, 0.55)
TEMPERATURE = 0.00001
# Experimental heuristic calibrated in another environment. Not a probability of correctness.
LOGPROB_THRESHOLD = -0.0006153307040221989
MIN_AGREEING = 2
TORCH_THREADS = int(os.environ.get('SAYTHEMATH_THREADS', '0')) or max(1, min(4, (os.cpu_count() or 2)))

# Request limits (API_CONTRACT.md).
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_BODY_BYTES = 12 * 1024 * 1024  # base64 of 8 MiB plus JSON overhead
MAX_FORMAT_BODY_BYTES = 64 * 1024
MAX_LATEX_CHARS = 2000
WORKER_TIMEOUT_S = 15.0
# Bounded execution. A reading (three scales) that has not finished within this limit is stopped inside the model
# and reported as RECOGNITION_TIMEOUT; it is below the frontend's 180 s wait so the user gets an explicit state.
READ_TIME_LIMIT_S = float(os.environ.get('SAYTHEMATH_READ_LIMIT_S', '120'))
# PDF discovery limit (the frontend waits up to 300 s for /api/pdf/open).
PDF_OPEN_TIME_LIMIT_S = float(os.environ.get('SAYTHEMATH_PDF_OPEN_LIMIT_S', '240'))
# How long a new request may wait for a job that is already stopping (cancelled, disconnected or over its limit).
STOP_WAIT_S = 5.0
DEFAULT_PORT = 8765

HIGHER_MESSAGE = ('Higher-confidence reading. At least two of three readings agreed and the model scored this '
                  'reading highly, but recognition can still change signs, exponents or roots. Check anything important.')
UNCERTAIN_MESSAGE = ('Uncertain reading. The readings disagreed or the model scored this reading low. '
                     'Treat it as a guess and compare the alternatives.')
