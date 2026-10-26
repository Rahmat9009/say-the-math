"""Offline self-check: verify checkpoints, load pix2tex, count parameters, start the math worker.

  python -m recognition.selfcheck [--write models/setup-record.json]
"""
import argparse
import importlib.metadata as md
import json
import platform
import sys
import time

from . import netguard

netguard.install()

from . import config  # noqa: E402
from .mathconv import MathWorker, worker_problems  # noqa: E402
from .model import Pix2TexReader, checkpoint_problems, sha256_file  # noqa: E402

PACKAGES = ['torch', 'torchvision', 'pix2tex', 'timm', 'x-transformers', 'transformers', 'tokenizers', 'albumentations',
            'numpy', 'Pillow', 'opencv-python-headless', 'munch', 'PyYAML', 'pdfplumber', 'pdfminer.six', 'pypdfium2']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', help='write the record to this JSON path')
    a = ap.parse_args()
    problems = checkpoint_problems() + worker_problems()
    if problems:
        print('SELF-CHECK FAILED: ' + '; '.join(problems), file=sys.stderr)
        sys.exit(1)
    r = Pix2TexReader()
    t0 = time.perf_counter()
    r.load()
    load_s = time.perf_counter() - t0
    p = r.parameters
    print(f'pix2tex loaded in {load_s:.1f} s; parameters: encoder {p["encoder"]:,}, decoder {p["decoder"]:,}, '
          f'image resizer {p["image_resizer"]:,}, total {p["total"]:,}')
    if p['total'] > config.MAX_PARAMETERS:
        print('SELF-CHECK FAILED: model exceeds 500M parameters', file=sys.stderr)
        sys.exit(1)
    if p != config.EXPECTED_PARAMETERS:
        print(f'NOTE: parameter count differs from the research record {config.EXPECTED_PARAMETERS}')
    w = MathWorker()
    versions = w.ensure_started()
    probe = w.convert(r'\frac{a}{b}')
    w.close()
    print(f'math worker: {versions}; probe speech: {probe["speech"]!r}')
    record = {
        'checked_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'python': platform.python_version(), 'platform': platform.platform(),
        'model': config.MODEL_NAME, 'parameters': p,
        'checkpoint_sha256': {n: sha256_file(config.MODELS_DIR / n) for n in config.CHECKPOINTS},
        'model_load_seconds': round(load_s, 2), 'torch_threads': config.TORCH_THREADS,
        'python_packages': {k: _version(k) for k in PACKAGES},
        'math_worker': versions,
        'network_attempts_blocked': len(netguard.blocked_attempts),
    }
    from .pdfnav import availability
    record['pdf_navigation'] = availability()
    print(record['pdf_navigation']['message'])
    if a.write:
        config.MODELS_DIR.mkdir(exist_ok=True)
        with open(a.write, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=1)
        print(f'wrote {a.write}')
    print('SELF-CHECK PASSED')


def _version(name):
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


if __name__ == '__main__':
    main()
