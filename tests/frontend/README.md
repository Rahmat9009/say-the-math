# Isolated frontend checks

These checks use explicit API doubles; they do not perform OCR or establish model
accuracy, audible screen-reader behavior or independent blind-user success.

See [public testing instructions](../../docs/TESTING.md) for the CLI commands,
real-model browser checks and release exclusions. Run from the project root and
create `output/playwright` before screenshot checks.

`browser-checks.js` covers readiness, byte/decode/size validation, MathML sanitation,
confidence, alternatives, tree navigation, focus recovery, cancellation, stale
responses, clipboard fallback, responsive/forced-color layout and no external
frontend requests. `cancellation-errors-check.js` specifically checks the normally
unseen RECOGNITION_CANCELLED error UI with an isolated API error response.

Manual audible checks and remaining limitations are in
[ACCESSIBILITY.md](../../docs/ACCESSIBILITY.md). User-confirmed voice clarity does
not complete equation-reading or blind-user testing.
