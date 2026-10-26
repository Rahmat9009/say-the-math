# Shared API contract — version 1

Serve the interface and API from the same loopback origin. UTF-8 JSON. No cloud endpoint or wildcard CORS. Handle malformed/oversized requests and reject cross-origin requests/DNS-rebinding host values.

## GET /api/status

HTTP 200:
```json
{
  "ready": true,
  "model_available": true,
  "math_available": true,
  "message": "Local reader is ready.",
  "model": {"name": "pix2tex", "parameters": 30351829}
}
```
ready means dependencies/assets are present and recognition can be attempted; it does not claim that model loading/inference has already succeeded. Missing setup returns ready=false and a useful message. No paths or input contents in diagnostic responses.

## POST /api/read

Request: {"image_base64":"RAW_BASE64_WITHOUT_DATA_URL_PREFIX","filename":"equation.png"}.
filename is optional display metadata; never a filesystem path.
Allow PNG/JPEG/WebP, maximum 8 MiB decoded bytes and 16 million pixels. Validate actual decoded format, not just extension. Reject multi-frame/unsupported images.
Serialize model access or return BUSY while another recognition runs.

Response:
```json
{
  "latex": "\\frac{x+1}{2}",
  "speech": "the fraction with numerator x plus 1 and denominator 2",
  "mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\"><mfrac><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow><mn>2</mn></mfrac></math>",
  "confidence": {
    "level": "higher",
    "message": "Higher-confidence reading. Recognition can still change signs or exponents.",
    "agreeing_reads": 3,
    "total_reads": 3
  },
  "root_id": "m0",
  "nodes": [
    {"id":"m0","parent":null,"children":["m1"],"kind":"equation","label":"Equation: x plus 1 divided by 2","mathml":"<math>...</math>"},
    {"id":"m1","parent":"m0","children":["m2","m3"],"kind":"fraction","label":"Fraction: x plus 1 divided by 2","mathml":"<math>...</math>"},
    {"id":"m2","parent":"m1","children":[],"kind":"numerator","label":"Numerator: x plus 1","mathml":"<math>...</math>"},
    {"id":"m3","parent":"m1","children":[],"kind":"denominator","label":"Denominator: 2","mathml":"<math>...</math>"}
  ],
  "alternatives": [
    {"latex":"\\frac{x+1}{2}","count":3}
  ],
  "elapsed_ms": 1200
}
```

The example is a schema illustration, not a measured model result. Nodes must cover the actual generated structure; the illustrative list compresses internal groups. IDs unique; one root; child and parent links consistent; no cycles. Labels include structural role and spoken content. Cap tree size/depth and report truncation if needed.

Return distinct candidate transcriptions and their counts (1..3); do not include reference answers. level is higher only when >=2 readings agree and the chosen prediction's raw mean token log probability meets the experimental threshold. Otherwise uncertain. Agreement is not proof of correctness. Both levels must warn about fallibility.

## POST /api/format

Request: {"latex":"A_MODEL_GENERATED_ALTERNATIVE"}; max 2,000 characters.
Response: {"latex":"...","speech":"...","mathml":"...","root_id":"m0","nodes":[...]}.
No OCR and no confidence escalation. Frontend marks any manually selected alternative as uncertain.

## Error envelope

{"error":{"code":"INVALID_IMAGE","message":"Choose one PNG, JPG or WebP equation image."}}
Use 400 for malformed requests; 413 for excessive size; 422 for unreadable/unsupported image or failed mathematical conversion; 409 BUSY; 503 NOT_READY; 500 RECOGNITION_FAILED or INTERNAL_ERROR. Distinguish failures from an uncertain successful result. Keep stack traces, image contents and recognized personal text out of logs.

## DOM/data rules

Treat all API text as untrusted. Render text through textContent. For MathML, whitelist MathML elements and attributes or use a safe equivalent; reject scripts, HTML, links and event attributes. Do not inject unsanitized MathML with innerHTML.
Clear or invalidate old results on new input and guard against stale fetch responses.
Native MathML remains available to screen readers; the custom tree is an additional navigation path.
