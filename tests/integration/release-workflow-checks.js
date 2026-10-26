// Real running backend, no API doubles. Generate test-output/authored.pdf with
// test_pdf_portable.py's authored_pdf fixture; run from the project root.
async page => {
  const origin = new URL(page.url()).origin;
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin)) throw new Error('Open the real local app first.');
  const checks = [], observations = [], external = [], errors = [];
  const assert = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
  const context = page.context();
  await page.unrouteAll({behavior:'ignoreErrors'});
  await context.unrouteAll({behavior:'ignoreErrors'});
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== origin) {
      external.push(route.request().url()); return route.abort();
    }
    return route.continue();
  });
  const focus = () => page.evaluate(() => document.activeElement.id);
  const select = async name => {
    await page.locator('#image-input').setInputFiles(`tests/integration/${name}.png`);
    await page.waitForFunction(() => !document.getElementById('read-button').disabled);
  };
  const start = async () => {
    const sent = page.waitForRequest(r => r.url() === origin+'/api/read');
    await page.locator('#read-button').focus(); await page.keyboard.press('Enter');
    await sent;
  };
  const read = async () => {
    const response = page.waitForResponse(r => r.url() === origin+'/api/read', {timeout:180000});
    await start();
    const reply = await response, body = await reply.json();
    assert(reply.ok(), 'actual recovery recognition succeeds without BUSY');
    await page.locator('#result').waitFor({state:'visible'});
    assert(await page.locator('#latex-text').textContent() === body.latex, 'UI presents the actual recovery transcription');
    return body;
  };
  await page.goto(origin);
  await select('fraction'); await read(); // Warm real model before cancellation.
  await select('root-power'); await start();
  await page.waitForTimeout(350);
  assert(await page.locator('#working-state').isVisible(), 'request is still active before Cancel');
  await page.locator('#cancel-button').focus(); await page.keyboard.press('Enter');
  assert(await focus() === 'read-button', 'Cancel returns focus to Read equation');
  assert(await page.locator('#result').isHidden(), 'Cancel removes the old reading');
  assert((await page.locator('#visible-message').textContent()).includes('cannot be interrupted'), 'Cancel retains initial-load limitation');
  await select('fraction'); const recovered = await read();
  await page.waitForTimeout(1500);
  assert(await page.locator('#latex-text').textContent() === recovered.latex, 'cancelled request cannot replace recovery result');
  observations.push({case:'actual cancellation recovery', latex:recovered.latex, confidence:recovered.confidence});

  await select('root-power'); await start();
  await page.waitForTimeout(350);
  assert(await page.locator('#working-state').isVisible(), 'request is active before changing input');
  await select('integral'); const replacement = await read();
  await page.waitForTimeout(1500);
  assert(await page.locator('#latex-text').textContent() === replacement.latex, 'replacement input discards prior response');
  observations.push({case:'input replacement', latex:replacement.latex, confidence:replacement.confidence});

  const opened = page.waitForResponse(r => r.url() === origin+'/api/pdf/open', {timeout:300000});
  await page.locator('#pdf-input').setInputFiles('test-output/authored.pdf');
  const manifest = await (await opened).json();
  await page.locator('#pdf-navigation').waitFor({state:'visible'});
  assert(manifest.page_count === 3 && await page.locator('#pdf-pages option').count() === 3, 'every authored PDF page remains accessible');
  assert(await focus() === 'pdf-document-title', 'PDF open focuses document title');
  const initial = await page.locator('#pdf-candidates').inputValue();
  await page.locator('#next-candidate').focus(); await page.keyboard.press('Enter');
  assert(await focus() === 'pdf-candidates', 'candidate navigation restores selector focus');
  assert(await page.locator('#pdf-candidates').inputValue() !== initial, 'Next candidate follows reading order');
  await page.locator('#previous-candidate').focus(); await page.keyboard.press('Enter');
  assert(await page.locator('#pdf-candidates').inputValue() === initial, 'Previous candidate returns to the first region');
  await page.waitForFunction(() => !document.getElementById('read-pdf-candidate').disabled);
  const pdfReply = page.waitForResponse(r => r.url() === origin+'/api/pdf/read', {timeout:180000});
  await page.locator('#read-pdf-candidate').focus(); await page.keyboard.press('Enter');
  const response = await pdfReply, reading = await response.json();
  assert(response.ok(), 'selected PDF candidate runs actual recognition on demand');
  await page.locator('#result').waitFor({state:'visible'});
  assert(reading.region_completeness.state === 'unknown', 'actual PDF recognition keeps completeness unknown');
  assert(await page.locator('#output-region').isVisible(), 'completeness is displayed separately from confidence');
  assert((await page.locator('#output-region').textContent()).includes('completeness unknown'), 'higher confidence cannot imply a complete crop');
  assert(await page.locator('#latex-text').textContent() === reading.latex, 'PDF UI faithfully presents returned transcription');
  observations.push({case:'PDF candidate', latex:reading.latex, confidence:reading.confidence, completeness:reading.region_completeness});
  await page.locator('#next-page').focus(); await page.keyboard.press('Enter');
  assert(await focus() === 'pdf-pages', 'page navigation returns focus to page selector');
  assert((await page.locator('#pdf-page-status').textContent()).startsWith('No candidates detected.'), 'ordinary-text page says No candidates detected');
  assert(await page.locator('#result').isHidden(), 'changing PDF page clears prior recognition');
  await page.keyboard.press('ArrowDown');
  await page.waitForFunction(() => document.getElementById('pdf-pages').value === '2');
  assert((await page.locator('#pdf-page-status').textContent()).startsWith('Unsupported page.'), 'vector page says Unsupported page');
  assert(!(await page.locator('#pdf-page-status').textContent()).toLowerCase().includes('no equations'), 'unsupported state does not infer absence of equations');
  await page.locator('#close-pdf').focus(); await page.keyboard.press('Enter');
  assert(await focus() === 'choose-pdf', 'Close PDF returns focus to chooser');
  assert(await page.locator('#pdf-navigation').isHidden(), 'closed PDF navigation is removed');
  assert(errors.length === 0, 'no browser JavaScript errors');
  assert(external.length === 0, 'no external browser runtime requests');
  await context.unrouteAll({behavior:'ignoreErrors'});
  return {realBackend:true,apiDoubles:false,audibleTest:false,passed:checks.length,checks,observations,errors,external};
}
