# Experimental PDF API

The image API is documented in [API_CONTRACT.md](../API_CONTRACT.md). PDF routes
are additive and use the same local-origin checks and error envelope.

| Route | Request | Result |
| --- | --- | --- |
| GET /api/pdf/status | None | available, message; navigation availability is separate from OCR readiness |
| POST /api/pdf/open | pdf_base64, optional filename/open_token | document_id, every physical page, ordered candidate regions |
| POST /api/pdf/crop | document_id, equation_id | Preview image_base64, crop_sha256, region_completeness; no OCR |
| POST /api/pdf/read | document_id, equation_id | Image-reading fields plus document/equation identity, region_completeness, crop_sha256, settings_fingerprint, from_cache |
| POST /api/pdf/close | Exactly one of document_id or open_token | closed: true; pending discovery can be cancelled by token |

Physical page indices start at zero; the UI displays index + 1. Printed labels are
shown only when PDF metadata defines them. Pages say Candidates, No candidates
detected or Unsupported page. None establishes that an equation is absent.
Candidate context is extracted surrounding text and may contain extraction errors.

Automatic regions always have `region_completeness.state = unknown`, even when a
transcription is higher-confidence. No runtime crop-completeness test exists.
Multi-line candidates are listed as not_attempted; direct reading returns
422 UNSUPPORTED_LAYOUT. Source comparisons and approximate disputed-node references
are not runtime reliability features.

Documents/crops/cache stay in memory: PDF 50 MiB, 500 pages, two documents, 2,000
candidates, 50,000 glyphs/page and 2 million/document, 16 million rendered pixels.
Idle sessions expire after 15 minutes. Successful-reading cache is per session,
limited to 24 entries / 12 MiB, keyed to exact PNG bytes and current recognition
code/settings/assets/dependency fingerprints. Failures are not cached. Changed
input creates a new document session. Changes during recognition reject caching.

Normal deadlines: recognition 120 seconds, discovery 240 seconds, configurable
with SAYTHEMATH_READ_LIMIT_S and SAYTHEMATH_PDF_OPEN_LIMIT_S. Decoding cancellation
stops at the next model step; discovery stops between pages. Initial model loading
and checkpoint checks cannot be interrupted and may delay stopping. Conversion
has a separate 15-second worker limit. A concurrent connected client can get BUSY.

Stopped jobs produce no partial reading/document: 504 RECOGNITION_TIMEOUT,
409 RECOGNITION_CANCELLED, 504 PDF_DISCOVERY_TIMEOUT or 409 PDF_CANCELLED. Other
errors include INVALID_PDF, PDF_TOO_LARGE, PDF_RENDER_FAILED, UNKNOWN_DOCUMENT,
UNKNOWN_EQUATION, PDF_SESSION_LIMIT and SETTINGS_CHANGED. The frontend treats
server failures separately from its own transport timeout, whose server state is
unknown. Generation guards discard stale responses after cancellation/replacement.
