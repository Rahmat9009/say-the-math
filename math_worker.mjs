// Say the Math: local LaTeX -> MathML -> spoken English worker.
//
// Runs MathJax 4 (TeX input only, fixed package list, no autoload/require/html) and
// Speech Rule Engine (ClearSpeak, English) from the local node_modules. No network: every
// socket connection attempt in this process is refused and counted.
//
// Protocol: one JSON object per line on stdin, one JSON object per line on stdout.
//   {"id": 1, "op": "ping"}
//   {"id": 2, "op": "convert", "latex": "\\frac{x+1}{2}"}
// Replies:
//   {"id": 1, "ok": true, "versions": {...}, "blocked_connections": 0}
//   {"id": 2, "ok": true, "mathml": "...", "speech": "...", "root_id": "m0", "nodes": [...], "truncated": false}
//   {"id": 2, "ok": false, "code": "MATH_CONVERSION_FAILED", "message": "..."}
// Diagnostics go to stderr and never contain the LaTeX being converted.

import net from 'node:net';
import readline from 'node:readline';
import {createRequire} from 'node:module';

// ---- no network ---------------------------------------------------------------------------
let blockedConnections = 0;
const refuse = function () {
  blockedConnections += 1;
  throw new Error('Network access is disabled in the Say the Math math worker.');
};
net.Socket.prototype.connect = refuse;
net.connect = refuse;
net.createConnection = refuse;
if (typeof globalThis.fetch === 'function') globalThis.fetch = async () => refuse();

const require = createRequire(import.meta.url);
const {DOMParser, XMLSerializer} = require('@xmldom/xmldom');
const SRE = require('speech-rule-engine');
const {init} = require('@mathjax/src/bundle/node-main.cjs');

const TEX_PACKAGES = ['base', 'ams', 'boldsymbol', 'textmacros', 'cancel', 'mathtools'];
const MathJax = await init({
  loader: {require, load: ['input/tex-base', '[tex]/ams', '[tex]/boldsymbol', '[tex]/textmacros', '[tex]/cancel', '[tex]/mathtools']},
  tex: {packages: TEX_PACKAGES, formatError: (jax, err) => { throw err; }},
  startup: {typeset: false},
});
await SRE.setupEngine({locale: 'en', domain: 'clearspeak', modality: 'speech'});
await SRE.engineReady();

const MAX_LATEX = 2000;
const MAX_NODES = 300;
const MAX_DEPTH = 24;
const MML_NS = 'http://www.w3.org/1998/Math/MathML';

// Elements that may appear in returned MathML. Anything else is a conversion failure.
const ALLOWED = new Set(['math', 'mrow', 'mi', 'mn', 'mo', 'mtext', 'ms', 'mspace', 'mfrac', 'msqrt', 'mroot',
  'msup', 'msub', 'msubsup', 'munder', 'mover', 'munderover', 'mmultiscripts', 'mprescripts', 'none',
  'mtable', 'mtr', 'mlabeledtr', 'mtd', 'mstyle', 'mpadded', 'mphantom', 'menclose', 'merror', 'semantics',
  'annotation', 'annotation-xml', 'maction', 'mglyph']);
// Attributes kept on returned MathML. data-*, class, style, id, href and event handlers are dropped.
const KEEP_ATTRS = new Set(['xmlns', 'display', 'mathvariant', 'stretchy', 'fence', 'separator', 'accent',
  'accentunder', 'largeop', 'movablelimits', 'symmetric', 'lspace', 'rspace', 'minsize', 'maxsize', 'form',
  'linethickness', 'width', 'height', 'depth', 'columnalign', 'rowalign', 'columnspacing', 'rowspacing',
  'columnlines', 'rowlines', 'frame', 'framespacing', 'displaystyle', 'scriptlevel', 'notation',
  'voffset', 'columnspan', 'rowspan', 'mathsize', 'encoding', 'texclass']);

const BIG_OPERATORS = new Set(['∫', '∬', '∭', '⨌', '∮', '∯', '∰', '∑', '∏', '∐', '⋃', '⋂', '⨁', '⨂', '⨀', '⨄', '⨆', '⋁', '⋀']);
const LIMIT_NAMES = new Set(['lim', 'max', 'min', 'sup', 'inf', 'lim sup', 'lim inf', 'limsup', 'liminf', 'det', 'gcd', 'Pr', 'arg max', 'arg min']);
const PRIME_LIKE = new Set(['′', '″', '‴', '⁗', '*', '∗', '†', '‡', '∘', "'"]);
const OPEN_FENCES = new Set(['(', '[', '{', '|', '‖', '⟨', '⌊', '⌈']);
const CLOSE_FENCES = new Set([')', ']', '}', '|', '‖', '⟩', '⌋', '⌉']);

const PREFIX = {
  equation: 'Equation', group: 'Group', fenced: 'Bracketed group', fraction: 'Fraction', numerator: 'Numerator',
  denominator: 'Denominator', power: 'Power', superscripted: 'Superscript expression', subscripted: 'Subscript expression',
  scripted: 'Scripted expression', bounded_operator: 'Operator with bounds', under_over: 'Expression with limits',
  accent: 'Accented expression', square_root: 'Square root', root: 'Root', radicand: 'Radicand', index: 'Root index',
  base: 'Base', exponent: 'Exponent', superscript: 'Superscript', subscript: 'Subscript', lower_bound: 'Lower bound',
  upper_bound: 'Upper bound', condition: 'Condition', under_script: 'Under script', over_script: 'Over script',
  accent_mark: 'Accent mark', table: 'Table', table_row: 'Row', table_cell: 'Cell', enclosed: 'Enclosed expression',
  identifier: 'Variable', name: 'Name', number: 'Number', operator: 'Operator', text: 'Text', script_part: 'Script part',
};

const elementChildren = (el) => Array.from(el.childNodes || []).filter((n) => n.nodeType === 1);
const tag = (el) => (el.localName || el.nodeName || '').toLowerCase();
const text = (el) => (el.textContent || '').trim();
const isToken = (el) => ['mi', 'mn', 'mo', 'mtext', 'ms'].includes(tag(el));

function cleanTree(el) {
  const name = tag(el);
  if (!ALLOWED.has(name)) throw new Error(`Unsupported MathML element <${name}>`);
  if (name === 'merror') throw new Error('MathJax reported an error in the LaTeX');
  for (const attr of Array.from(el.attributes || [])) {
    if (!KEEP_ATTRS.has(attr.name)) el.removeAttribute(attr.name);
  }
  if (!isToken(el)) {
    for (const n of Array.from(el.childNodes || [])) {
      if (n.nodeType === 3 && !n.nodeValue.trim()) el.removeChild(n);
      else if (n.nodeType === 8) el.removeChild(n);
    }
  }
  for (const child of elementChildren(el)) cleanTree(child);
}

// Remove presentation-only wrappers so navigation follows meaning.
function unwrap(el) {
  let cur = el;
  for (;;) {
    const name = tag(cur);
    const kids = elementChildren(cur).filter((k) => !['mspace', 'mphantom'].includes(tag(k)));
    if ((name === 'mrow' || name === 'mstyle' || name === 'mpadded') && kids.length === 1) { cur = kids[0]; continue; }
    if ((name === 'semantics' || name === 'maction') && kids.length >= 1) { cur = kids[0]; continue; }
    return cur;
  }
}

const INVISIBLE = new Set(['⁡', '⁢', '⁣', '⁤', '']);
const skipInTree = (k) => ['mspace', 'mphantom', 'annotation', 'annotation-xml', 'none', 'mprescripts'].includes(tag(k))
  || (tag(k) === 'mo' && INVISIBLE.has(text(k)));
function contentChildren(el) {
  return elementChildren(el).map(unwrap).filter((k) => !skipInTree(k));
}

const serializer = new XMLSerializer();
const NS_ATTR = ` xmlns="${MML_NS}"`;
const serialize = (e) => serializer.serializeToString(e).split(NS_ATTR).join('');
function asMath(elements) {
  const inner = elements.map(serialize).join('');
  const body = elements.length === 1 ? inner : `<mrow>${inner}</mrow>`;
  return `<math xmlns="${MML_NS}">${body}</math>`;
}

const speechCache = new Map();
function speak(mathml) {
  if (speechCache.has(mathml)) return speechCache.get(mathml);
  let s = '';
  try { s = String(SRE.toSpeech(mathml) || '').trim(); } catch (e) { s = ''; }
  if (speechCache.size > 2000) speechCache.clear();
  speechCache.set(mathml, s);
  return s;
}

function baseText(el) {
  const u = unwrap(el);
  return isToken(u) ? text(u) : '';
}

function leafKind(el) {
  const name = tag(el);
  if (name === 'mn') return 'number';
  if (name === 'mo') return 'operator';
  if (name === 'mtext' || name === 'ms') return 'text';
  if (name === 'mi') return text(el).length > 1 ? 'name' : 'identifier';
  return 'group';
}

function isFenced(kids) {
  if (kids.length < 2) return false;
  const a = kids[0], b = kids[kids.length - 1];
  return tag(a) === 'mo' && tag(b) === 'mo' && OPEN_FENCES.has(text(a)) && CLOSE_FENCES.has(text(b));
}

// Describe the structural kind of an element and its (role, element-list) children.
function structure(el) {
  const name = tag(el);
  const kids = contentChildren(el);
  switch (name) {
    case 'mfrac':
      return {kind: 'fraction', parts: [['numerator', [kids[0]]], ['denominator', [kids[1]]]]};
    case 'msqrt':
      return {kind: 'square_root', parts: [['radicand', kids]]};
    case 'mroot':
      return {kind: 'root', parts: [['radicand', [kids[0]]], ['index', [kids[1]]]]};
    case 'msup': {
      const sup = baseText(kids[1]);
      const prime = PRIME_LIKE.has(sup);
      return {kind: prime ? 'superscripted' : 'power', parts: [['base', [kids[0]]], [prime ? 'superscript' : 'exponent', [kids[1]]]]};
    }
    case 'msub': {
      const b = baseText(kids[0]);
      if (BIG_OPERATORS.has(b)) return {kind: 'bounded_operator', parts: [['base', [kids[0]]], ['lower_bound', [kids[1]]]]};
      return {kind: 'subscripted', parts: [['base', [kids[0]]], ['subscript', [kids[1]]]]};
    }
    case 'msubsup': {
      const b = baseText(kids[0]);
      if (BIG_OPERATORS.has(b)) return {kind: 'bounded_operator', parts: [['base', [kids[0]]], ['lower_bound', [kids[1]]], ['upper_bound', [kids[2]]]]};
      return {kind: 'scripted', parts: [['base', [kids[0]]], ['subscript', [kids[1]]], ['exponent', [kids[2]]]]};
    }
    case 'munder': {
      const b = baseText(kids[0]);
      if (BIG_OPERATORS.has(b)) return {kind: 'bounded_operator', parts: [['base', [kids[0]]], ['lower_bound', [kids[1]]]]};
      if (LIMIT_NAMES.has(b)) return {kind: 'under_over', parts: [['base', [kids[0]]], ['condition', [kids[1]]]]};
      return {kind: 'under_over', parts: [['base', [kids[0]]], ['under_script', [kids[1]]]]};
    }
    case 'mover': {
      const b = baseText(kids[0]);
      if (BIG_OPERATORS.has(b)) return {kind: 'bounded_operator', parts: [['base', [kids[0]]], ['upper_bound', [kids[1]]]]};
      const accent = el.getAttribute('accent') === 'true' || (tag(kids[1]) === 'mo' && text(kids[1]).length === 1);
      if (accent) return {kind: 'accent', parts: [['base', [kids[0]]], ['accent_mark', [kids[1]]]]};
      return {kind: 'under_over', parts: [['base', [kids[0]]], ['over_script', [kids[1]]]]};
    }
    case 'munderover': {
      const b = baseText(kids[0]);
      if (BIG_OPERATORS.has(b)) return {kind: 'bounded_operator', parts: [['base', [kids[0]]], ['lower_bound', [kids[1]]], ['upper_bound', [kids[2]]]]};
      return {kind: 'under_over', parts: [['base', [kids[0]]], ['under_script', [kids[1]]], ['over_script', [kids[2]]]]};
    }
    case 'mmultiscripts':
      return {kind: 'scripted', parts: [['base', [kids[0]]], ...kids.slice(1).map((k) => ['script_part', [k]])]};
    case 'mtable':
      return {kind: 'table', rows: kids};
    case 'mtr':
    case 'mlabeledtr':
      return {kind: 'table_row', cells: kids};
    case 'menclose':
      return {kind: 'enclosed', parts: [['enclosed_body', kids]]};
    case 'mrow':
    case 'mstyle':
    case 'mpadded':
    case 'math':
      return {kind: isFenced(kids) ? 'fenced' : 'group', items: kids};
    default:
      return {kind: leafKind(el), items: []};
  }
}

function buildTree(mathEl, fullMathml) {
  const nodes = [];
  let truncated = false;
  const newNode = (parent, kind, elements, mathml) => {
    const id = `m${nodes.length}`;
    const mml = mathml || asMath(elements);
    const spoken = speak(mml) || (elements.length === 0 ? 'empty' : '');
    const prefix = PREFIX[kind] || 'Part';
    const node = {id, parent, children: [], kind, label: spoken ? `${prefix}: ${spoken}` : `${prefix}: empty`, mathml: mml};
    nodes.push(node);
    if (parent !== null) nodes[Number(parent.slice(1))].children.push(id);
    return node;
  };
  const room = () => nodes.length < MAX_NODES;

  // Add the children describing element list `els` below `node`.
  const expandList = (node, els, depth) => {
    if (els.length === 1) {
      const only = unwrap(els[0]);
      if (isToken(only)) return; // the role label already carries the token
      const s = structure(only);
      if (s.kind === 'group' && s.items.length > 0) { s.items.forEach((k) => addElement(node, k, depth)); return; }
      addElement(node, only, depth);
      return;
    }
    els.forEach((k) => addElement(node, k, depth));
  };

  const addElement = (parentNode, el, depth) => {
    if (!room() || depth > MAX_DEPTH) { truncated = true; return; }
    el = unwrap(el);
    const s = structure(el);
    const node = newNode(parentNode.id, s.kind, [el]);
    if (s.parts) {
      for (const [role, els] of s.parts) {
        if (!room()) { truncated = true; return; }
        const valid = els.filter(Boolean);
        const roleKind = role === 'enclosed_body' ? 'group' : role;
        const roleNode = newNode(node.id, roleKind, valid);
        expandList(roleNode, valid, depth + 2);
      }
    } else if (s.rows) {
      s.rows.forEach((r) => addElement(node, r, depth + 1));
    } else if (s.cells) {
      for (const cell of s.cells) {
        if (!room()) { truncated = true; return; }
        const cellKids = contentChildren(cell);
        const cellNode = newNode(node.id, 'table_cell', cellKids);
        expandList(cellNode, cellKids, depth + 2);
      }
    } else if (s.items && s.items.length) {
      s.items.forEach((k) => addElement(node, k, depth + 1));
    }
  };

  const root = newNode(null, 'equation', [], fullMathml);
  expandList(root, contentChildren(mathEl), 1);
  return {root_id: root.id, nodes, truncated};
}

function convert(latex) {
  if (typeof latex !== 'string' || !latex.trim()) throw new Error('Empty LaTeX');
  if (latex.length > MAX_LATEX) throw new Error('LaTeX too long');
  const raw = MathJax.tex2mml(latex, {display: true});
  const doc = new DOMParser({onError: (level, msg) => { if (level !== 'warning') throw new Error(`Invalid MathML: ${msg}`); }})
    .parseFromString(raw, 'application/xml');
  const mathEl = doc.documentElement;
  if (!mathEl || tag(mathEl) !== 'math') throw new Error('MathJax did not return a math element');
  cleanTree(mathEl);
  mathEl.setAttribute('xmlns', MML_NS);
  const mathml = serializer.serializeToString(mathEl);  // root keeps its xmlns
  const speech = speak(mathml);
  if (!speech) throw new Error('Speech Rule Engine returned no speech');
  const tree = buildTree(mathEl, mathml);
  return {mathml, speech, ...tree};
}

function versions() {
  const pkg = (name) => { try { return require(`${name}/package.json`).version; } catch { return null; } };
  return {node: process.versions.node, mathjax: MathJax.version || pkg('@mathjax/src'), sre: SRE.version || pkg('speech-rule-engine'),
    xmldom: pkg('@xmldom/xmldom'), tex_packages: TEX_PACKAGES, sre_domain: 'clearspeak', sre_locale: 'en'};
}

const out = (obj) => process.stdout.write(JSON.stringify(obj) + '\n');
const rl = readline.createInterface({input: process.stdin});
out({id: 0, ok: true, ready: true, versions: versions()});
for await (const line of rl) {
  if (!line.trim()) continue;
  let job;
  try { job = JSON.parse(line); } catch { out({id: null, ok: false, code: 'BAD_REQUEST', message: 'Malformed worker request'}); continue; }
  if (job.op === 'ping') { out({id: job.id, ok: true, versions: versions(), blocked_connections: blockedConnections}); continue; }
  if (job.op !== 'convert') { out({id: job.id, ok: false, code: 'BAD_REQUEST', message: 'Unknown operation'}); continue; }
  try {
    out({id: job.id, ok: true, ...convert(job.latex)});
  } catch (e) {
    const msg = String((e && e.message) || e).replace(/\s+/g, ' ').slice(0, 300);
    out({id: job.id, ok: false, code: 'MATH_CONVERSION_FAILED', message: msg});
  }
}
