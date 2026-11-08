# Third-party material

The repository license (see `LICENSE`) covers the author's own work only.

## Fonts

Bundled in `src/finagent/ui/static/fonts/`, under the SIL Open Font License 1.1 (license texts
sit next to the files):

- IBM Plex Sans
- JetBrains Mono

## Bank annual reports

The evaluation is built on public annual reports of Julius Baer, Vontobel, EFG International,
Swissquote, BCV and BCGE (`data/sources.csv` lists URLs and SHA-256 hashes). The reports are
copyright of their publishers and are **not** redistributed here: `data/raw/` and `data/parsed/`
are git-ignored and `finagent download` fetches them from the publishers.

The repository does contain material derived from the reports: short evidence excerpts (table rows, sentences) and page
numbers in the evaluation datasets (`eval/datasets/`), and extracted key figures (`data/gold/`). The CI retrieval fixture
(`tests/fixtures/ci_fixture.jsonl.gz`) holds only stemmed search terms and embeddings, not readable report text. All of this is
included for reproducibility and review only, and remains subject to the publishers' rights.

## Dependencies

Dependencies are installed from PyPI and are not part of this repository. Note that
`pymupdf` is licensed under AGPL-3.0 (or a commercial license from Artifex) and `docling`,
`torch`, `sentence-transformers` and the others carry their own licenses; check them before any
use that requires the author's permission under `LICENSE`.

## Models

Models called through APIs or run locally (DeepSeek, Qwen, bge-m3, e5) are governed by their
providers' terms; no model weights are included.
