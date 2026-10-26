"""Shared structural checks for the MathML, speech and node tree returned by the backend."""
import xml.etree.ElementTree as ET

MML = '{http://www.w3.org/1998/Math/MathML}'
ALLOWED = {'math', 'mrow', 'mi', 'mn', 'mo', 'mtext', 'ms', 'mspace', 'mfrac', 'msqrt', 'mroot', 'msup', 'msub',
           'msubsup', 'munder', 'mover', 'munderover', 'mmultiscripts', 'mprescripts', 'none', 'mtable', 'mtr',
           'mlabeledtr', 'mtd', 'mstyle', 'mpadded', 'mphantom', 'menclose', 'semantics', 'annotation',
           'annotation-xml', 'maction', 'mglyph'}


def check_mathml(s):
    root = ET.fromstring(s)
    assert root.tag == MML + 'math', root.tag
    for el in root.iter():
        assert el.tag.startswith(MML), el.tag
        assert el.tag[len(MML):] in ALLOWED, el.tag
        for attr in el.attrib:
            low = attr.lower()
            assert not low.startswith('on') and not low.startswith('data-'), attr
            assert low not in ('href', 'style', 'class', 'id', 'src') and 'href' not in low, attr
    return root


def check_tree(result, max_nodes=300):
    nodes = result['nodes']
    assert 0 < len(nodes) <= max_nodes
    by_id = {n['id']: n for n in nodes}
    assert len(by_id) == len(nodes), 'duplicate ids'
    roots = [n for n in nodes if n['parent'] is None]
    assert len(roots) == 1 and roots[0]['id'] == result['root_id']
    for n in nodes:
        assert set(n) == {'id', 'parent', 'children', 'kind', 'label', 'mathml'}
        assert isinstance(n['label'], str) and n['label'].strip() and ':' in n['label']
        if n['parent'] is not None:
            assert n['id'] in by_id[n['parent']]['children']
        for c in n['children']:
            assert by_id[c]['parent'] == n['id']
        check_mathml(n['mathml'])
    seen, stack = set(), [result['root_id']]
    while stack:
        i = stack.pop()
        assert i not in seen, 'cycle'
        seen.add(i)
        stack.extend(by_id[i]['children'])
    assert seen == set(by_id), 'unreachable nodes'
    assert roots[0]['mathml'] == result['mathml']
    return by_id


def kinds(result):
    return [n['kind'] for n in result['nodes']]


def child_kinds(by_id, node):
    return [by_id[c]['kind'] for c in node['children']]
