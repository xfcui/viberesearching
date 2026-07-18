---
name: convert-pdf-to-markdown
description: >-
  Convert PDF documents to clean Markdown with marker-pdf (tables, equations,
  images) and pdfplumber/pypdf fallbacks. Use when the user requests PDF to
  Markdown conversion, document extraction, or formatting PDFs.
disable-model-invocation: true
---

# Convert PDF to Markdown

**Runner:** `.cursor/skills/convert-pdf-to-markdown/scripts/convert.py`

```bash
python .cursor/skills/convert-pdf-to-markdown/scripts/convert.py --input <path_to_pdf> [options]
```

| Option | Description |
|---|---|
| `--input`, `-i` | Required. Input PDF |
| `--output`, `-o` | Output `.md` (default: beside input) |
| `--output-dir`, `-d` | Dir for markdown + images |
| `--fallback` | Skip marker-pdf; use pdfplumber/pypdf |

---

## Workflow

1. **Deps:** Prefer `marker-pdf` (`pip install marker-pdf`; office formats: `pip install "marker-pdf[full]"`). Activate the project venv first.
2. **Convert:**

```bash
python .cursor/skills/convert-pdf-to-markdown/scripts/convert.py --input "path/to/document.pdf"
# custom:
python .cursor/skills/convert-pdf-to-markdown/scripts/convert.py \
  --input "path/to/document.pdf" --output "output/report.md" --output-dir "output/"
# fast text-only:
python .cursor/skills/convert-pdf-to-markdown/scripts/convert.py --input "path/to/document.pdf" --fallback
```

3. **Verify:** Skim the `.md` head; if marker ran, check `images/`. Report path + brief summary to the user.

---

## Troubleshooting

- **Scanned / bad text:** marker may OCR — needs a working torch/tesseract setup.
- **OOM / GPU issues:** use `--fallback`.
