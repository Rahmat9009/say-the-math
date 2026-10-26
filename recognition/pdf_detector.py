"""Experimental detector, vendored from the frozen PDF feasibility detector.

Origin: research/pdf_feasibility/detect.py (project MIT code). Runtime uses detect_page;
no research manifests, readings, annotations or source comparisons are imported.
Discovery remains fallible; this is not a crop-completeness test.

Displayed-equation candidate detection from a born-digital PDF's own glyphs and rules.

Two detectors share the same line building and grouping:
  font_only - a line is math if any glyph uses a math font (the baseline the brief warns about)
  combined  - math-font share, math-symbol share, word count, centring/indent, left-margin prose start,
              fraction rules; equation numbers are split off; stacked relation rows are flagged multi-line
Both report vector-graphics clusters without a text layer as "unsupported" regions instead of ignoring them.

  python detect.py PDF [--detector combined|font_only]   -> JSON candidates on stdout
"""
import json
import heapq
import re
import statistics
import sys
import unicodedata
from dataclasses import dataclass, field

import pdfplumber

MATH_FONT = re.compile(r'(math|mjx|^cm(mi|sy|ex|bsy|mib)\d|stix|symbol|mt ?extra|msam|msbm|eufm|rsfs|esint|newcm|euclid)', re.I)
MATH_CHARS = set('=+−<>≤≥≠≈∈∉⊂⊆∪∩∑∏∫∮√∞∂∇±∓×÷·⋅∘→←↔⇒⇔∀∃∅∠⊥∥′″^_/')
RELATIONS = set('=<>≤≥≠≈∈∉⊂⊆⊃⊇≡∼≃≅∝')
EQNUM = re.compile(r'^\(\s*[0-9A-Za-z]+([.\-][0-9A-Za-z]+)*\s*\)$')


def base_font(name):
    return name.split('+', 1)[-1]


def is_math_font(name):
    return bool(MATH_FONT.search(base_font(name)))


def is_math_char(ch):
    if len(ch) != 1:  # ligatures ("fi") and unmapped "(cid:N)" glyphs carry no usable symbol identity
        return False
    if ch in MATH_CHARS:
        return True
    o = ord(ch)
    if 0x1D400 <= o <= 0x1D7FF or 0x0391 <= o <= 0x03C9 or 0x2200 <= o <= 0x22FF or 0x27C0 <= o <= 0x27EF or 0x2980 <= o <= 0x2AFF:
        return True
    return unicodedata.category(ch) == 'Sm'


@dataclass
class Line:
    chars: list
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def text(self):
        return ''.join(c['text'] for c in sorted(self.chars, key=lambda c: c['x0']))

    def refresh(self):
        self.x0 = min(c['x0'] for c in self.chars)
        self.x1 = max(c['x1'] for c in self.chars)
        self.top = min(c['top'] for c in self.chars)
        self.bottom = max(c['bottom'] for c in self.chars)


def page_objects(page):
    chars = [c for c in page.chars if c['text'].strip()]
    rules = []
    for o in list(page.rects) + list(page.lines):
        h = o['bottom'] - o['top']
        w = o['x1'] - o['x0']
        if h <= 1.6 and w >= 3:
            rules.append({'x0': o['x0'], 'x1': o['x1'], 'top': o['top'], 'bottom': o['bottom']})
    graphics = [{'x0': o['x0'], 'x1': o['x1'], 'top': o['top'], 'bottom': o['bottom']} for o in page.curves]
    return chars, rules, graphics


def build_lines(chars):
    """Cluster glyphs into visual lines by vertical overlap of their boxes (scripts may form own lines)."""
    lines = []
    for c in sorted(chars, key=lambda c: ((c['top'] + c['bottom']) / 2, c['x0'])):
        cy = (c['top'] + c['bottom']) / 2
        best = None
        for ln in lines[-6:]:
            overlap = min(ln.bottom, c['bottom']) - max(ln.top, c['top'])
            if overlap >= 0.6 * min(ln.bottom - ln.top, c['bottom'] - c['top']) and ln.top - 1 <= cy <= ln.bottom + 1:
                best = ln
        if best is None:
            lines.append(Line([c], c['x0'], c['x1'], c['top'], c['bottom']))
        else:
            best.chars.append(c)
            best.refresh()
    return lines


def split_numbers(lines, col, body_size):
    """Split a right- or left-margin "(n)" segment off a line when separated by a wide gap."""
    numbers = []
    for ln in lines:
        cs = sorted(ln.chars, key=lambda c: c['x0'])
        segs, cur = [], [cs[0]]
        for a, b in zip(cs, cs[1:]):
            if b['x0'] - a['x1'] > 2.5 * body_size:
                segs.append(cur)
                cur = []
            cur.append(b)
        segs.append(cur)
        if len(segs) < 2:
            continue
        for seg in (segs[-1], segs[0]):
            txt = ''.join(c['text'] for c in seg).strip()
            near_edge = (seg[-1]['x1'] >= col[1] - 2) or (seg[0]['x0'] <= col[0] + 2)
            if EQNUM.match(txt) and near_edge and len(seg) < len(cs):
                numbers.append({'text': txt, 'x0': seg[0]['x0'], 'x1': seg[-1]['x1'],
                                'top': min(c['top'] for c in seg), 'bottom': max(c['bottom'] for c in seg)})
                ln.chars = [c for c in ln.chars if c not in seg]
                ln.refresh()
                break
    return numbers


def line_features(ln, col):
    chars = ln.chars
    n = len(chars)
    ordered = sorted(chars, key=lambda c: c['x0'])
    mf = sum(is_math_font(c['fontname']) for c in chars) / n
    ms = sum(is_math_char(c['text']) for c in chars) / n
    plain = ''.join(c['text'] if not is_math_font(c['fontname']) and not is_math_char(c['text']) else ' ' for c in ordered)
    words = len(re.findall(r'[A-Za-z]{3,}', plain))
    left, right = ln.x0 - col[0], col[1] - ln.x1
    width = ln.x1 - ln.x0
    colw = col[1] - col[0]
    centred = abs(left - right) <= 0.12 * colw and width <= 0.8 * colw
    indented = left >= 1.5 * statistics.median(c['size'] for c in chars) and width <= 0.8 * colw
    first = ordered[0]
    prose_start = left <= 2 and not is_math_font(first['fontname']) and first['text'].isalpha() and \
        bool(re.match(r'[A-Za-z]{2,}', plain.strip()))
    return {'n': n, 'math_font': mf, 'math_sym': ms, 'words': words, 'centred': centred, 'indented': indented,
            'prose_start': prose_start, 'text': ln.text, 'eqnum': bool(EQNUM.match(ln.text.strip())),
            'relations': sum(c['text'] in RELATIONS for c in chars)}


def is_math_line(f, detector):
    if f['eqnum']:
        return False
    if detector == 'font_only':
        return f['math_font'] > 0
    if f['words'] >= 4 or f['prose_start']:
        return False
    evidence = f['math_font'] >= 0.5 or f['math_sym'] >= 0.25
    return evidence and (f['centred'] or f['indented'] or f['words'] <= 1)


def _join(a, b, body_size):
    vgap = max(a['top'], b['top']) - min(a['bottom'], b['bottom'])
    hover = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
    return vgap <= 0.75 * body_size and hover > -0.5 * body_size


def group(items, body_size):
    """Same first-pair merge rule as the frozen detector, without cubic rescanning.

    A merge only expands a box, so an eligible pair stays eligible. Original indices
    preserve list order after deletions; a min-heap picks exactly the first (i,j)
    the frozen nested loop would merge. Recheck only pairs involving the expanded box.
    This matters for PDF pages with thousands of vector-path fragments.
    """
    groups = [dict(it, members=[it]) for it in sorted(items, key=lambda i: i['top'])]
    active = [True] * len(groups)
    pairs, seen = [], set()
    def offer(i, j):
        if (i,j) not in seen and _join(groups[i], groups[j], body_size):
            seen.add((i,j))
            heapq.heappush(pairs,(i,j))
    for i, a in enumerate(groups):
        for j in range(i+1,len(groups)):
            if groups[j]['top'] > a['bottom'] + .75 * body_size:
                break
            offer(i,j)
    while pairs:
        i,j = heapq.heappop(pairs)
        if not active[i] or not active[j]:
            continue
        a,b = groups[i],groups[j]
        a['members'] += b['members']
        for k, fn in (('x0', min), ('top', min), ('x1', max), ('bottom', max)):
            a[k] = fn(a[k], b[k])
        active[j] = False
        for k in range(i):
            if active[k] and a['top'] <= groups[k]['bottom'] + .75 * body_size:
                offer(k,i)
        for k in range(i+1,len(groups)):
            if groups[k]['top'] > a['bottom'] + .75 * body_size:
                break
            if active[k]:
                offer(i,k)
    return [g for i,g in enumerate(groups) if active[i]]


def rows_with_relations(lines_in, rules_in):
    """Count stacked rows that each carry a relation and are not separated by a fraction rule."""
    main = max(statistics.median(c['size'] for c in m['line'].chars) for m in lines_in)
    rows = sorted([m['line'] for m in lines_in
                   if any(c['text'] in RELATIONS and c['size'] >= 0.85 * main for c in m['line'].chars)],  # not limits/scripts
                  key=lambda l: l.top)
    count = 1 if rows else 0
    for a, b in zip(rows, rows[1:]):
        if b.top >= a.bottom - 1 and not any(a.bottom - 2 <= r['top'] <= b.top + 2 for r in rules_in):
            count += 1
    return count


def detect_page(page, detector='combined', col=None):
    chars, rules, graphics = page_objects(page)
    out = {'candidates': [], 'unsupported': [], 'eqnums': []}
    if not chars and not graphics:
        return out
    body_size = statistics.median([c['size'] for c in chars]) if chars else 12.0
    col = col or (min((c['x0'] for c in chars), default=0), max((c['x1'] for c in chars), default=page.width))
    lines = build_lines(chars)
    if detector == 'combined':
        out['eqnums'] = split_numbers(lines, col, body_size)
        lines = [ln for ln in lines if ln.chars]
    feats = [(ln, line_features(ln, col)) for ln in lines]
    for ln, f in feats:
        if f['eqnum']:
            out['eqnums'].append({'text': f['text'].strip(), 'x0': ln.x0, 'x1': ln.x1, 'top': ln.top, 'bottom': ln.bottom})
    math_items = [{'kind': 'line', 'x0': ln.x0, 'x1': ln.x1, 'top': ln.top, 'bottom': ln.bottom, 'line': ln, 'f': f}
                  for ln, f in feats if is_math_line(f, detector)]
    for r in rules:  # fraction rules / radical bars belong to math only next to a math line
        if any(min(m['x1'], r['x1']) - max(m['x0'], r['x0']) > 0 and
               (abs(r['top'] - m['bottom']) < body_size or abs(m['top'] - r['bottom']) < body_size) for m in math_items):
            math_items.append({'kind': 'rule', **r})
    pad = 0.2 * body_size
    for g in group(math_items, body_size):
        lines_in = [m for m in g['members'] if m['kind'] == 'line']
        if not lines_in:
            continue
        rules_in = [m for m in g['members'] if m['kind'] == 'rule']
        box = [g['x0'] - pad, g['top'] - pad, g['x1'] + pad, g['bottom'] + pad]
        for o in graphics + rules:  # strokes of stretchy glyphs or bars that touch the box
            if o['x1'] >= box[0] and o['x0'] <= box[2] and o['bottom'] >= box[1] and o['top'] <= box[3] \
                    and (o['x1'] - o['x0']) < 4 * (box[2] - box[0]):
                box = [min(box[0], o['x0']), min(box[1], o['top']), max(box[2], o['x1']), max(box[3], o['bottom'])]
        n_rel_rows = rows_with_relations(lines_in, rules_in)
        cand = {'x0': box[0], 'top': box[1], 'x1': box[2], 'bottom': box[3],
                'text': ' '.join(m['line'].text for m in sorted(lines_in, key=lambda m: m['top'])),
                'fonts': sorted({base_font(c['fontname']) for m in lines_in for c in m['line'].chars}),
                'glyphs': sum(len(m['line'].chars) for m in lines_in),
                'has_rule': bool(rules_in), 'layout': 'multi-line' if n_rel_rows >= 2 else 'single-line'}
        num = [e for e in out['eqnums'] if e['top'] < g['bottom'] + 2 and e['bottom'] > g['top'] - 2]
        cand['number'] = num[0]['text'] if num else None
        prev = [ln for ln, f in feats if ln.bottom <= g['top'] + 1 and not is_math_line(f, detector) and not f['eqnum']]
        cand['context_before'] = max(prev, key=lambda l: l.bottom).text[-80:] if prev else ''
        out['candidates'].append(cand)
    # Navigation needs a page-level warning, not approximate unsupported-region boxes.
    # Grouping thousands of vector fragments is expensive and does not recover math.
    # Do not perform or expose that research-only localization at runtime.
    if graphics:
        out['unsupported'].append({'reason': 'Vector drawings are not interpreted as equations.'})
    return out


def detect(pdf_path, detector='combined'):
    res = []
    with pdfplumber.open(pdf_path) as pdf:
        allchars = [c for p in pdf.pages for c in p.chars if c['text'].strip()]
        col = (min(c['x0'] for c in allchars), max(c['x1'] for c in allchars)) if allchars else None
        for i, page in enumerate(pdf.pages):
            d = detect_page(page, detector, col)
            res.append({'page': i, 'label': page.page_number, **d})
    order = 0
    for p in res:
        p['candidates'].sort(key=lambda c: (c['top'], c['x0']))
        for c in p['candidates']:
            c['order'] = order
            order += 1
    return res


if __name__ == '__main__':
    det = sys.argv[sys.argv.index('--detector') + 1] if '--detector' in sys.argv else 'combined'
    print(json.dumps(detect(sys.argv[1], det), indent=1, default=str))
