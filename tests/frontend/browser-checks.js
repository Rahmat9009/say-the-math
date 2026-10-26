// Run ONLY against fixture-server.mjs through Playwright CLI run-code --filename.
async (page) => {
  const passed = [], errors = [], outbound = [];
  await page.unrouteAll({behavior:'ignoreErrors'});
  page.removeAllListeners('pageerror');
  const assert = (value, name) => { if (!value) throw new Error(name); passed.push(name); };
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    if (!route.request().url().startsWith('http://127.0.0.1:8766/')) { outbound.push(route.request().url()); await route.abort(); }
    else await route.continue();
  });
  const primary = '\\frac{x+1}{2}', alternative = '\\frac{x-1}{2}';
  const mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow><mn>2</mn></mfrac></math>';
  const nodes = [
    {id:'m0',parent:null,children:['m1'],kind:'equation',label:'Equation: x plus 1 divided by 2'},
    {id:'m1',parent:'m0',children:['m2','m3'],kind:'fraction',label:'Fraction: x plus 1 divided by 2'},
    {id:'m2',parent:'m1',children:[],kind:'numerator',label:'Numerator: x plus 1'},
    {id:'m3',parent:'m1',children:[],kind:'denominator',label:'Denominator: 2'}
  ].map(n => ({...n, mathml}));
  const reading = () => ({latex:primary,speech:'the fraction with numerator x plus 1 and denominator 2',mathml,root_id:'m0',nodes,confidence:{level:'higher',message:'Higher-confidence reading. Recognition can still change signs or exponents.',agreeing_reads:2,total_reads:3},alternatives:[{latex:primary,count:2},{latex:alternative,count:1}],elapsed_ms:10});
  let statusReady = false, mode = 'higher', reads = 0, held;
  await page.route('**/api/status', r => r.fulfill({json:{ready:statusReady,model_available:statusReady,math_available:statusReady,message:statusReady?'Local reader is ready.':'Model weights are missing. Run setup.'}}));
  await page.route('**/api/read', async route => {
    reads++;
    if (mode === 'delay') await new Promise(resolve => { held = resolve; });
    if (mode === 'malformed') return route.fulfill({body:'not JSON',contentType:'text/plain'});
    if (mode === 'busy') return route.fulfill({status:409,json:{error:{code:'BUSY',message:'Local reader is busy.'}}});
    if (mode === 'model-error') return route.fulfill({status:500,json:{error:{code:'RECOGNITION_FAILED',message:'Model inference failed.'}}});
    if (mode === 'math-error') return route.fulfill({status:422,json:{error:{code:'MATH_CONVERSION_FAILED',message:'Math conversion failed.'}}});
    if (mode === 'not-ready') return route.fulfill({status:503,json:{error:{code:'NOT_READY',message:'Model is no longer available. Run setup.'}}});
    if (mode === 'unreachable') return route.abort('connectionrefused');
    const value = reading();
    if (mode === 'uncertain') { value.confidence.level = 'uncertain'; value.tree_truncated = true; }
    if (mode === 'cycle') value.nodes = [ {...nodes[0],children:['m0']} ];
    if (mode === 'script') value.mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mtext><script>alert(1)</script></mtext></math>';
    if (mode === 'attributes') value.mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML" onclick="alert(1)" style="color:red"><mi href="https://example.com" id="unsafe">x</mi></math>';
    if (mode === 'text') value.speech = '<img src=x onerror=alert(1)>';
    return route.fulfill({json:value});
  });
  let formatFail = false;
  await page.route('**/api/format', route => {
    if (formatFail) return route.fulfill({status:422,json:{error:{code:'MATH_CONVERSION_FAILED',message:'Alternative could not be converted.'}}});
    const value = reading(); value.latex = alternative; value.speech = 'the fraction with numerator x minus 1 and denominator 2';
    value.mathml = mathml.replace('<mo>+</mo>','<mo>−</mo>');
    value.nodes = nodes.map(n=>({...n,label:n.label.replace('plus','minus')}));
    return route.fulfill({json:value});
  });
  await page.goto('http://127.0.0.1:8766/');
  await page.locator('#engine-status').filter({hasText:'missing'}).waitFor();
  assert(await page.locator('#read-button').isDisabled(),'missing setup disables recognition');
  assert(await page.locator('#setup-help').getAttribute('open') !== null,'missing setup opens help');
  // Use Tab/Enter to open the native file chooser; no pointer interaction.
  await page.keyboard.press('Tab');
  assert(await page.locator('.skip').evaluate(el=>el===document.activeElement),'first Tab exposes skip link');
  await page.keyboard.press('Enter');
  assert(await page.locator('#main').evaluate(el=>el===document.activeElement),'skip link focuses main');
  await page.keyboard.press('Tab');
  assert(await page.locator('#choose-button').evaluate(el=>el===document.activeElement),'keyboard reaches image chooser after skip');
  // Native chooser is checked separately with CLI press Enter / upload; that modal
  // interrupts run-code by design. Remaining checks use setInputFiles.
  // Create an original test image in the browser, not an OCR answer in the UI.
  const png = await page.evaluate(() => { const c=document.createElement('canvas'); c.width=300;c.height=100;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,300,100);x.fillStyle='black';x.font='30px serif';x.fillText('x + 1',30,40);x.fillRect(20,50,120,2);x.fillText('2',65,85);return c.toDataURL().split(',')[1]; });
  const image = {name:'authored-fraction.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')};
  const select = async () => { await page.locator('#image-input').setInputFiles(image); await page.locator('#image-preview').waitFor({state:'visible'}); };
  const focusID = () => page.evaluate(() => document.activeElement.id);
  const waitResult = () => page.locator('#result').waitFor({state:'visible'});
  await select();
  assert(await page.locator('#read-button').isDisabled(),'selected image does not bypass missing setup');
  statusReady=true; await page.locator('#retry-status').click(); await page.waitForFunction(()=>!document.getElementById('read-button').disabled);
  await page.locator('#read-button').focus(); await page.keyboard.press('Enter'); await waitResult();
  assert(await focusID()==='result-title','result moves focus to heading');
  assert(await page.locator('#confidence-title').textContent()==='Higher-confidence reading','higher-confidence label');
  assert(await page.locator('#math-display math mfrac').count()===1,'native MathML fraction remains accessible');
  assert(await page.locator('#math-display math').getAttribute('aria-hidden')===null,'native math is not hidden');
  await page.locator('#math-tree').focus(); await page.keyboard.press('ArrowRight');
  assert(await page.locator('#math-tree').getAttribute('aria-activedescendant')==='part-1','Right enters fraction');
  await page.keyboard.press('ArrowDown');
  assert(await page.locator('#math-tree').getAttribute('aria-activedescendant')==='part-2','Down enters numerator in reading order');
  await page.keyboard.press('End');
  assert(await page.locator('#math-tree').getAttribute('aria-activedescendant')==='part-3','End reaches denominator');
  await page.keyboard.press('ArrowLeft');
  assert(await page.locator('#math-tree').getAttribute('aria-activedescendant')==='part-1','Left reaches parent');
  await page.keyboard.press('ArrowLeft');
  assert(await page.locator('#part-1').getAttribute('aria-expanded')==='false','Left collapses expanded group');
  await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight'); await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.getElementById('announcement').textContent==='Numerator: x plus 1');
  passed.push('Enter repeats structural role through live region');
  await page.locator('#parent-button').click(); assert(await focusID()==='math-tree','movement button restores explorer focus');
  await page.locator('#announce-button').click(); await page.waitForFunction(()=>document.getElementById('announcement').textContent.includes('Higher-confidence reading'));
  passed.push('Announce uses live region');
  await page.locator('#alternatives summary').click(); formatFail=true; await page.getByRole('button',{name:'Use reading 2',exact:true}).click();
  await page.locator('#visible-message').filter({hasText:'Alternative could not'}).waitFor();
  assert(await page.locator('#latex-text').textContent()===primary,'failed alternative preserves existing reading');
  formatFail=false; await page.getByRole('button',{name:'Use reading 2',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('latex-text').textContent.includes('x-1'));
  assert(await page.locator('#confidence-title').textContent()==='Uncertain reading','manual alternative remains uncertain');
  assert(await focusID()==='result-title','alternative recovers heading focus');
  assert(!await page.locator('#confidence').getAttribute('class').then(x=>x.includes('higher')),'alternative clears higher-confidence styling');
  await page.locator('#reset-button').click(); assert(await focusID()==='choose-button','reset restores choose focus');
  assert(await page.locator('#result').isHidden(),'reset removes old result');
  await page.locator('#image-input').setInputFiles({name:'bad.png',mimeType:'image/png',buffer:Buffer.from('not an image')});
  await page.locator('#visible-message').filter({hasText:'Choose one PNG'}).waitFor(); passed.push('spoofed image rejected');
  await page.locator('#image-input').setInputFiles({name:'huge.png',mimeType:'image/png',buffer:Buffer.alloc(8*1024*1024+1)});
  await page.locator('#visible-message').filter({hasText:'8 MiB'}).waitFor(); passed.push('oversized byte input rejected');
  await page.locator('#image-input').setInputFiles({name:'broken.png',mimeType:'image/png',buffer:Buffer.from([137,80,78,71,13,10,26,10])});
  await page.locator('#visible-message').filter({hasText:'could not be opened'}).waitFor(); passed.push('corrupt image decoding rejected');
  const manyPixels = await page.evaluate(()=>{const c=document.createElement('canvas');c.width=4001;c.height=4000;return c.toDataURL().split(',')[1];});
  await page.locator('#image-input').setInputFiles({name:'large-dimensions.png',mimeType:'image/png',buffer:Buffer.from(manyPixels,'base64')});
  await page.locator('#visible-message').filter({hasText:'16 million pixels'}).waitFor(); passed.push('oversized dimensions rejected');
  for (const scenario of ['uncertain','malformed','busy','model-error','math-error','cycle','script','attributes','text']) {
    mode=scenario; await select(); await page.locator('#read-button').click();
    if (['uncertain','attributes','text'].includes(scenario)) {
      await waitResult();
      if(scenario==='uncertain') assert(await page.locator('#confidence-title').textContent()==='Uncertain reading','uncertain result displayed');
      if(scenario==='uncertain') assert(await page.locator('#structure-warning').isVisible(),'incomplete structure is explicitly disclosed');
      if(scenario==='attributes') assert(await page.locator('#math-display [onclick], #math-display [style], #math-display [href], #unsafe').count()===0,'MathML unsafe attributes stripped');
      if(scenario==='text') assert(await page.locator('#spoken-text img').count()===0 && (await page.locator('#spoken-text').textContent()).startsWith('<img'),'API text rendered inertly');
    } else {
      await page.locator('#visible-message').waitFor({state:'visible'});
      assert(await page.locator('#result').isHidden(),`${scenario} is a failure, not a reading`);
      assert(await focusID()==='visible-message',`${scenario} error focus`);
    }
  }
  mode='delay'; await select(); const before=reads; await page.locator('#read-button').click();
  await page.waitForFunction(()=>!document.getElementById('working-state').hidden);
  assert(await page.locator('#read-button').isDisabled(),'double submission disabled');
  await page.locator('#reset-button').click(); held();
  await page.waitForTimeout(200);
  assert(await page.locator('#result').isHidden() && reads===before+1,'stale response after reset discarded');
  mode='delay'; await select(); await page.locator('#read-button').click();
  await page.waitForTimeout(80); await select(); held(); await page.waitForTimeout(200);
  assert(await page.locator('#result').isHidden(),'stale response after replacement discarded');
  mode='delay'; await page.locator('#read-button').click(); await page.waitForTimeout(80); await page.locator('#cancel-button').click(); held();
  assert(await focusID()==='read-button','cancel restores focus');
  // Exercise the actual paste handler with a browser ClipboardEvent.
  await page.evaluate(base64 => { const b=Uint8Array.from(atob(base64),x=>x.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([b],'pasted.png',{type:'image/png'}));document.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})); },png);
  await page.waitForFunction(()=>document.getElementById('file-name').textContent==='pasted.png'); passed.push('clipboard image paste handler');
  await page.evaluate(base64 => { const b=Uint8Array.from(atob(base64),x=>x.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([b],'dropped.png',{type:'image/png'}));document.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true})); },png);
  await page.waitForFunction(()=>document.getElementById('file-name').textContent==='dropped.png'); passed.push('additional drag/drop handler');
  mode='higher'; await page.locator('#read-button').click(); await waitResult();
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile layout fits viewport');
  await page.emulateMedia({reducedMotion:'reduce',forcedColors:'active'});
  assert(await page.evaluate(()=>getComputedStyle(document.querySelector('.spinner')).animationName)==='none','reduced motion stops spinner');
  assert(await page.locator('#part-0 > span').evaluate(el=>getComputedStyle(el).color!==getComputedStyle(el).backgroundColor),'selected row visible in forced colors');
  await page.screenshot({path:'output/playwright/mobile.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'no-preference',forcedColors:'none'});
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:'output/playwright/desktop.png',fullPage:true});
  await page.locator('#result details').last().locator('summary').click();
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('Test denied permission');}}}));
  await page.locator('#copy-button').click();
  assert(await page.evaluate(()=>getSelection().toString())===primary,'copy permission failure selects LaTeX for keyboard copy');
  assert(await focusID()==='latex-text','copy fallback focus');
  for (const unavailable of ['not-ready','unreachable']) {
    mode=unavailable; await select(); await page.locator('#read-button').click();
    await page.locator('#visible-message').waitFor({state:'visible'});
    assert(await page.locator('#read-button').isDisabled(),`${unavailable} invalidates old readiness`);
    assert(await page.locator('#engine-status').getAttribute('class').then(x=>x.includes('error')),`${unavailable} status explains unavailability`);
    await page.locator('#retry-status').click(); await page.waitForFunction(()=>!document.getElementById('read-button').disabled);
  }
  assert(errors.length===0,'no browser JS errors'); assert(outbound.length===0,'no external frontend requests');
  return {isolatedTestDoubles:true,passed:passed.length,checks:passed,errors,outbound};
}
