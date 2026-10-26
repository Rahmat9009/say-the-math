'use strict';

// Local navigation only. No research records, source comparisons or reading cache.
window.createPDFNavigation = ({ api, announce, message, onClear, onSelect, onPreview }) => {
  const $ = id => document.getElementById(id);
  let documentData = null, pageIndex = 0, candidate = null, generation = 0;
  let opening = null, openToken = null, preview = null, available = false, checking = 0;
  const remembered = new Map();
  const stateLabel = page => page.status === 'unsupported' ? 'Unsupported page' : page.status === 'no_candidates' ? 'No candidates detected' : `${page.candidate_count} candidate region${page.candidate_count === 1 ? '' : 's'}`;
  const pageLabel = page => `PDF page ${page.index + 1} of ${documentData.page_count}${page.printed_label !== null ? `, printed label ${page.printed_label}` : ''}`;
  const location = (item, doc = documentData) => `PDF page ${item.page_index + 1} of ${doc.page_count}, candidate ${item.order + 1}${item.number ? `, equation number ${item.number}` : ''}`;
  const text = (value, max) => typeof value === 'string' && value.length <= max;

  function validate(data) {
    const fail = () => { throw new Error('The local reader returned an invalid PDF navigation manifest. Open the PDF again.'); };
    if (!data || !text(data.document_id, 100) || !data.document_id || !text(data.filename, 255) || !Number.isInteger(data.page_count) || data.page_count < 1 || data.page_count > 500 || !Array.isArray(data.pages) || data.pages.length !== data.page_count || !Array.isArray(data.equations) || data.equations.length > 2000) fail();
    data.pages.forEach((p, index) => {
      if (p?.index !== index || !['candidates','unsupported','no_candidates'].includes(p.status) || !(p.printed_label === null || text(p.printed_label,100)) || !Number.isInteger(p.candidate_count) || p.candidate_count < 0 || !Array.isArray(p.reasons) || p.reasons.length > 50 || p.reasons.some(r=>!text(r,2000))) fail();
    });
    const ids = new Set(), counts = new Array(data.page_count).fill(0);
    let lastOrder = -1, lastPage = -1;
    for (const e of data.equations) {
      if (!e || !text(e.id,100) || !e.id || ids.has(e.id) || !Number.isInteger(e.page_index) || e.page_index < lastPage || e.page_index < 0 || e.page_index >= data.page_count || !Number.isInteger(e.order) || e.order <= lastOrder || !['single-line','multi-line'].includes(e.layout) || e.region_completeness?.state !== 'unknown' || !text(e.context_before,120) || !(e.number === null || text(e.number,200)) || !Array.isArray(e.bbox_pt) || e.bbox_pt.length !== 4 || e.bbox_pt.some(v=>!Number.isFinite(v)) || e.bbox_pt[2] <= e.bbox_pt[0] || e.bbox_pt[3] <= e.bbox_pt[1] || e.provenance !== 'glyph_layout') fail();
      if ((e.layout === 'multi-line' && e.recognition?.status !== 'not_attempted') || (e.layout === 'single-line' && e.recognition?.status !== 'pending')) fail();
      ids.add(e.id); counts[e.page_index]++; lastOrder = e.order; lastPage = e.page_index;
    }
    data.pages.forEach((p,i)=>{ if (p.candidate_count !== counts[i] || (p.status === 'candidates') !== (counts[i] > 0)) fail(); });
    return data;
  }

  async function check() {
    const ticket = ++checking;
    try {
      const data = await api('/api/pdf/status', null, new AbortController(), 15000);
      if (ticket !== checking) return;
      available = data.available === true;
      $('pdf-engine-status').textContent = text(data.message,2000) ? data.message : 'Experimental PDF navigation is unavailable.';
    } catch {
      if (ticket !== checking) return;
      available = false;
      $('pdf-engine-status').textContent = 'Experimental PDF navigation is unavailable. Check or update the local reader, then check its status again.';
    }
    $('choose-pdf').disabled = !available;
  }

  function close(focus = true) {
    const prior = documentData, priorToken = openToken;
    if (!prior && !opening && !priorToken) return Promise.resolve();
    generation++; opening?.abort(); preview?.abort();
    opening = null; preview = null; openToken = null; documentData = null; candidate = null;
    remembered.clear(); $('pdf-input').value = '';
    $('pdf-opening').hidden = true; $('pdf-navigation').hidden = true;
    $('pdf-pages').replaceChildren(); $('pdf-candidates').replaceChildren(); $('pdf-context').textContent = '';
    $('pdf-document-title').textContent = ''; $('pdf-preview-status').textContent = '';
    onClear();
    if (focus) { $('choose-pdf').focus(); announce('PDF closed. Choose another PDF or an equation image.'); }
    const body = prior ? { document_id: prior.document_id } : { open_token: priorToken };
    return api('/api/pdf/close', body, new AbortController(),15000).catch(() => {
      if (focus && !documentData && !opening) message('The PDF is closed in this browser. The server could not confirm closing it; its idle session expires after 15 minutes.');
    });
  }

  async function openFiles(files) {
    await close(false);
    onClear(); const ticket = ++generation;
    if (files.length !== 1 || !files[0].size || files[0].size > 50 * 1024 * 1024) {
      message('Choose exactly one PDF no larger than 50 MiB.',true); return;
    }
    const file = files[0];
    openToken = crypto.randomUUID();
    const controller = opening = new AbortController();
    $('pdf-opening').hidden = false;
    $('cancel-pdf-open').focus();
    announce('Opening PDF and discovering candidate regions locally. Recognition has not started.');
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (ticket !== generation) return;
      if (!new TextDecoder('ascii').decode(bytes.slice(0,1024)).includes('%PDF-')) throw new Error('This file does not look like a PDF. Choose an unencrypted PDF.');
      let binary = '';
      for(let i=0;i<bytes.length;i+=32768) binary += String.fromCharCode(...bytes.subarray(i,i+32768));
      const data = await api('/api/pdf/open', {pdf_base64:btoa(binary),filename:file.name || 'document.pdf',open_token:openToken},controller,300000);
      if (ticket !== generation) return;
      try { documentData = validate(data); }
      catch(error) { if (text(data?.document_id,100)) await api('/api/pdf/close',{document_id:data.document_id},new AbortController(),15000).catch(()=>{}); throw error; }
      $('pdf-document-title').textContent = `${documentData.filename} · ${documentData.page_count} PDF pages`;
      $('pdf-pages').replaceChildren();
      documentData.pages.forEach(p=>{
        const option=document.createElement('option'); option.value=String(p.index); option.textContent=`${pageLabel(p)} — ${stateLabel(p)}`; $('pdf-pages').append(option);
      });
      $('pdf-navigation').hidden = false;
      showPage(0, false);
      $('pdf-document-title').focus();
      announce(`PDF open. ${documentData.page_count} pages. All pages are listed. ${pageLabel(documentData.pages[0])}. ${stateLabel(documentData.pages[0])}. Detection can miss equations; automatic regions have completeness unknown.`);
    } catch(error) {
      if (ticket !== generation) return;
      const token = openToken;
      documentData = null; openToken = null;
      if (token) api('/api/pdf/close',{open_token:token},new AbortController(),15000).catch(()=>{});
      message(error.message,true,error.code);
    } finally {
      if(ticket===generation) { opening=null; $('pdf-opening').hidden=true; }
    }
  }

  function showPage(index, speak = true, targetID = null) {
    if(!documentData || index<0 || index>=documentData.page_count) return;
    pageIndex=index;
    const page=documentData.pages[index], items=documentData.equations.filter(e=>e.page_index===index);
    $('pdf-pages').value=String(index);
    $('pdf-page-title').textContent=pageLabel(page);
    $('pdf-page-status').textContent=`${stateLabel(page)}. ${page.status==='candidates' ? 'Candidates may be incomplete; detection can miss equations.' : 'Equations may be present but not detected. This version cannot reliably recover missing regions without visual selection.'}`;
    $('pdf-page-reasons').textContent=page.reasons.join(' ');
    $('previous-page').disabled=index===0; $('next-page').disabled=index===documentData.page_count-1;
    $('pdf-candidates').replaceChildren();
    items.forEach(item=>{
      const option=document.createElement('option'); option.value=item.id;
      option.textContent=`Candidate ${item.order+1}${item.number ? ` · number ${item.number}` : ''} · ${item.layout==='multi-line' ? 'Multi-line; recognition not attempted' : 'Single-line candidate'} · completeness unknown`;
      $('pdf-candidates').append(option);
    });
    $('pdf-candidate-controls').hidden=!items.length;
    const preferred=targetID || remembered.get(index);
    choose(items.find(e=>e.id===preferred) || items[0] || null, false);
    if(speak) announce(`${pageLabel(page)}. ${$('pdf-page-status').textContent}${candidate ? ` ${location(candidate)}. Detected region: completeness unknown.` : ''}`);
  }

  function choose(item, speak = true) {
    preview?.abort(); preview=null;
    candidate=item;
    if(item) remembered.set(pageIndex,item.id);
    $('pdf-candidate-info').hidden=!item;
    $('pdf-preview-status').textContent='';
    onSelect(item,documentData);
    const all=documentData.equations, at=item ? all.indexOf(item) : -1;
    $('previous-candidate').disabled=item ? at===0 : !all.some(e=>e.page_index<pageIndex);
    $('next-candidate').disabled=item ? at===all.length-1 : !all.some(e=>e.page_index>pageIndex);
    if(!item) return;
    $('pdf-candidates').value=item.id;
    $('pdf-candidate-title').textContent=location(item);
    $('pdf-context').textContent=item.context_before || 'No surrounding text was extracted.';
    $('pdf-layout-status').textContent=item.layout==='multi-line' ? 'Multi-line candidate: recognition not attempted. Multi-line derivations are outside the tested single-equation scope.' : 'Single-line candidate. Choose Read equation to attempt recognition of this region.';
    if(speak) announce(`${location(item)}. Detected region: completeness unknown. Surrounding text may contain extraction errors. ${item.context_before} ${$('pdf-layout-status').textContent}`);
    const currentDoc=documentData.document_id, currentItem=item.id;
    const controller=preview=new AbortController();
    $('pdf-preview-status').textContent='Preparing candidate preview…';
    api('/api/pdf/crop',{document_id:currentDoc,equation_id:currentItem},controller,30000).then(data=>{
      if(documentData?.document_id!==currentDoc || candidate?.id!==currentItem || controller.signal.aborted) return;
      if(!text(data.image_base64,12*1024*1024) || data.region_completeness?.state!=='unknown') throw new Error('The candidate preview response was invalid.');
      const binary=atob(data.image_base64), bytes=Uint8Array.from(binary,x=>x.charCodeAt(0));
      onPreview(bytes,item,currentDoc);
      $('pdf-preview-status').textContent='Candidate preview ready. Completeness remains unknown.';
    }).catch(error=>{
      if(documentData?.document_id===currentDoc && candidate?.id===currentItem && !controller.signal.aborted) $('pdf-preview-status').textContent=`Preview unavailable. ${error.message}`;
    });
  }

  $('choose-pdf').addEventListener('click',()=>{ $('pdf-input').value=''; $('pdf-input').click(); });
  $('pdf-input').addEventListener('change',()=>{ if($('pdf-input').files.length) openFiles([...$('pdf-input').files]); });
  $('close-pdf').addEventListener('click',()=>close());
  $('cancel-pdf-open').addEventListener('click',()=>{ close(false); $('choose-pdf').focus(); announce('PDF discovery cancelled. Discovery stops after the current page; no pages will be listed.'); });
  $('pdf-pages').addEventListener('change',()=>showPage(Number($('pdf-pages').value)));
  $('pdf-candidates').addEventListener('change',()=>choose(documentData.equations.find(e=>e.id===$('pdf-candidates').value)));
  for(const [id,delta] of [['previous-page',-1],['next-page',1]]) $(id).addEventListener('click',()=>{ showPage(pageIndex+delta); $('pdf-pages').focus(); });
  for(const [id,delta] of [['previous-candidate',-1],['next-candidate',1]]) $(id).addEventListener('click',()=>{
    const all=documentData.equations;
    const next=candidate ? all[all.indexOf(candidate)+delta] : (delta>0 ? all.find(e=>e.page_index>pageIndex) : all.findLast(e=>e.page_index<pageIndex));
    if(next) { showPage(next.page_index,true,next.id); $('pdf-candidates').focus(); }
  });
  window.addEventListener('pagehide',()=>{
    const body=documentData ? {document_id:documentData.document_id} : openToken ? {open_token:openToken} : null;
    opening?.abort(); preview?.abort();
    if(body) fetch('/api/pdf/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true}).catch(()=>{});
  });
  check();
  return {close,check,focusCurrent:()=>{ (documentData ? candidate ? $('pdf-candidates') : $('pdf-pages') : $('choose-pdf')).focus(); }};
};
