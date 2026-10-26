"""Render newly authored smoke-test equations to images with matplotlib mathtext.

These equations were written for this app's tests (not taken from any textbook or dataset). Mathtext is
a different typesetter from the LaTeX renders pix2tex was trained on. The reference strings are used
only by tests to compare against model output after inference; inference never sees them.

  python tests/backend/make_images.py [OUT_DIR]
"""
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

CASES = [
    # id, mathtext source, expected feature checked by tests
    ('fraction', r'\frac{3y-5}{2y+7}', 'fraction'),
    ('sqrt_powers', r'\sqrt{p^{2}+q^{3}}', 'root'),
    ('cube_root', r'\sqrt[3]{8m}', 'root_index'),
    ('integral', r'\int_{1}^{4} t^{3}\,dt', 'integral'),
    ('sum', r'\sum_{k=0}^{n} 2^{k}', 'sum'),
    ('exp_neg', r'e^{-x^{2}}', 'exponent'),
    ('relation', r'a \leq b - 1', 'relation'),
]
FONTSETS = ('cm', 'stix')


def render(src, fontset, dpi=200, fontsize=22):
    with plt.rc_context({'mathtext.fontset': fontset}):
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f'${src}$', fontsize=fontsize)
        buf = io.BytesIO()
        fig.savefig(buf, dpi=dpi, format='png', bbox_inches='tight', pad_inches=0.12, facecolor='white')
        plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert('RGB')


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cid, src, feature in CASES:
        for fs in FONTSETS:
            img = render(src, fs)
            name = f'{cid}_{fs}.png'
            img.save(out / name)
            manifest.append({'file': name, 'id': cid, 'fontset': fs, 'authored_source': src, 'feature': feature})
    # one JPEG and one transparent PNG variant of the fraction
    img = render(CASES[0][1], 'cm')
    img.save(out / 'fraction_cm.jpg', quality=80)
    manifest.append({'file': 'fraction_cm.jpg', 'id': 'fraction', 'fontset': 'cm', 'authored_source': CASES[0][1], 'feature': 'fraction'})
    g = img.convert('L')
    rgba = Image.new('RGBA', img.size, (0, 0, 0, 0))
    rgba.putalpha(g.point(lambda v: 255 - v))
    rgba.save(out / 'fraction_transparent.png')
    manifest.append({'file': 'fraction_transparent.png', 'id': 'fraction', 'fontset': 'cm', 'authored_source': CASES[0][1], 'feature': 'fraction'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    m = main(sys.argv[1] if len(sys.argv) > 1 else 'test-output/images')
    print(f'wrote {len(m)} images')
