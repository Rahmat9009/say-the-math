# Third-party notices

Third-party packages, model weights and research corpora are not bundled. `setup_app.py` downloads the packages and model weights onto
the user's computer. Each component stays under its own license. Keep upstream LICENSE/NOTICE files when
redistributing a packaged build. This list records what the app uses and the license metadata we read
from the installed packages on 2026-10-21. It is not a legal determination.

## Model

- **pix2tex / LaTeX-OCR 0.1.4**, https://github.com/lukas-blecher/LaTeX-OCR. Repository license: MIT, (c) 2021 Lukas Blecher.
  - Checkpoints from release v0.0.1, downloaded by setup and verified by SHA256:
    - `weights.pth` a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa
    - `image_resizer.pth` 1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458
  - The release does not carry a separate license for the weights. The repository is MIT. The training-data provenance (arXiv, Wikipedia, im2latex-derived formulas) is not resolved by the code license. Check before any redistribution of the weights.
  - `recognition/model.py` adapts small parts of pix2tex's `cli.py` (`minmax_size`, the image-resizer loop). They are MIT and attributed in the file.
  - The original MIT copyright and permission notice for that adaptation are retained in `licenses/pix2tex-MIT.txt`.
  - Loaded architecture: encoder 12,855,232; decoder 12,643,648; image resizer 4,852,949; total 30,351,829 parameters (counted from the loaded modules).

## Math conversion (Node, run locally)

- MathJax `@mathjax/src` 4.1.3 and `@mathjax/mathjax-newcm-font` 4.1.3: Apache-2.0. https://github.com/mathjax/MathJax-src
- Speech Rule Engine 5.0.0-rc.4: Apache-2.0. https://github.com/Speech-Rule-Engine/speech-rule-engine
- `@xmldom/xmldom` 0.9.12: MIT.
- Transitive: mhchemparser 4.2.1 (Apache-2.0), mj-context-menu 1.0.0 (Apache-2.0), wicked-good-xpath 1.3.0 (MIT), commander 14.0.3 (MIT), glob 13.0.6 and rimraf 6.1.3 (BlueOak-1.0.0), and their small dependencies, as listed in `package-lock.json`.

## Python runtime (see requirements-lock.txt for exact versions)

- PyTorch 2.5.1 (CPU) and TorchVision 0.20.1: BSD-3-Clause.
- timm 0.5.4: Apache-2.0. x-transformers 0.15.0: MIT. entmax 1.3: MIT. einops: MIT.
- transformers 4.46.3, tokenizers 0.20.3, huggingface_hub, safetensors: Apache-2.0. These are used only to load pix2tex's bundled tokenizer file, with offline mode forced.
- albumentations 1.4.24, albucore: MIT. opencv-python-headless 5.0.0.93: Apache-2.0. Its wheels may bundle third-party libraries with their own licenses (for example FFmpeg, LGPL); check the wheel's bundled notices before redistributing.
- NumPy, SciPy, pandas, networkx, sympy, Jinja2, MarkupSafe, idna, colorama, pyreadline3: BSD-family. Pillow: MIT-CMU. PyYAML, munch, pydantic, urllib3, six, filelock: MIT. requests, regex, tzdata, stringzilla, simsimd: Apache-2.0 (regex also CNRI-Python). certifi: MPL-2.0. tqdm: MPL-2.0 AND MIT. typing_extensions: PSF-2.0.

## Experimental PDF navigation runtime

- pdfplumber 0.11.4 and pdfminer.six 20231228: MIT. Used for glyph/layout extraction; the runtime detector is a vendored copy of this project's frozen feasibility detector.
- pypdfium2 4.30.0: Apache-2.0 OR BSD-3-Clause, together with the PDFium binary's bundled third-party license notices. Retain those notices when redistributing the installed runtime. No PyMuPDF dependency was added.
- cryptography 50.0.2 (Apache-2.0 OR BSD-3-Clause), cffi 2.1.1 and pycparser 3.11 (MIT) are PDF-extraction dependencies pinned in requirements-lock.txt.
- Downloaded research PDFs, crops and raw comparison records are excluded from the public repository. Optional local corpus tests skip when those fixtures are absent. Public PDF tests generate original temporary pages with Matplotlib and its installed fonts; the renderer is test-only. Recognition results and source-comparison diagnostics are not shipped as live readings.

## Test-only

- pytest 8.3.4 (MIT) and matplotlib 3.9.4 (PSF-based matplotlib license) are used to author and render test equations. They are not needed to run the app.

## Not included

No textbook pages, research datasets, rendered research images or model weights are stored in this repository. The test equations in `tests/backend/make_images.py` were written for this project.
