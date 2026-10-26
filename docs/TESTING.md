# Reproduce the checks

Use the project root as the working directory. Run setup first; setup downloads
pinned dependencies/checkpoints explicitly. Install test-only packages:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests/backend tests/integration/test_pdf_portable.py -q
```

On macOS/Linux the Python path is `.venv/bin/python`. Those platforms have not
been executed in this build. The real-model tests need the pinned model files;
when absent they explicitly skip. Deterministic tests use clearly isolated reader
doubles; they never supply a reading to the production UI.

`test_pdf_portable.py` generates original temporary PDFs with mathematical text,
ordinary prose and unsupported vector graphics. It checks every page, candidate
order, unknown completeness, actual PNG rendering/hash and session closure. No
downloaded research document or saved recognition is required.

Optional research-export checks skip explicitly when their corpus/manifest is
absent. Downloaded papers, crops and raw research results are deliberately excluded
from the public repository. Those checks are not a release prerequisite for a
fresh clone. The public authored-PDF checks remain runnable.

## Browser checks

The test-only Playwright CLI is installed through npm exec, not bundled into the
runtime. Create `output/playwright` before screenshot checks.

For isolated frontend checks, start `node tests/frontend/fixture-server.mjs` on
8766, then in another terminal:

```powershell
npx --yes --package @playwright/cli playwright-cli -s=frontend open http://127.0.0.1:8766/
npx --yes --package @playwright/cli playwright-cli -s=frontend run-code --filename tests/frontend/browser-checks.js --raw
```

The fixture server has no OCR. The browser script explicitly supplies API doubles
for validation, readiness, errors, alternatives, stale responses and tree/focus
checks. `cancellation-errors-check.js` separately exercises the normally unseen
409 RECOGNITION_CANCELLED error as an explicit API-error double.

For actual image/model browser checks, start the real server and use another
browser session:

```powershell
.\.venv\Scripts\python.exe app.py --port 8780
npx --yes --package @playwright/cli playwright-cli -s=real open http://127.0.0.1:8780/
npx --yes --package @playwright/cli playwright-cli -s=real run-code --filename tests/integration/browser-checks.js --raw
```

This script authors fraction, root/exponent and integral images and sends their
actual bytes to the model. Reference equations remain in test code and are never
sent as inference answers. Assertions compare the UI with actual model/formatter
output; they do not establish that every recognized equation is correct.

## Privacy and release checks

Before publishing, inspect the Git index as the authoritative publication list.
Exclude credentials, model weights, environments, caches, personal documents,
NVDA binaries/settings/logs, session handoffs and downloaded datasets. The root
`.gitignore` is a second layer, not a substitute for reviewing staged contents.
Keep checkpoint hashes and setup scripts so users can reproduce downloads.

Automated checks cannot complete the audible/independent-use checks in
[ACCESSIBILITY.md](ACCESSIBILITY.md). Report exactly which category was executed.
