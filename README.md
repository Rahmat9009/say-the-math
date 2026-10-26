This project was submitted to the ryze.ai hackathon by Rahmat Ullah.

# Say the Math

A local prototype for opening a cropped printed-equation image, reading its
transcription with your screen reader, and exploring the numerator, denominator,
exponent and other parts with a keyboard. Experimental PDF navigation finds
candidate regions and keeps every page accessible.

Recognition uses **pix2tex with 30,351,829 architectural parameters**, including
its image resizer. Inference runs on the user's CPU. MathJax and Speech Rule Engine
convert the returned LaTeX to native MathML, English text and a structural tree.
There is no cloud inference, account, telemetry, runtime CDN or added TTS model.
The user's existing screen reader supplies voice and retains its own preferences.

## Install and run

Tested on Windows 11 with 64-bit Python 3.12 and Node.js 24. The setup also accepts
Python 3.11; Node.js 22 or newer is required by the locked dependencies.
Keep the project path short on Windows. Install Python/Node first,
then clone into a new folder:

```powershell
git clone https://github.com/Rahmat9009/say-the-math.git
cd say-the-math
.\Start-Windows.cmd
```

First setup explicitly installs pinned packages into `.venv` and `node_modules`,
downloads approximately 122 MB of checkpoints, checks their SHA256 hashes, loads
the model and records architectural parameter counts. Package downloads can total
about 1 GB. Later launches use local assets; runtime does not silently download
weights. Keep the server terminal open. Control+C stops it.

The printed browser URL is bound to `127.0.0.1` (normally port 8765). To use port
8780 explicitly after setup:

```powershell
.\.venv\Scripts\python.exe app.py --port 8780
```

Repair setup with `Start-Windows.cmd setup`. To set up or inspect it directly:

```powershell
py -3.12 setup_app.py
py -3.12 setup_app.py --check
```

The check loads/counts the model and checks assets without network access.
`sh start.sh` supplies a macOS/Linux launcher; those platforms have not been
executed in this build. The setup selects CPU PyTorch on Windows/Linux and uses
the pinned Node lockfile. Test-only dependencies are separate.

## Read an image

1. Tab to **Choose an image**, Enter, and select one tight crop containing the
   whole printed equation. PNG/JPEG/WebP: at most 8 MiB and 16 million pixels.
   Image paste is supported; drag/drop is an additional path.
2. Choose **Read equation**. Loading focuses **Cancel recognition**. First model
   loading can take longer; results normally return focus to **Read & explore**.
3. Read the confidence warning, native MathML and spoken text. **Announce with
   screen reader** repeats the current warning and reading through a live region.
4. Tab to **Explore the equation**. Up/Down visit visible parts; Right expands or
   enters, Left collapses or goes to the parent. Home/End visit the first/last
   visible parts; Enter repeats the current part. Tab leaves the tree. Native
   MathML remains a separate screen-reader reading/navigation path.
5. Compare model alternatives when available. Manually selected alternatives are
   always **Uncertain reading**. The LaTeX disclosure supports copying. Clear image
   removes input/result and restores chooser focus. Errors offer a keyboard return
   to the input. The app's Keyboard help includes optional NVDA speech settings.

## Experimental PDF navigation

Choose an unencrypted born-digital PDF (up to 50 MiB and 500 pages). Discovery
lists all physical pages and candidate regions in heuristic reading order.
Opening or navigating does not run OCR; activate **Read selected candidate**.

- Page controls include **No candidates detected** and **Unsupported page**.
  These never establish that a page has no equations. Candidate buttons can skip
  pages without candidates; page buttons do not.
- Every automatic region has **completeness unknown**, independently from
  transcription confidence. Even a higher-confidence crop can omit a relation,
  exponent or most of a derivation. Detection can miss, clip, split or merge regions.
- Extracted context is labelled **surrounding text that may contain extraction
  errors**. Multi-line candidates are listed with **recognition not attempted**;
  multi-line recognition is outside the tested scope.
- Return to PDF navigation restores candidate focus after a failure, or chooser
  focus if opening failed. Close PDF removes its in-memory session. Sessions
  expire after 15 idle minutes; successful-reading cache is bounded, session-local
  and keyed to exact crop bytes plus current recognition settings/code/assets.

There is no dependable nonvisual repair workflow for missed or incomplete regions.
Source comparison and approximate disputed-node hints are not runtime reliability
features. Details: [PDF API](docs/PDF_API.md).

## Confidence, failures and cancellation

**Higher-confidence reading** requires at least two agreeing outputs and a model
score meeting an experimental cutoff. **Uncertain reading** can therefore still
have two or three agreeing outputs. These are repeated views from the same model;
agreement is not a probability of correctness and can repeat the same mistake.
Recognition can change signs, exponents, roots, relations or bounds. No OCR fallback
or example answer is substituted for a failed recognition/conversion.

Normal server limits are 120 seconds per recognition and 240 seconds for PDF
discovery. A timeout is an explicit failure with no partial reading/document.
Cancel stops decoding at the next model step, or discovery between pages. **Initial
model loading and checkpoint checks cannot be interrupted** and may delay stopping.
Math conversion has a separate 15-second worker timeout. A truly concurrent client
can receive BUSY. Late results cannot replace a newer selection. Server timeouts
are distinct from a browser transport timeout where the server's state is unknown.

Handwriting, photographs, inline discovery and multi-line recognition are outside
the tested scope. Input limits, loopback Host/Origin checks, native MathML
whitelisting, bounded structure and stale-response guards are implemented. Python
and Node refuse outbound runtime networking; browser checks also blocked external
requests. This is not an OS-firewall isolation claim.

## Accessibility and testing status

**Voice clarity and comfort were user-confirmed.** Limited guided testing received
general positive feedback, but detailed audible equation-reading, uncertainty,
PDF navigation, cancellation/error announcements and focus recovery are not marked
complete. Independent blind-user task validation remains pending. Automated
DOM/ARIA/API checks do not establish audible behavior or general NVDA, JAWS or
VoiceOver compatibility. See [accessibility status](docs/ACCESSIBILITY.md).

The repository includes authored examples and tests; it excludes downloaded
research corpora, model weights, environments, NVDA settings/logs and session
transcripts. [Testing instructions](docs/TESTING.md) distinguish real inference,
isolated test doubles and optional research-fixture checks.
[Release checks](docs/RELEASE_CHECKS.md) record the executed publication checks
and their limits. These checks are regression diagnostics, not accuracy estimates.
The [fresh Windows installation record](docs/FRESH_INSTALL.md) covers a new
environment, fresh dependency/checkpoint downloads and actual running-app checks.

## Model downloads and attribution

The encoder has 12,855,232 parameters, decoder 12,643,648 and image resizer
4,852,949; total **30,351,829**, below the event's 500M-per-model cap. Parameter
counts are architectural counts, not checkpoint byte sizes. No additional
inference model is bundled.

Setup downloads the [pix2tex v0.0.1 release](https://github.com/lukas-blecher/LaTeX-OCR/releases/tag/v0.0.1):

| File | SHA256 |
| --- | --- |
| weights.pth | a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa |
| image_resizer.pth | 1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458 |

Inference preserves the project's pinned pix2tex 0.1.4 three-scale configuration
(1.0 / 0.75 / 0.55), temperature 0.00001 and experimental score rule. Readings
and conversion come from actual input; no source-comparison dataset is loaded.

Project code is [MIT](LICENSE), copyright Rahmat Ullah. The adapted
[pix2tex / LaTeX-OCR](https://github.com/lukas-blecher/LaTeX-OCR) code is MIT;
MathJax and Speech Rule Engine are Apache-2.0. The checkpoint release does not
state a separate weight license; the code license does not resolve training-data
provenance or redistribution rights. Training-source descriptions include
arXiv/Wikipedia/im2latex-derived material; this project distributes no training
dataset or weights. Test equations were authored for this project.
See [third-party notices](THIRD_PARTY_NOTICES.md) for pinned dependency licenses,
adaptation credits and checkpoint details. Inference is local after explicit setup;
research/build assistance is separate from the application runtime.
