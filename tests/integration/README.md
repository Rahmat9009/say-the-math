# Real integration and authored PDF checks

See [testing instructions](../../docs/TESTING.md) and
[release checks](../../docs/RELEASE_CHECKS.md).

- `test_pdf_portable.py` creates original temporary PDFs. Every page remains
  accessible; ordered candidates retain unknown completeness. Actual preview
  rendering/hash and closed-session errors are checked without downloaded data.
- `browser-checks.js` authors fraction, root/exponent and integral images in the
  browser and sends them to the actual local model. UI speech, MathML and explorer
  are compared with returned output, including genuine alternative readings.
- `test_pdf_navigation.py` is an optional corpus/export regression suite. It
  explicitly skips when the excluded research corpus/manifest is absent. Its
  outputs are not product inputs and do not supply a runtime fallback.

The PNG examples in this directory were authored for the project. Reference
equations in tests are never sent as OCR answers. A passing display comparison
does not establish that a recognition matches its source or that NVDA speaks it
successfully. Keep automated, audible and blind-user evidence distinct.
