"""LaTeX -> MathML, speech and tree through the real local Node worker (no OCR involved)."""
import pytest

from recognition.mathconv import MathWorker, MathWorkerError
from treecheck import check_mathml, check_tree, child_kinds, kinds


@pytest.fixture(scope='module')
def worker():
    w = MathWorker()
    w.ensure_started()
    yield w
    w.close()


def convert(worker, latex):
    out = worker.convert(latex)
    check_mathml(out['mathml'])
    by_id = check_tree(out)
    return out, by_id


def test_fraction_roles(worker):
    out, by_id = convert(worker, r'\frac{x+1}{2}')
    assert out['speech'] == 'the fraction with numerator x plus 1 and denominator 2'
    frac = next(n for n in out['nodes'] if n['kind'] == 'fraction')
    assert child_kinds(by_id, frac) == ['numerator', 'denominator']
    num = by_id[frac['children'][0]]
    assert num['label'] == 'Numerator: x plus 1'
    assert child_kinds(by_id, num) == ['identifier', 'operator', 'number']
    assert by_id[frac['children'][1]]['label'] == 'Denominator: 2'


def test_exponent_and_root_index(worker):
    out, by_id = convert(worker, r'\sqrt[3]{a^{2}-b}')
    root = next(n for n in out['nodes'] if n['kind'] == 'root')
    assert child_kinds(by_id, root) == ['radicand', 'index']
    assert by_id[root['children'][1]]['label'] == 'Root index: 3'
    power = next(n for n in out['nodes'] if n['kind'] == 'power')
    assert child_kinds(by_id, power) == ['base', 'exponent']
    assert 'cube root' in out['speech'] and 'minus' in out['speech']


def test_square_root_radicand(worker):
    out, by_id = convert(worker, r'\sqrt{x+y}')
    sq = next(n for n in out['nodes'] if n['kind'] == 'square_root')
    assert child_kinds(by_id, sq) == ['radicand']
    assert by_id[sq['children'][0]]['label'] == 'Radicand: x plus y'


def test_integral_bounds(worker):
    out, by_id = convert(worker, r'\int_{0}^{\pi} \sin t \, dt')
    op = next(n for n in out['nodes'] if n['kind'] == 'bounded_operator')
    assert child_kinds(by_id, op) == ['base', 'lower_bound', 'upper_bound']
    assert by_id[op['children'][1]]['label'] == 'Lower bound: 0'
    assert by_id[op['children'][2]]['label'] == 'Upper bound: pi'
    assert out['speech'].startswith('the integral from 0 to pi')


def test_sum_and_limit(worker):
    out, by_id = convert(worker, r'\sum_{k=1}^{n} k = \lim_{h \to 0} f(h)')
    assert 'bounded_operator' in kinds(out)
    cond = next(n for n in out['nodes'] if n['kind'] == 'condition')
    assert cond['label'].startswith('Condition: h')


def test_minus_sign_survives(worker):
    out, _ = convert(worker, r'-x^{2}')
    assert 'negative' in out['speech'] or 'minus' in out['speech']
    out2, _ = convert(worker, r'x^{-2}')
    assert out['speech'] != out2['speech']


def test_nested_fraction_and_matrix(worker):
    out, by_id = convert(worker, r'\frac{1}{1+\frac{1}{x}}')
    assert kinds(out).count('fraction') == 2
    out, by_id = convert(worker, r'\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}')
    table = next(n for n in out['nodes'] if n['kind'] == 'table')
    assert child_kinds(by_id, table) == ['table_row', 'table_row']
    assert all(child_kinds(by_id, by_id[r]) == ['table_cell', 'table_cell'] for r in table['children'])


def test_text_and_relations(worker):
    out, _ = convert(worker, r'x \leq 3 \text{ if } x \in A')
    assert 'less than or equal' in out['speech']


def test_large_expression_is_truncated_not_broken(worker):
    latex = '+'.join(f'x_{{{i}}}' for i in range(200))
    out = worker.convert(latex)
    assert out['truncated'] is True
    check_tree(out)


@pytest.mark.parametrize('latex', [
    r'\frac{1}{', r'\foo{x}', r'\href{http://example.com}{x}', r'\require{html}', r'\def\a{\a}\a',
    r'\class{c}{x}', r'\style{color:red}{x}', r'\unicode{65}', r'\begin{xyz}x\end{xyz}', '}', '   ', r'\input{file}',
])
def test_conversion_failures_are_reported(worker, latex):
    with pytest.raises(MathWorkerError) as e:
        worker.convert(latex)
    assert e.value.code == 'MATH_CONVERSION_FAILED'


def test_too_long_rejected(worker):
    with pytest.raises(MathWorkerError):
        worker.convert('x' * 2001)


def test_worker_restarts_after_crash(worker):
    worker.proc.kill()
    worker.proc.wait()
    out = worker.convert('a+b')
    assert out['speech'] == 'a plus b'


def test_worker_has_no_network(worker):
    msg = worker.ping()
    assert msg['ok'] and msg['blocked_connections'] == 0
    assert msg['versions']['mathjax'] == '4.1.3' and msg['versions']['sre'] == '5.0.0-rc.4'
