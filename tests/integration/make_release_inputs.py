"""Generate original, disposable PDF/long-equation inputs for browser release checks.

Run from the project root after installing requirements-dev.txt. No saved reading
or reference answer is supplied to the runtime recognition API.
"""
import base64
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    output = ROOT / 'test-output'
    output.mkdir(exist_ok=True)
    pages = runpy.run_path(str(ROOT / 'tests/integration/test_pdf_portable.py'))
    pdf = pages['authored_pdf'].__wrapped__()
    (output / 'authored.pdf').write_bytes(base64.b64decode(pdf))
    images = runpy.run_path(str(ROOT / 'tests/backend/make_images.py'))
    equation = '+'.join(r'\frac{x^{%d}+%d}{x+%d}' % (i, i, i+1)
                        for i in range(1, 13)) + '=y'
    images['render'](equation, 'cm').save(output / 'long-equation.png')
    print('Generated authored.pdf and long-equation.png in test-output.')


if __name__ == '__main__':
    main()
