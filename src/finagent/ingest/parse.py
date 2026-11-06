"""PDF -> pages + blocks. Docling does layout/tables; pymupdf gives plain page text."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from finagent.config import ROOT

PARSED = ROOT / "data" / "parsed"

_KINDS: dict[str, Literal["heading", "paragraph", "table", "caption", "list"]] = {
    "section_header": "heading",
    "title": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "footnote": "paragraph",
    "list_item": "list",
    "caption": "caption",
    "table": "table",
}


class Block(BaseModel):
    doc_id: int
    page_no: int  # 1-based PDF index
    kind: Literal["heading", "paragraph", "table", "caption", "list"]
    level: int | None = None
    text: str  # tables as Markdown
    section_path: list[str]  # running heading stack


def strip_repeated_lines(pages: list[str], threshold: float = 0.5) -> list[str]:
    """Drop lines (digits ignored) on more than `threshold` of pages: running headers/footers."""
    if len(pages) < 4:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip())

    counts: Counter[str] = Counter()
    for text in pages:
        counts.update({key(ln) for ln in text.splitlines() if ln.strip()})
    limit = threshold * len(pages)
    noisy = {k for k, n in counts.items() if n > limit}
    return ["\n".join(ln for ln in text.splitlines() if key(ln) not in noisy) for text in pages]


def page_texts(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as pdf:
        return strip_repeated_lines([p.get_text() for p in pdf])


def _convert(path: Path, sha256: str):
    """Run docling once per PDF; later calls load data/parsed/<sha256>.json."""
    from docling_core.types.doc import DoclingDocument

    cache = PARSED / f"{sha256}.json"
    if cache.exists():
        return DoclingDocument.load_from_json(cache)

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=False)  # the reports have a text layer
    fmt = {InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    conv = DocumentConverter(format_options=fmt)
    doc = conv.convert(path).document
    PARSED.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(cache)
    return doc


def parse_pdf(path: Path, doc_id: int, sha256: str) -> list[Block]:
    doc = _convert(path, sha256)
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    for item, _ in doc.iterate_items():
        label = str(getattr(item.label, "value", item.label))
        kind = _KINDS.get(label)
        if kind is None or not item.prov:
            continue  # pictures, page headers/footers, formulas, ...
        if kind == "table":
            text = item.export_to_markdown(doc).strip()
        else:
            text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        level = None
        if kind == "heading":
            level = getattr(item, "level", 1) or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
        blocks.append(
            Block(
                doc_id=doc_id,
                page_no=item.prov[0].page_no,
                kind=kind,
                level=level,
                text=text,
                section_path=[t for _, t in stack],
            )
        )
    return blocks
