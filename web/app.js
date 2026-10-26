'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const MAX_BYTES = 8 * 1024 * 1024;
  let epoch = 0, selected = null, imageURL = null, ready = false, busy = false;
  let request = null, result = null, tree = new Map(), active = null;
  let expanded = new Set(), statusEpoch = 0, announcementTimer;
  let pdf = null;
  const regionAnnouncement = () => selected?.pdf ? 'Detected region: completeness unknown. A higher-confidence transcription does not mean the whole equation is present. ' : '';

  function announce(message) {
    clearTimeout(announcementTimer);
    $('announcement').textContent = '';
    announcementTimer = setTimeout(() => { $('announcement').textContent = message; }, 70);
  }
  function message(text, focus = false, code = '') {
    $('visible-message').textContent = text;
    $('visible-message').dataset.errorCode = code || '';
    $('visible-message').hidden = !text;
    $('return-to-pdf').hidden = !text || !(selected?.pdf || code?.startsWith('PDF_'));
    $('return-to-input').hidden = !text || !selected || selected.pdf === true;
    if (text) { announce(text); if (focus) $('visible-message').focus(); }
  }
  function controls() {
    const disabled = !selected || !ready || busy || (selected.pdf && selected.candidate.layout !== 'single-line');
    $('read-button').disabled = disabled;
    $('read-pdf-candidate').disabled = disabled;
    $('output-card').setAttribute('aria-busy', String(busy));
  }
  function invalidate() {
    epoch++;
    request?.abort(); request = null; busy = false; result = null;
    tree.clear(); active = null; expanded.clear();
    $('result').hidden = true; $('working-state').hidden = true; $('empty-state').hidden = false;
    $('math-display').replaceChildren(); $('math-tree').replaceChildren();
    $('math-tree').removeAttribute('aria-activedescendant');
    $('alternative-list').replaceChildren(); $('spoken-text').textContent = ''; $('latex-text').textContent = '';
    announce(''); message(''); controls();
  }
  function clearImage(focus = true, keepPDF = false) {
    if (!keepPDF) pdf?.close(false);
    invalidate(); selected = null;
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = null; $('source-image').removeAttribute('src'); $('image-input').value = '';
    $('image-preview').hidden = true; $('drop-zone').hidden = false;
    $('output-region').hidden = true;
    $('change-button').textContent = 'Change image'; $('reset-button').textContent = 'Clear image';
    $('source-image').alt = 'Selected equation image. Its recognized reading will appear after processing.';
    $('input-hint').textContent = 'Use a tight crop with the whole equation visible.';
    controls(); if (focus) $('choose-button').focus();
  }
  async function selectFiles(files) {
    const restoreFocus = $('image-preview').contains(document.activeElement) || $('output-card').contains(document.activeElement);
    clearImage(false);
    if (restoreFocus) $('choose-button').focus();
    const ticket = epoch;
    if (files.length !== 1) { message('Choose or paste exactly one equation image.', true); return; }
    const file = files[0];
    if (!file.size || file.size > MAX_BYTES) { message('Choose an image up to 8 MiB (8,388,608 bytes). Empty files cannot be read.', true); return; }
    $('input-hint').textContent = 'Preparing the image…'; announce('Preparing the image.');
    let temporaryURL;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (ticket !== epoch) return;
      const png = bytes.length >= 8 && [137,80,78,71,13,10,26,10].every((v,i) => bytes[i] === v);
      const jpeg = bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
      const webp = String.fromCharCode(...bytes.slice(0,4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8,12)) === 'WEBP';
      if (!png && !jpeg && !webp) throw new Error('Choose one PNG, JPG or WebP equation image. Use Choose a PDF for experimental PDF navigation.');
      temporaryURL = URL.createObjectURL(file);
      const image = new Image(); image.src = temporaryURL;
      await image.decode();
      if (ticket !== epoch) { URL.revokeObjectURL(temporaryURL); return; }
      if (image.naturalWidth * image.naturalHeight > 16000000) throw new Error('Choose an image with at most 16 million pixels.');
      imageURL = temporaryURL;
      selected = { file, bytes };
      $('source-image').src = imageURL;
      $('file-name').textContent = file.name || 'Pasted equation image';
      $('file-name').title = file.name || 'Pasted equation image';
      $('image-preview').hidden = false; $('drop-zone').hidden = true;
      $('input-hint').textContent = 'Image ready. Choose Read equation when the local reader is ready.';
      controls(); announce('Image ready. ' + (ready ? 'Choose Read equation.' : 'The local reader needs setup.'));
      $('read-button').disabled ? $('change-button').focus() : $('read-button').focus();
    } catch (error) {
      if (temporaryURL) URL.revokeObjectURL(temporaryURL);
      if (ticket !== epoch) return;
      $('input-hint').textContent = 'Use a tight crop with the whole equation visible.';
      message(error instanceof Error && !/decode/i.test(error.message) ? error.message : 'This image could not be opened. Choose another PNG, JPG or WebP image.', true);
    }
  }

  async function api(path, body, controller, timeout = 180000) {
    const timer = setTimeout(() => controller.abort('timeout'), timeout);
    try {
      const response = await fetch(path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined, signal: controller.signal, cache: 'no-store', credentials: 'same-origin' });
      let data;
      try { data = await response.json(); } catch { throw new Error('The local reader returned an unreadable response. Check the reader and try again.'); }
      if (!response.ok) {
        const code = data?.error?.code;
        const recovery = {
          RECOGNITION_TIMEOUT: ' Try a tighter crop that still includes the whole equation, or choose another candidate.',
          RECOGNITION_CANCELLED: ' Choose another candidate or image, or try again.',
          PDF_DISCOVERY_TIMEOUT: ' Try a shorter PDF or an already-cropped equation image.',
          PDF_CANCELLED: ' Choose a PDF to start again.'
        };
        const suffix = code === 'BUSY' ? (path === '/api/pdf/open' ? ' Wait for PDF discovery to finish, then try again.' : ' Wait for the current recognition or initial model loading to finish, then try again.') : recovery[code] || '';
        const error = new Error((typeof data?.error?.message === 'string' && data.error.message.trim() ? data.error.message.slice(0,1500) : 'The local reader could not complete this request.') + suffix);
        error.code = code; throw error;
      }
      return data;
    } catch (error) {
      if (controller.signal.aborted && controller.signal.reason === 'timeout') {
        const timeoutError = new Error('The local reader took too long to respond. It may still be working. Check its status before trying again.');
        timeoutError.code = 'CLIENT_TIMEOUT'; throw timeoutError;
      }
      if (error instanceof TypeError) {
        const unreachable = new Error('Cannot reach the local reader. Start it on this computer, then check its status again.');
        unreachable.code = 'UNREACHABLE'; throw unreachable;
      }
      throw error;
    } finally { clearTimeout(timer); }
  }
  function updateUnavailable(error) {
    if (error.code !== 'NOT_READY' && error.code !== 'UNREACHABLE') return;
    ready = false;
    $('engine-status').textContent = error.message; $('engine-status').classList.add('error');
    $('engine-detail').textContent = error.message; $('setup-help').open = true; controls();
  }
  async function checkStatus() {
    const ticket = ++statusEpoch; ready = false; controls();
    $('engine-status').textContent = 'Checking the local reader…';
    $('retry-status').disabled = true;
    try {
      const data = await api('/api/status', null, new AbortController(), 15000);
      if (ticket !== statusEpoch) return;
      if (typeof data?.ready !== 'boolean' || typeof data?.message !== 'string') throw new Error('The local reader returned an invalid status response.');
      ready = data.ready && data.model_available === true && data.math_available === true;
      $('engine-status').textContent = data.message;
      $('engine-detail').textContent = ready ? 'The local reader can attempt recognition. Its first reading may take longer while the model loads.' : data.message;
    } catch (error) {
      if (ticket !== statusEpoch) return;
      $('engine-status').textContent = error.message; $('engine-detail').textContent = error.message;
    } finally {
      if (ticket === statusEpoch) {
        $('retry-status').disabled = false; $('engine-status').classList.toggle('error', !ready);
        $('setup-help').open = !ready; controls();
      }
    }
  }

  const mathNS = 'http://www.w3.org/1998/Math/MathML';
  const tags = new Set('math mrow mi mn mo mtext mspace ms mfrac msqrt mroot msup msub msubsup mover munder munderover mfenced menclose mtable mtr mtd mlabeledtr mstyle mpadded mphantom mmultiscripts mprescripts none semantics annotation'.split(' '));
  const attributes = new Set('display mathvariant mathsize mathcolor mathbackground stretchy symmetric fence separator accent accentunder largeop movablelimits form lspace rspace width height depth linethickness bevelled notation open close separators columnalign rowalign columnspacing rowspacing columnlines rowlines frame equalrows equalcolumns scriptlevel displaystyle subscriptshift superscriptshift encoding'.split(' '));
  function safeMath(source) {
    if (typeof source !== 'string' || source.length > 300000 || /<!DOCTYPE|<!ENTITY/i.test(source)) throw new Error('The reading contains invalid mathematical markup.');
    const parsed = new DOMParser().parseFromString(source, 'application/xml');
    const root = parsed.documentElement;
    if (parsed.querySelector('parsererror') || root.localName !== 'math') throw new Error('The reading could not be displayed as MathML.');
    let count = 0;
    function copy(node, depth) {
      if (++count > 5000 || depth > 80) throw new Error('The mathematical display is too complex for this reader.');
      if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
      if (node.nodeType !== Node.ELEMENT_NODE || !tags.has(node.localName) || (node.namespaceURI && node.namespaceURI !== mathNS)) throw new Error('The reading contains unsupported mathematical markup.');
      const element = document.createElementNS(mathNS, node.localName);
      for (const attribute of node.attributes) {
        // Reconstruct only inert MathML attributes. Never carry IDs, URLs, CSS, events or HTML across.
        if (attributes.has(attribute.name) && /^[\w\s.,()+%#−-]{0,160}$/u.test(attribute.value)) element.setAttribute(attribute.name, attribute.value);
      }
      for (const child of node.childNodes) {
        if (child.nodeType === Node.COMMENT_NODE) continue;
        element.append(copy(child, depth + 1));
      }
      return element;
    }
    return copy(root, 0);
  }
  function validate(data, recognition) {
    const fail = () => { throw new Error('The local reader returned an incomplete or invalid equation. Try another image or restart the reader.'); };
    if (!data || typeof data.latex !== 'string' || !data.latex.trim() || data.latex.length > 2000 || typeof data.speech !== 'string' || !data.speech.trim() || data.speech.length > 50000 || !Array.isArray(data.nodes) || !data.nodes.length || data.nodes.length > 2000) fail();
    const display = safeMath(data.mathml);
    const nodes = new Map();
    for (const node of data.nodes) {
      if (!node || typeof node.id !== 'string' || !node.id || node.id.length > 100 || nodes.has(node.id) || typeof node.label !== 'string' || !node.label.trim() || node.label.length > 10000 || typeof node.kind !== 'string' || !Array.isArray(node.children) || node.children.some(id => typeof id !== 'string') || !(node.parent === null || typeof node.parent === 'string')) fail();
      nodes.set(node.id, node);
    }
    const root = nodes.get(data.root_id);
    if (!root || root.parent !== null) fail();
    const visited = new Set();
    function visit(node, depth) {
      if (depth > 80 || visited.has(node.id)) fail();
      visited.add(node.id);
      for (const id of node.children) {
        const child = nodes.get(id);
        if (!child || child.parent !== node.id) fail();
        visit(child, depth + 1);
      }
    }
    visit(root, 0); if (visited.size !== nodes.size) fail();
    if (recognition) {
      const c = data.confidence;
      if (!c || !['higher','uncertain'].includes(c.level) || typeof c.message !== 'string' || !Number.isInteger(c.agreeing_reads) || c.agreeing_reads < 1 || c.agreeing_reads > 3 || c.total_reads !== 3 || (c.level === 'higher' && c.agreeing_reads < 2) || !Array.isArray(data.alternatives) || !data.alternatives.length || data.alternatives.length > 3) fail();
      let total = 0; const seen = new Set();
      for (const alt of data.alternatives) {
        if (typeof alt?.latex !== 'string' || !alt.latex.trim() || alt.latex.length > 2000 || seen.has(alt.latex) || !Number.isInteger(alt.count) || alt.count < 1 || alt.count > 3) fail();
        total += alt.count; seen.add(alt.latex);
      }
      if (total !== 3 || !seen.has(data.latex)) fail();
    }
    return { display, nodes };
  }

  function visibleNodes() {
    const list = [];
    function walk(id) { list.push(id); if (expanded.has(id)) tree.get(id).children.forEach(walk); }
    if (result) walk(result.root_id);
    return list;
  }
  function renderTree() {
    const fragment = document.createDocumentFragment();
    function branch(id, level, position, size) {
      const node = tree.get(id), item = document.createElement('div');
      item.id = 'part-' + [...tree.keys()].indexOf(id);
      item.setAttribute('role','treeitem'); item.setAttribute('aria-level',level);
      item.setAttribute('aria-posinset',position); item.setAttribute('aria-setsize',size);
      item.setAttribute('aria-selected',String(id === active));
      if (node.children.length) item.setAttribute('aria-expanded',String(expanded.has(id)));
      const label = document.createElement('span'); label.textContent = node.label;
      item.append(label); item.setAttribute('aria-label',node.label);
      label.style.paddingLeft = `${9 + Math.min(level - 1, 8) * 16}px`;
      item.addEventListener('click', event => { event.stopPropagation(); activate(id, true); });
      if (node.children.length) {
        const group = document.createElement('div'); group.setAttribute('role','group'); group.hidden = !expanded.has(id);
        node.children.forEach((child, i) => group.append(branch(child, level + 1, i + 1, node.children.length)));
        item.append(group);
      }
      return item;
    }
    fragment.append(branch(result.root_id,1,1,1));
    $('math-tree').replaceChildren(fragment);
    $('math-tree').setAttribute('aria-activedescendant','part-' + [...tree.keys()].indexOf(active));
    const node = tree.get(active), list = visibleNodes(), i = list.indexOf(active);
    $('parent-button').disabled = node.parent === null; $('child-button').disabled = !node.children.length;
    $('previous-button').disabled = i === 0; $('next-button').disabled = i === list.length - 1;
  }
  function activate(id, focus = false, speak = false) {
    if (!tree.has(id)) return;
    active = id; renderTree();
    if (focus) $('math-tree').focus();
    document.getElementById($('math-tree').getAttribute('aria-activedescendant'))?.scrollIntoView({ block: 'nearest' });
    if (speak) announce(tree.get(id).label);
  }
  function move(direction, focus = false) {
    if (!result || busy) return;
    const node = tree.get(active), list = visibleNodes(), i = list.indexOf(active);
    if (direction === 'parent' && node.parent !== null) activate(node.parent, focus);
    if (direction === 'child' && node.children.length) { expanded.add(active); activate(node.children[0], focus); }
    if (direction === 'previous' && i > 0) activate(list[i-1], focus);
    if (direction === 'next' && i < list.length-1) activate(list[i+1], focus);
  }
  function showResult(data, checked, manual = false) {
    result = data; tree = checked.nodes; active = data.root_id; expanded = new Set(tree.keys());
    $('math-display').replaceChildren(checked.display);
    $('spoken-text').textContent = data.speech; $('latex-text').textContent = data.latex;
    const higher = !manual && data.confidence.level === 'higher';
    const confidenceReason = !manual && !higher ? " Agreement alone is not enough for higher confidence; the model's score must also meet an experimental cutoff." : '';
    $('confidence').classList.toggle('higher',higher);
    $('confidence-title').textContent = higher ? 'Higher-confidence reading' : 'Uncertain reading';
    $('confidence-text').textContent = manual ? 'You selected an alternative model reading. Recognition can still change signs, exponents or roots. Compare it with the source.' : `${data.confidence.agreeing_reads} of 3 readings agree.${confidenceReason} Recognition can still change signs, exponents or roots. Compare this reading with the source.`;
    $('part-count').textContent = `${tree.size} parts`;
    $('structure-warning').hidden = data.tree_truncated !== true && data.truncated !== true;
    renderTree();
    $('result').hidden = false; $('empty-state').hidden = true; $('working-state').hidden = true;
    announce(`${regionAnnouncement()}${higher ? 'Higher-confidence' : 'Uncertain'} reading ready.${confidenceReason} Recognition can still change signs, exponents or roots. ${data.speech}`);
  }
  function renderAlternatives(alternatives) {
    $('alternative-list').replaceChildren();
    alternatives.forEach((alt, i) => {
      const row = document.createElement('div'); row.className = 'alternative';
      const label = document.createElement('p'); label.textContent = `Model reading ${i+1} · ${alt.count} of 3 reads`;
      const code = document.createElement('pre'); code.textContent = alt.latex;
      const button = document.createElement('button'); button.className = 'secondary'; button.textContent = `Use reading ${i+1}`;
      button.disabled = alt.latex === result.latex;
      if (button.disabled) label.append(document.createTextNode(' · Currently displayed'));
      button.addEventListener('click', () => formatAlternative(alt.latex, alternatives));
      row.append(label,code,button); $('alternative-list').append(row);
    });
    $('alternatives').open = false;
  }
  async function read() {
    if (!selected || !ready || busy || (selected.pdf && selected.candidate.layout !== 'single-line')) return;
    const current = selected; invalidate(); busy = true; const ticket = epoch;
    const controller = request = new AbortController();
    $('empty-state').hidden = true; $('working-state').hidden = false; controls();
    $('cancel-button').focus();
    announce(`${regionAnnouncement()}Reading the equation locally. Cancel stops recognition at the next model step. Initial model loading and checkpoint checks cannot be interrupted.`);
    try {
      let data;
      if (current.pdf) {
        data = await api('/api/pdf/read',{ document_id:current.document_id, equation_id:current.equation_id },controller);
      } else {
        let binary = '';
        for (let i=0;i<current.bytes.length;i+=32768) binary += String.fromCharCode(...current.bytes.subarray(i,i+32768));
        data = await api('/api/read',{ image_base64: btoa(binary), filename: (current.file.name || 'clipboard.png').split(/[\\/]/).pop() },controller);
      }
      if (ticket !== epoch) return;
      if (current.pdf && (data.document_id !== current.document_id || data.equation_id !== current.equation_id || data.region_completeness?.state !== 'unknown')) throw new Error('The PDF reading does not match the selected region. Select the candidate again.');
      const checked = validate(data,true);
      const shouldFocus = [ document.body, $('read-button'), $('read-pdf-candidate'), $('cancel-button') ].includes(document.activeElement);
      showResult(data,checked); renderAlternatives(data.alternatives);
      if (shouldFocus) $('result-title').focus();
    } catch (error) {
      if (ticket !== epoch) return;
      updateUnavailable(error);
      $('working-state').hidden = true; $('empty-state').hidden = false;
      message(error.message + (current.pdf && error.code === 'MATH_CONVERSION_FAILED' ? ' Return to PDF navigation to choose another candidate or retry.' : ''),true,error.code);
    } finally { if (ticket === epoch) { busy = false; request = null; controls(); } }
  }
  async function formatAlternative(latex, alternatives) {
    if (busy || !result) return;
    const ticket = epoch; const controller = request = new AbortController(); busy = true; controls();
    $('alternative-list').querySelectorAll('button').forEach(b => { b.disabled = true; });
    announce('Preparing the alternative reading.'); message('');
    try {
      const data = await api('/api/format',{latex},controller,30000);
      if (ticket !== epoch) return;
      if (data.latex !== latex) throw new Error('The local reader returned a different alternative. The prior reading is still displayed.');
      const checked = validate(data,false);
      showResult(data,checked,true); renderAlternatives(alternatives); $('result-title').focus();
    } catch (error) {
      if (ticket === epoch) { updateUnavailable(error); renderAlternatives(alternatives); $('alternatives').open = true; message(error.message,true); }
    } finally { if (ticket === epoch) { busy = false; request = null; controls(); } }
  }

  $('choose-button').addEventListener('click',() => { $('image-input').value = ''; $('image-input').click(); });
  $('change-button').addEventListener('click',() => { $('image-input').value = ''; $('image-input').click(); });
  $('image-input').addEventListener('change',() => { if ($('image-input').files.length) selectFiles([...$('image-input').files]); });
  $('reset-button').addEventListener('click',() => { if(selected?.pdf) { pdf?.close(); return; } clearImage(); announce('Image and reading cleared. Choose another image.'); });
  $('read-button').addEventListener('click',read);
  $('read-pdf-candidate').addEventListener('click',read);
  $('return-to-pdf').addEventListener('click',()=>pdf?.focusCurrent());
  $('return-to-input').addEventListener('click',()=>{ ($('read-button').disabled ? $('change-button') : $('read-button')).focus(); });
  $('retry-status').addEventListener('click',()=>{ checkStatus(); pdf?.check(); });
  $('cancel-button').addEventListener('click',() => { invalidate(); message('Recognition cancelled. No reading will be displayed. Initial model loading and checkpoint checks cannot be interrupted; if underway, they must finish before cancellation takes effect. You can choose another candidate or image, or try again.'); (selected?.pdf ? $('read-pdf-candidate') : $('read-button')).focus(); });
  $('help-button').addEventListener('click',() => {
    const open = $('keyboard-help').hidden; $('keyboard-help').hidden = !open; $('help-button').setAttribute('aria-expanded',String(open));
  });
  $('announce-button').addEventListener('click',() => { if (result) announce(`${regionAnnouncement()}${$('confidence-title').textContent}. ${$('confidence-text').textContent} ${result.speech}`); });
  $('copy-button').addEventListener('click',async () => {
    if (!result) return; const ticket = epoch;
    try { await navigator.clipboard.writeText(result.latex); if (ticket === epoch) announce('LaTeX copied.'); }
    catch { if (ticket === epoch) { $('latex-text').focus(); const range = document.createRange(); range.selectNodeContents($('latex-text')); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); message('Clipboard access is unavailable. The LaTeX is selected; press Control+C or Command+C to copy it.'); } }
  });
  ['parent','child','previous','next'].forEach(direction => $(direction + '-button').addEventListener('click',() => move(direction,true)));
  $('math-tree').addEventListener('keydown',event => {
    if (!result || busy || event.altKey || event.ctrlKey || event.metaKey) return;
    const list = visibleNodes(), node = tree.get(active);
    if (!['ArrowUp','ArrowDown','ArrowRight','ArrowLeft','Home','End','Enter',' '].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowUp') move('previous');
    if (event.key === 'ArrowDown') move('next');
    if (event.key === 'ArrowRight') { if (node.children.length && !expanded.has(active)) { expanded.add(active); renderTree(); } else move('child'); }
    if (event.key === 'ArrowLeft') { if (node.children.length && expanded.has(active)) { expanded.delete(active); renderTree(); } else move('parent'); }
    if (event.key === 'Home') activate(list[0]);
    if (event.key === 'End') activate(list[list.length-1]);
    if (event.key === 'Enter' || event.key === ' ') announce(node.label);
  });
  document.addEventListener('paste',event => {
    const files = [...(event.clipboardData?.files || [])];
    if (!files.length) return;
    event.preventDefault(); selectFiles(files);
  });
  document.addEventListener('dragover',event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) { event.preventDefault(); $('drop-zone').classList.add('drag-over'); } });
  document.addEventListener('dragleave',event => { if (!event.relatedTarget) $('drop-zone').classList.remove('drag-over'); });
  document.addEventListener('drop',event => { event.preventDefault(); $('drop-zone').classList.remove('drag-over'); if (event.dataTransfer?.files.length) selectFiles([...event.dataTransfer.files]); });
  window.addEventListener('pagehide',() => { request?.abort(); if (imageURL) URL.revokeObjectURL(imageURL); });
  if (typeof window.createPDFNavigation === 'function') pdf = window.createPDFNavigation({
    api, announce, message,
    onClear: () => clearImage(false,true),
    onSelect: (candidate, documentData) => {
      clearImage(false,true);
      if (!candidate) return;
      selected = {pdf:true, document_id:documentData.document_id, equation_id:candidate.id, candidate};
      $('output-region').hidden = false;
      $('input-hint').textContent = candidate.layout === 'multi-line' ? 'Multi-line candidate: recognition not attempted; outside the tested single-equation scope.' : 'PDF candidate selected. Its completeness is unknown. Choose Read equation to attempt recognition.';
      controls();
    },
    onPreview: (bytes, candidate, documentID) => {
      if (!selected?.pdf || selected.document_id !== documentID || selected.equation_id !== candidate.id) return;
      if (imageURL) URL.revokeObjectURL(imageURL);
      imageURL = URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
      $('source-image').src = imageURL; $('source-image').alt = 'Automatically detected PDF candidate region. It may omit parts of the equation; completeness unknown.';
      $('file-name').textContent = `PDF page ${candidate.page_index+1} · candidate ${candidate.order+1}`;
      $('change-button').textContent = 'Choose an image instead'; $('reset-button').textContent = 'Close PDF';
      $('image-preview').hidden = false; $('drop-zone').hidden = true;
    }
  });
  checkStatus();
})();
