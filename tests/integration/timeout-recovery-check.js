// Real backend with test-only SAYTHEMATH_READ_LIMIT_S=8. Never fabricate a timeout.
// Use an authored long equation at test-output/long-equation.png, then a fraction.
async page => {
  const origin = new URL(page.url()).origin, checks = [];
  const assert = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
  await page.goto(origin);
  const select = async file => {
    await page.locator('#image-input').setInputFiles(file);
    await page.waitForFunction(() => !document.getElementById('read-button').disabled);
  };
  const read = async () => {
    const pending = page.waitForResponse(r => r.url() === origin+'/api/read', {timeout:180000});
    await page.locator('#read-button').focus(); await page.keyboard.press('Enter');
    const reply = await pending; return {status:reply.status(),body:await reply.json()};
  };
  await select('test-output/long-equation.png');
  const start = Date.now(), timed = await read(), elapsed_ms = Date.now()-start;
  assert(timed.status === 504 && timed.body.error?.code === 'RECOGNITION_TIMEOUT', 'real server deadline returns explicit timeout');
  assert(!('latex' in timed.body) && !('confidence' in timed.body), 'timeout returns no partial reading or confidence');
  await page.locator('#visible-message').waitFor({state:'visible'});
  assert(await page.evaluate(() => document.activeElement.id) === 'visible-message', 'timeout receives error focus');
  assert(await page.locator('#result').isHidden() && await page.locator('#working-state').isHidden(), 'timeout exits loading without a result');
  await page.keyboard.press('Tab'); await page.keyboard.press('Enter');
  assert(await page.evaluate(() => document.activeElement.id) === 'read-button', 'keyboard recovery returns to equation input');
  await select('tests/integration/fraction.png'); const recovered = await read();
  assert(recovered.status === 200, 'same process reads next fraction without BUSY');
  await page.locator('#result').waitFor({state:'visible'});
  assert(await page.locator('#latex-text').textContent() === recovered.body.latex, 'recovery UI displays the next actual reading');
  await page.waitForTimeout(1500);
  assert(await page.locator('#latex-text').textContent() === recovered.body.latex, 'timed-out result never replaces recovery');
  return {realBackend:true,apiDoubles:false,testOnlyDeadlineSeconds:8,audibleTest:false,passed:checks.length,checks,elapsed_ms,timed,recovered};
}
