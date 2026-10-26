# Fresh Windows installation — 2026-10-26

## Source and setup

The source checkout and public remote both started at
`16b55a2408c34a3088e15e798e550b236e966915`, with no tracked working-tree
changes. A separate public clone was created at `C:\stm-rc-1026`; that destination
did not exist. The supplied `node-setup-fix.patch` was reviewed and applied to
both checkouts after `git apply --check`. It only aligns setup, package metadata,
launchers and README at Node 22+, keeping Node 24 as the tested version. No
dependency version, model, confidence cutoff or inference setting was changed.

Setup ran with the installed base Python 3.12.10 executable, not the original
project's virtual environment. Before setup the clone had no `.venv`,
`node_modules` or `models`. `SAYTHEMATH_MODELS_DIR` was unset. The Python package
cache was disabled (`PIP_NO_CACHE_DIR=1`); npm used a new clone-local cache. The
existing environment and model files were not copied, linked or reused.

Executed environment:

- Windows 11, build 26300, 64-bit.
- Python 3.12.10; Node.js 24.16.0; npm 11.13.0.
- PyTorch 2.5.1+cpu, TorchVision 0.20.1+cpu, pix2tex 0.1.4.
- MathJax 4.1.3, Speech Rule Engine 5.0.0-rc.4, xmldom 0.9.12.

Commands, with the base Python executable abbreviated as `<Python312>`:

```powershell
git clone https://github.com/Rahmat9009/say-the-math.git C:\stm-rc-1026
# Apply the reviewed release patch before installation.
cd C:\stm-rc-1026
$env:PIP_NO_CACHE_DIR='1'
$env:npm_config_cache='C:\stm-rc-1026\.setup-npm-cache'
& '<Python312>\python.exe' setup_app.py
.\.venv\Scripts\python.exe setup_app.py --check
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-dev.txt
```

Full setup exited 0. It created a new isolated environment, installed Python
packages and 17 locked Node packages, then downloaded both checkpoints on the
first attempt. Actual new-file SHA256 values matched the pinned values:

| Checkpoint | SHA256 |
| --- | --- |
| weights.pth | a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa |
| image_resizer.pth | 1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458 |

The initial self-check loaded and counted 30,351,829 parameters and converted a real
fraction with the local math worker. The separate `--check` passed with runtime
network blocking active and zero blocked outbound attempts. `pip check` reported
no broken requirements. Test-only packages were installed after this runtime
installation/self-check; they were not required for setup success.

No genuine setup failure occurred. A sandboxed preliminary Python-launcher probe
could not see registered Python installations; the normal-host probe resolved
Python 3.12.10 successfully. This was an execution-environment limitation rather
than a project installer failure. Node 22 itself and macOS/Linux remain unexecuted.

## Running-app checks

The new installation was started with its own Python, Node dependencies and model
assets on port 8781, with normal recognition/discovery limits of 120/240 seconds.
The existing port-8780 app was left intact. Test code and the small HTML fix below
were copied into the clone; production recognition code was unchanged.

- Actual fraction, root/exponent and integral recognition: 35 browser assertions
  passed. Fraction/root readings were uncertain with two of three agreeing;
  integral was higher-confidence with three agreeing. These few authored examples
  are not an accuracy estimate. UI LaTeX, speech, native MathML and structural
  navigation matched actual backend output. A wrong model alternative remained
  an uncertain alternative; faithful UI presentation does not make it correct.
- Real cancellation, immediate recovery, replacement-input/stale-response guards,
  PDF candidate recognition and all three authored PDF page states: 32 assertions
  passed. Cancel and input replacement each stopped actual HTTP/model work; server
  logs recorded client disconnects. No API answers were substituted.
- The PDF candidate returned a higher-confidence transcription while completeness
  remained unknown in both API and UI. Ordinary-text and unsupported vector pages
  stayed navigable and did not imply absence of equations. Candidate/page/close
  controls restored the expected DOM focus. These are not audible observations.
- Browser runtime checks observed no external requests or JavaScript exceptions.
  A harmless initial favicon 404 was reproduced and fixed with an empty inline
  favicon; a new browser navigation produced no console error afterward.

- Timeout and same-process recovery: 8 assertions passed on a separate instance
  with an explicitly test-only 8-second recognition limit. A newly authored long
  single equation returned HTTP 504 RECOGNITION_TIMEOUT in 8.130 seconds, with no
  partial reading/confidence. Keyboard error recovery returned to the input and
  the next actual fraction succeeded in 1.764 seconds, without BUSY or a stale
  replacement. The normal 120-second deadline was not waited out again in this
  fresh run; its earlier test remains historical evidence only.
- The public Python suite in the new environment: 96 passed, two optional
  research-data modules skipped, no failures/errors, 35.63 seconds. There were
  304 warnings; warnings were not treated as audible or runtime
  failures. Excluded datasets were not copied into the clone.

Reproduction commands after runtime setup and test-package installation:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --disable-warnings --basetemp=test-output/release-pytest
.\.venv\Scripts\python.exe tests/integration/make_release_inputs.py
$env:SAYTHEMATH_READ_LIMIT_S='120'
$env:SAYTHEMATH_PDF_OPEN_LIMIT_S='240'
.\.venv\Scripts\python.exe app.py --port 8781
```

In another terminal, create `output/playwright`, open an isolated CLI browser and
run the existing real-image checks, then the workflow checks:

```powershell
npx --yes --package @playwright/cli playwright-cli -s=release open http://127.0.0.1:8781/
npx --yes --package @playwright/cli playwright-cli -s=release run-code --filename tests/integration/browser-checks.js --raw
npx --yes --package @playwright/cli playwright-cli -s=release run-code --filename tests/integration/release-workflow-checks.js --raw
```

For the timeout case, use a separate terminal/process with
`$env:SAYTHEMATH_READ_LIMIT_S='8'` and run `app.py --port 8782`. Open a separate
browser session at that URL and run `tests/integration/timeout-recovery-check.js`.
The production/listening instance stays at normal limits. Stop the temporary
instance afterward. No API response interception is used to manufacture timeout,
cancellation or recovery results. Browser routes only monitor/block external URLs.

## Accessibility and limits

Previously confirmed voice clarity/comfort is retained. In the new guided
session, the listener reported hearing the image chooser's written label clearly
and successfully loading the fraction. After activating Read equation, the
listener reported careful listening and that the reading worked well. Exact
equation words and focus announcements were not transcribed, so detailed
word-level validation is not marked complete. No audible success is inferred
from the automated checks. The listener then closed NVDA before the warning
checkpoint; it was left closed with existing preferences preserved. Warning
audibility, numerator/denominator announcements, focus recovery and PDF
completeness warnings remain pending for a future listening session. Independent
blind-user validation remains pending. The application does not set NVDA voice
or speed. See [ACCESSIBILITY.md](ACCESSIBILITY.md).

PDF navigation remains experimental, may miss/incompletely crop regions and has
no dependable nonvisual repair workflow. Timeouts produce no partial reading;
initial model loading/checkpoint verification cannot be interrupted. Checkpoint
licensing/provenance limits remain disclosed in the README/notices. No hackathon
entry was submitted during this work.
