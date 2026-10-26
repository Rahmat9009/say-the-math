// Real backend ONLY. Run with Playwright CLI against the actual local server.
// First navigate the browser to the running app's loopback URL. No API doubles here.
async (page) => {
  await page.unrouteAll({behavior:'ignoreErrors'});
  const origin = new URL(page.url()).origin;
  if (!origin.startsWith('http://127.0.0.1:') || origin.endsWith(':8766')) throw new Error('Navigate to the real local app, not the fixture server.');
  const outbound = [], errors = [], observations = [], passed = [];
  page.removeAllListeners('pageerror'); page.on('pageerror',error=>errors.push(error.message));
  const context = page.context();
  await context.route('**/*',route=>{
    if (new URL(route.request().url()).origin !== origin) { outbound.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  const assert = (value,label) => { if (!value) throw new Error(label); passed.push(label); };
  await page.goto(origin);
  await page.waitForFunction(()=>document.getElementById('engine-status').textContent !== 'Checking the local reader…');
  const status = await page.evaluate(async()=> (await fetch('/api/status')).json());
  assert(status.ready===true,'real backend ready');
  const examples = [
    {name:'fraction',latex:'\\frac{x+3}{7}',math:'<mfrac><mrow><mi>x</mi><mo>+</mo><mn>3</mn></mrow><mn>7</mn></mfrac>',roles:['numerator','denominator']},
    {name:'root-power',latex:'\\sqrt{x^{2}+5}',math:'<msqrt><mrow><msup><mi>x</mi><mn>2</mn></msup><mo>+</mo><mn>5</mn></mrow></msqrt>',roles:['radicand','exponent']},
    {name:'integral',latex:'\\int_{0}^{2}x\\,dx',math:'<msubsup><mo>∫</mo><mn>0</mn><mn>2</mn></msubsup><mi>x</mi><mspace width="0.16em"/><mi>d</mi><mi>x</mi>',roles:['lower_bound','upper_bound']}
  ];
  const authoring = await context.newPage();
  for (const example of examples) {
    await authoring.setContent(`<html><body style="margin:0;background:white"><div id="authored" style="display:inline-block;padding:26px;background:white"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block" style="font-size:36px;color:black;margin:0"><mrow>${example.math}</mrow></math></div></body></html>`);
    const bounds = await authoring.locator('#authored').boundingBox();
    if (example.name === 'integral') assert(bounds.width > bounds.height,'integral test source laid out as a single line');
    const buffer = await authoring.locator('#authored').screenshot({path:`tests/integration/${example.name}.png`});
    await page.locator('#image-input').setInputFiles({name:`${example.name}.png`,mimeType:'image/png',buffer});
    await page.waitForFunction(()=>!document.getElementById('read-button').disabled);
    const replyPromise = page.waitForResponse(r=>r.url()===origin+'/api/read' && r.request().method()==='POST',{timeout:180000});
    await page.locator('#read-button').focus(); await page.keyboard.press('Enter');
    const reply = await replyPromise, data = await reply.json();
    assert(reply.ok(),`${example.name}: actual model returned successful reading`);
    await page.locator('#result').waitFor({state:'visible',timeout:15000});
    assert(await page.locator('#latex-text').textContent()===data.latex,`${example.name}: UI LaTeX equals real model output`);
    assert(await page.locator('#spoken-text').textContent()===data.speech,`${example.name}: UI speech equals real conversion`);
    const expectedText = await page.evaluate(xml=>new DOMParser().parseFromString(xml,'application/xml').documentElement.textContent.replace(/\s/g,''),data.mathml);
    const shownText = (await page.locator('#math-display math').textContent()).replace(/\s/g,'');
    assert(shownText===expectedText,`${example.name}: native MathML preserves actual symbols`);
    assert(await page.locator('#math-tree [role=treeitem]').count()===data.nodes.length,`${example.name}: entire returned hierarchy displayed`);
    assert(await page.evaluate(()=>document.activeElement.id)==='result-title',`${example.name}: keyboard result focus`);
    await page.locator('#math-tree').focus(); await page.keyboard.press('End');
    const last = await page.locator('#math-tree').getAttribute('aria-activedescendant');
    assert((await page.locator('#'+last).getAttribute('aria-label'))===data.nodes.at(-1).label,`${example.name}: explorer reaches final returned part`);
    const roleFindings = {};
    for (const role of example.roles) {
      const node = data.nodes.find(n=>n.kind===role);
      roleFindings[role] = node?.label || null;
      if (node) {
        await page.locator('#math-tree').press('Home');
        for (let i=0;i<data.nodes.findIndex(n=>n.id===node.id);i++) await page.keyboard.press('ArrowDown');
        const id = await page.locator('#math-tree').getAttribute('aria-activedescendant');
        assert((await page.locator('#'+id).getAttribute('aria-label'))===node.label,`${example.name}: keyboard reaches ${role}`);
      }
    }
    const alternatives = data.alternatives;
    const other = alternatives.find(a=>a.latex!==data.latex);
    let alternativeCheck = null;
    if(other) {
      await page.locator('#alternatives summary').click();
      const index = alternatives.indexOf(other)+1;
      const formatReply = page.waitForResponse(r=>r.url()===origin+'/api/format' && r.request().method()==='POST');
      await page.getByRole('button',{name:`Use reading ${index}`,exact:true}).click();
      const formatted = await formatReply;
      alternativeCheck = {latex:other.latex,status:formatted.status()};
      if (formatted.ok()) {
        await page.waitForFunction(latex=>document.getElementById('latex-text').textContent===latex,other.latex);
        assert(await page.locator('#confidence-title').textContent()==='Uncertain reading',`${example.name}: real alternative remains uncertain`);
      } else {
        await page.locator('#visible-message').waitFor({state:'visible'});
        assert(await page.locator('#latex-text').textContent()===data.latex,`${example.name}: real alternative failure retains prior reading`);
        alternativeCheck.error = await page.locator('#visible-message').textContent();
      }
    }
    observations.push({name:example.name,reference_latex:example.latex,observed_latex:data.latex,speech:data.speech,confidence:data.confidence,elapsed_ms:data.elapsed_ms,parts:data.nodes.length,roles:roleFindings,alternatives:data.alternatives,alternativeCheck});
  }
  await authoring.close();
  await page.screenshot({path:'output/playwright/real-integral.png',fullPage:true});
  const invalid = await page.evaluate(async()=>{
    const response=await fetch('/api/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:btoa('corrupt image')})});
    return {status:response.status,body:await response.json()};
  });
  assert(invalid.status===422 || invalid.status===400,'real API rejects invalid image');
  assert(Boolean(invalid.body.error?.code),'real API returns structured error');
  assert(errors.length===0,'real frontend has no JS exceptions');
  assert(outbound.length===0,'browser requested no external resources with outbound routes blocked');
  await context.unrouteAll({behavior:'ignoreErrors'});
  return {realInference:true,status,passed:passed.length,checks:passed,observations,invalid,errors,outbound};
}
