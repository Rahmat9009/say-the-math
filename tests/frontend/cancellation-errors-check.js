// Isolated API-error double only: browsers normally disconnect before the real
// RECOGNITION_CANCELLED response can be received. Not a real cancellation test.
async page => {
  const checks=[];const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
  await page.unrouteAll({behavior:'ignoreErrors'});
  await page.route('**/api/status',r=>r.fulfill({json:{ready:true,model_available:true,math_available:true,message:'Isolated test reader ready.'}}));
  await page.route('**/api/pdf/status',r=>r.fulfill({json:{available:false,message:'PDF unused in this isolated check.'}}));
  await page.route('**/api/read',r=>r.fulfill({status:409,json:{error:{code:'RECOGNITION_CANCELLED',message:'Recognition was cancelled before it finished. No reading was produced.'}}}));
  await page.goto('http://127.0.0.1:8766/');
  await page.locator('#image-input').setInputFiles('tests/integration/fraction.png');
  await page.waitForFunction(()=>!document.getElementById('read-button').disabled);
  await page.keyboard.press('Enter');await page.locator('#visible-message').waitFor({state:'visible'});
  assert(await page.locator('#visible-message').getAttribute('data-error-code')==='RECOGNITION_CANCELLED','server cancellation code is retained in the explicit error state');
  assert((await page.locator('#visible-message').textContent()).includes('No reading was produced')&&(await page.locator('#visible-message').textContent()).includes('try again'),'server cancellation explains no reading and retry');
  assert(await page.locator('#result').isHidden()&&await page.locator('#working-state').isHidden()&&await page.locator('#output-card').getAttribute('aria-busy')==='false','server cancellation is neither a partial result nor a stuck loading state');
  assert(await page.evaluate(()=>document.activeElement.id)==='visible-message','server cancellation receives error focus');
  await page.keyboard.press('Tab');await page.keyboard.press('Enter');
  assert(await page.evaluate(()=>document.activeElement.id)==='read-button'&&await page.locator('#read-button').isEnabled(),'server cancellation has a keyboard retry recovery path');
  await page.unrouteAll({behavior:'ignoreErrors'});
  return {isolatedApiErrorDouble:true,notRealCancellation:true,passed:checks.length,checks};
}
