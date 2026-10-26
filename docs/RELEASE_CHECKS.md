# Release checks — 2026-10-26

The follow-up [fresh-installation release record](FRESH_INSTALL.md) covers the
Node 22+ setup alignment, entirely new Windows installation, new checkpoint
downloads and subsequent real-app checks. The results below are the earlier
initial-publication checks and retain their original scope.

Executed on Windows 11, Python 3.12 and Node.js 24 before the initial publication.
These are regression diagnostics, not a held-out recognition-accuracy evaluation.

| Check | Executed result |
| --- | --- |
| Backend and authored PDF tests, with existing local model assets and optional local research fixtures | 102 passed; no failures, errors or skips |
| Isolated staged-source export, fresh locked npm dependencies, existing pinned Python environment and external local model assets | 96 passed; two optional research-data modules skipped; no failures or errors |
| Frontend browser checks with explicit API doubles | 61 passed |
| Running app on port 8780, actual model and math conversion, authored fraction/root/exponent/integral inputs | 35 passed |
| Explicit cancellation-error API double and keyboard recovery | 5 passed; not evidence of actual cancellation by itself |
| Offline setup self-check | Passed checkpoint hashes, architecture counts, local model load and math conversion |
| JavaScript syntax | Application, PDF interface and math worker passed Node syntax checks |
| Staged publication audit | Reviewed file list, credential patterns, personal paths, binary allowlist, exclusions, documentation links, required README first line and matching checkpoint hashes |
| Git whitespace check | Passed |

The actual browser runs returned uncertain fraction/root readings and a
higher-confidence integral reading. The interface matched the model's returned
LaTeX, speech and structure; alternatives remained uncertain. No browser JavaScript
exceptions or external-resource requests occurred in those runs. Backend checks
exercise cancellation, timeouts and recovery. Authored PDF checks retain all pages,
including no-candidate and unsupported pages, order candidates, retain unknown
completeness, render/hash actual crops and close document sessions.

The public-source export excludes downloaded papers, recognition records and raw
research corpora. Their optional tests skip explicitly; authored PDF tests still
run. Private local research fixtures used in the 102-test run were not published.
The isolated export reused installed Python packages and model checkpoints: this
was not a fresh operating-system installation or a new download of all assets.
Dependency deprecation warnings remain. macOS/Linux execution is pending.

Publication excludes credentials, environments, model weights, caches, personal
documents, screen-reader installations/settings/logs, internal handoffs, session
transcripts and downloaded datasets. Only three authored equation PNGs are
allowlisted as binary test inputs. Dependencies/checkpoints are obtained through
explicit setup; hashes and attribution remain in the public source. Pattern
scanning supplements file review and does not prove that every possible secret
format is detectable.

Voice clarity and comfort are **user-confirmed**. These release checks were
automated, with no new audible NVDA session. Detailed audible equation reading,
confidence/completeness announcements, PDF use, error/cancellation focus recovery
and independent blind-user validation remain pending. The user's NVDA voice and
speed preferences were preserved. See [ACCESSIBILITY.md](ACCESSIBILITY.md).

Experimental PDF discovery can miss or incompletely crop equations, including
higher-confidence transcriptions. Nonvisual repair is unresolved. Recognition
errors, repeated-model agreement and timeouts remain limitations described in the
[README](../README.md). Initial model loading/checkpoint checks cannot be
interrupted. No hackathon entry was sent during release preparation.
