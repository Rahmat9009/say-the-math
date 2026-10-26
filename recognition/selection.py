"""Choose one reading from the three scales and decide the confidence level. No reference labels."""
from collections import Counter

from . import config
from .normalize import vote_key


def choose(reads):
    """reads: list of {'scale', 'latex', 'lp_mean'} -> (chosen read, number agreeing with it).

    A normalized transcription produced by at least two scales wins; among its copies take the highest
    raw mean token log probability. With no majority, take the highest log probability overall.
    """
    keys = [vote_key(r['latex']) for r in reads]
    top, n = Counter(keys).most_common(1)[0]
    if n >= 2:
        pool = [r for r, k in zip(reads, keys) if k == top]
    else:
        pool = list(reads)
    return max(pool, key=lambda r: r['lp_mean']), n


def confidence(chosen, agreeing, total):
    higher = agreeing >= config.MIN_AGREEING and chosen['lp_mean'] >= config.LOGPROB_THRESHOLD
    return {
        'level': 'higher' if higher else 'uncertain',
        'message': config.HIGHER_MESSAGE if higher else config.UNCERTAIN_MESSAGE,
        'agreeing_reads': agreeing,
        'total_reads': total,
    }


def alternatives(reads, chosen):
    """Distinct model transcriptions (by normalized key) with counts; the chosen reading first."""
    groups = {}
    for r in reads:
        k = vote_key(r['latex'])
        g = groups.setdefault(k, {'reads': [], 'count': 0})
        g['reads'].append(r)
        g['count'] += 1
    out = []
    chosen_key = vote_key(chosen['latex'])
    for k, g in groups.items():
        best = chosen if k == chosen_key else max(g['reads'], key=lambda r: r['lp_mean'])
        out.append({'latex': best['latex'], 'count': g['count'], '_chosen': k == chosen_key, '_lp': best['lp_mean']})
    out.sort(key=lambda a: (not a['_chosen'], -a['count'], -a['_lp']))
    return [{'latex': a['latex'], 'count': a['count']} for a in out]
