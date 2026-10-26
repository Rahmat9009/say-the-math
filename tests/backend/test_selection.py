"""Voting normalization and reference-free confidence rule."""
import pytest

from recognition import config
from recognition.normalize import normalize, vote_key
from recognition.selection import alternatives, choose, confidence

GOOD = config.LOGPROB_THRESHOLD + 1e-4   # just above the threshold
LOW = config.LOGPROB_THRESHOLD - 1e-3


def r(latex, lp, scale=1.0):
    return {'latex': latex, 'lp_mean': lp, 'scale': scale}


@pytest.mark.parametrize('a,b', [
    (r'\dfrac{a}{b}', r'\frac{a}{b}'),
    (r'\tfrac{a}{b}', r'\frac{a}{b}'),
    (r'x\,+\;y', r'x+y'),
    (r'\left(x\right)', r'(x)'),
    (r'\operatorname{sin} x', r'\mathrm{sin} x'),
    (r'\displaystyle\int_0^1 f', r'\int_0^1 f'),
    (r'a\quad b', r'a b'),
])
def test_equivalent_spellings_vote_together(a, b):
    assert vote_key(a) == vote_key(b)


@pytest.mark.parametrize('a,b', [
    ('x-1', 'x+1'),                         # sign
    ('x-1', 'x1'),                          # lost minus
    (r'a\leq b', 'a<b'),                    # relation
    (r'x\in A', r'x\notin A'),              # membership
    ('x^{2}+y', 'x+y^{2}'),                 # exponent placement
    (r'\sqrt[3]{x}', r'\sqrt{x}'),          # radical index
    (r'\frac{a}{b}', r'\frac{b}{a}'),       # numerator / denominator
    (r'\int_{0}^{1}', r'\int_{1}^{0}'),     # bounds
    ('x^{2}', 'x_{2}'),                     # super vs sub
    ('-x', 'x'),
])
def test_meaningful_differences_are_preserved(a, b):
    assert vote_key(a) != vote_key(b)


def test_text_mode_spaces_are_meaningful():
    assert vote_key(r'\text{a b}') != vote_key(r'\text{ab}')
    assert vote_key(r'x\ \text{for all } x') != vote_key(r'x\ \text{forall } x')
    assert vote_key(r'\mbox{if x}') != vote_key(r'\mbox{ifx}')
    assert vote_key(r'\text{a  b}') == vote_key(r'\text{a b}')          # runs of spaces collapse
    assert vote_key(r'\text {a b}') == vote_key(r'\text{a b}')
    assert vote_key(r'x\text{ if }y') != vote_key(r'x\text{if}y')      # spaces inside text render in LaTeX
    assert vote_key(r'\text{a {b} c}+1') == vote_key(r'\text{a {b} c} + 1')   # nested braces; math spaces ignored
    assert vote_key(r'\text{a {b} c}') != vote_key(r'\text{a{b}c}')
    assert vote_key('d t') == vote_key('dt')                            # math-mode spaces are not meaningful


def test_quad_lookahead_does_not_eat_letters():
    assert normalize(r'\quadratic') == r'\quadratic'
    assert normalize(r'\, x') == 'x'
    assert normalize(r'\,x') == 'x'      # D2 fix: symbol commands followed by a letter


def test_majority_wins_and_highest_logprob_among_copies():
    reads = [r('x+1', -0.01, 1.0), r(r'x\,+1', -0.0001, 0.75), r('x-1', -0.00001, 0.55)]
    chosen, n = choose(reads)
    assert n == 2 and chosen['scale'] == 0.75   # majority beats the single higher-scoring outlier


def test_no_majority_takes_highest_logprob():
    reads = [r('a', -0.5), r('b', -0.01), r('c', -0.2)]
    chosen, n = choose(reads)
    assert n == 1 and chosen['latex'] == 'b'


def test_confidence_requires_agreement_and_threshold():
    assert confidence(r('x', GOOD), 2, 3)['level'] == 'higher'
    assert confidence(r('x', GOOD), 3, 3)['level'] == 'higher'
    assert confidence(r('x', LOW), 3, 3)['level'] == 'uncertain'    # agreement alone is not enough
    assert confidence(r('x', 0.0), 1, 3)['level'] == 'uncertain'    # score alone is not enough
    assert confidence(r('x', config.LOGPROB_THRESHOLD), 2, 3)['level'] == 'higher'  # inclusive


def test_confidence_messages_always_warn_and_never_claim_verification():
    for level_args in ((r('x', GOOD), 3, 3), (r('x', LOW), 1, 3)):
        msg = confidence(*level_args)['message'].lower()
        for banned in ('verified', 'safe', 'correctness checked', '%'):
            assert banned not in msg
    assert 'can still' in confidence(r('x', GOOD), 3, 3)['message']


def test_alternatives_are_distinct_model_outputs_with_counts():
    reads = [r('x+1', -0.1, 1.0), r(r'x\,+1', -0.01, 0.75), r('x-1', -0.001, 0.55)]
    chosen, _ = choose(reads)
    alts = alternatives(reads, chosen)
    assert alts[0] == {'latex': r'x\,+1', 'count': 2}
    assert alts[1] == {'latex': 'x-1', 'count': 1}
    assert sum(a['count'] for a in alts) == 3
    assert {a['latex'] for a in alts} <= {x['latex'] for x in reads}
