"""Three chunking strategies with the same output type: fixed | structure | table_aware."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

from finagent.ingest.parse import Block

# e5/bge-m3 truncate at 512 tokens; leave room for <s></s> and the "passage: " prefix.
MAX_TOKENS = 500
HEADER_RESERVE = 80  # tokens kept free for the context header in table_aware


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...
    def decode(self, ids: list[int]) -> str: ...


class Chunk(BaseModel):
    doc_id: int
    chunker: str
    page_start: int
    page_end: int
    section_path: str
    kind: Literal["text", "table", "mixed"]
    content: str


@dataclass
class Unit:
    page: int
    text: str
    is_table: bool = False
    idx: int = -1  # index of the source block


@dataclass
class Section:
    path: list[str]
    units: list[Unit] = field(default_factory=list)


def load_tokenizer() -> Tokenizer:
    """Tokenizer shared by the multilingual-e5 models and bge-m3 (XLM-R vocabulary)."""
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-small")

    class _Tok:
        def encode(self, text: str) -> list[int]:
            return tok.encode(text, add_special_tokens=False)

        def decode(self, ids: list[int]) -> str:
            return tok.decode(ids, skip_special_tokens=True)

    return _Tok()


def _kind(units: list[Unit]) -> Literal["text", "table", "mixed"]:
    n = sum(u.is_table for u in units)
    return "table" if n == len(units) else "text" if n == 0 else "mixed"


def _path(path: list[str], limit: int = 200) -> str:
    return " > ".join(path)[-limit:]


def _split_tokens(tok: Tokenizer, text: str, budget: int) -> list[str]:
    ids = tok.encode(text)
    return [tok.decode(ids[i : i + budget]) for i in range(0, len(ids), budget)]


# ---------------------------------------------------------------- fixed


def chunk_fixed(
    blocks: list[Block],
    tok: Tokenizer,
    size: int = MAX_TOKENS,
    overlap: int = 64,
    name: str = "fixed512",
) -> list[Chunk]:
    """Sliding token window over the whole document, ignoring structure."""
    if not blocks:
        return []
    ids: list[int] = []
    pages: list[int] = []
    for b in blocks:
        t = tok.encode(b.text + "\n")
        ids += t
        pages += [b.page_no] * len(t)
    out: list[Chunk] = []
    step = size - overlap
    for start in range(0, len(ids), step):
        window = ids[start : start + size]
        out.append(
            Chunk(
                doc_id=blocks[0].doc_id,
                chunker=name,
                page_start=pages[start],
                page_end=pages[start + len(window) - 1],
                section_path="",
                kind="text",
                content=tok.decode(window),
            )
        )
        if start + size >= len(ids):
            break
    return out


# ------------------------------------------------------------- structure


def _sections(blocks: list[Block]) -> list[Section]:
    secs: list[Section] = []
    for i, b in enumerate(blocks):
        if b.kind == "heading" or not secs:
            secs.append(Section(path=list(b.section_path)))
        secs[-1].units.append(Unit(b.page_no, b.text, b.kind == "table", i))
    return secs


class _Packer:
    """Greedy packing of sections into chunks of at most `budget` tokens."""

    def __init__(self, tok: Tokenizer, budget: int, make) -> None:
        self.tok, self.budget, self.make = tok, budget, make
        self.buf: list[Unit] = []
        self.buf_path: list[str] = []
        self.buf_tokens = 0
        self.out: list[Chunk] = []

    def _n(self, text: str) -> int:
        return len(self.tok.encode(text)) + 1  # +1 for the joining newline

    def flush(self) -> None:
        if self.buf:
            self.out.append(self.make(self.buf_path, self.buf))
        self.buf, self.buf_path, self.buf_tokens = [], [], 0

    def _fit(self, units: list[Unit]) -> list[Unit]:
        """Split any single unit that is larger than the budget."""
        fitted: list[Unit] = []
        for u in units:
            if self._n(u.text) <= self.budget:
                fitted.append(u)
            else:
                fitted += [
                    Unit(u.page, piece, u.is_table)
                    for piece in _split_tokens(self.tok, u.text, self.budget - 1)
                ]
        return fitted

    def add(self, path: list[str], units: list[Unit]) -> None:
        units = self._fit(units)
        total = sum(self._n(u.text) for u in units)
        if self.buf and self.buf_tokens + total <= self.budget:
            self.buf += units
            self.buf_tokens += total
            return
        self.flush()
        self.buf_path = path
        for u in units:
            n = self._n(u.text)
            if self.buf and self.buf_tokens + n > self.budget:
                self.flush()
                self.buf_path = path
            self.buf.append(u)
            self.buf_tokens += n


def _plain(doc_id: int, name: str):
    def make(path: list[str], units: list[Unit]) -> Chunk:
        return Chunk(
            doc_id=doc_id,
            chunker=name,
            page_start=min(u.page for u in units),
            page_end=max(u.page for u in units),
            section_path=_path(path),
            kind=_kind(units),
            content="\n".join(u.text for u in units),
        )

    return make


def chunk_structure(
    blocks: list[Block], tok: Tokenizer, max_tokens: int = MAX_TOKENS
) -> list[Chunk]:
    """Split at headings, merge small sections, split long ones at block boundaries."""
    if not blocks:
        return []
    p = _Packer(tok, max_tokens, _plain(blocks[0].doc_id, "structure"))
    for sec in _sections(blocks):
        p.add(sec.path, sec.units)
    p.flush()
    return p.out


# ----------------------------------------------------------- table_aware


def _context(meta: dict, path: list[str], caption: str | None = None) -> str:
    parts = [f"Bank: {meta['bank']}", f"Year: {meta['year']}"]
    if path:
        parts.append(f"Section: {_path(path)}")
    if caption:
        parts.append(f"Table: {caption[:150]}")
    return " | ".join(parts)


def _table_pieces(table: str, tok: Tokenizer, budget: int) -> list[str]:
    """Split a Markdown table by row groups, repeating the header row in every piece."""
    lines = table.splitlines()
    sep = next(
        (i for i, ln in enumerate(lines) if set(ln.replace("|", "").strip()) <= {"-", ":"}), 1
    )
    head, rows = lines[: sep + 1], lines[sep + 1 :]
    head_txt = "\n".join(head)
    head_n = len(tok.encode(head_txt)) + 1
    if head_n >= budget // 2:  # pathological header: fall back to plain splitting
        return _split_tokens(tok, table, budget)
    pieces: list[str] = []
    cur: list[str] = []
    cur_n = head_n
    for row in rows:
        n = len(tok.encode(row)) + 1
        if n + head_n > budget:  # one huge row: cut it
            if cur:
                pieces.append("\n".join([head_txt, *cur]))
                cur, cur_n = [], head_n
            pieces += [
                "\n".join([head_txt, cut]) for cut in _split_tokens(tok, row, budget - head_n - 1)
            ]
            continue
        if cur and cur_n + n > budget:
            pieces.append("\n".join([head_txt, *cur]))
            cur, cur_n = [], head_n
        cur.append(row)
        cur_n += n
    if cur:
        pieces.append("\n".join([head_txt, *cur]))
    return pieces or [table]


def chunk_table_aware(
    blocks: list[Block], doc_meta: dict, tok: Tokenizer, max_tokens: int = MAX_TOKENS
) -> list[Chunk]:
    """Like `structure`, but tables are separate chunks; every chunk gets a context header."""
    if not blocks:
        return []
    doc_id = blocks[0].doc_id

    # a caption directly before/after a table on the same page belongs to the table
    table_caption: dict[int, str] = {}
    consumed: set[int] = set()
    for i, b in enumerate(blocks):
        if b.kind != "table":
            continue
        for j in (i - 1, i + 1):
            near = blocks[j] if 0 <= j < len(blocks) else None
            if near and near.kind == "caption" and near.page_no == b.page_no:
                table_caption[i] = near.text
                consumed.add(j)
                break

    def make_text(path: list[str], units: list[Unit]) -> Chunk:
        body = "\n".join(u.text for u in units)
        return Chunk(
            doc_id=doc_id,
            chunker="table_aware",
            page_start=min(u.page for u in units),
            page_end=max(u.page for u in units),
            section_path=_path(path),
            kind="text",
            content=f"{_context(doc_meta, path)}\n{body}",
        )

    packer = _Packer(tok, max_tokens - HEADER_RESERVE, make_text)
    out: list[Chunk] = []

    # Walk sections, but treat each table as a barrier that is emitted on its own.
    for sec in _sections(blocks):
        run: list[Unit] = []
        for u in sec.units:
            if u.idx in consumed:
                continue
            if not u.is_table:
                run.append(u)
                continue
            if run:
                packer.add(sec.path, run)
                run = []
            packer.flush()
            out += packer.out
            packer.out = []
            header = _context(doc_meta, sec.path, table_caption.get(u.idx))
            budget = max_tokens - len(tok.encode(header)) - 1
            for piece in _table_pieces(u.text, tok, budget):
                out.append(
                    Chunk(
                        doc_id=doc_id,
                        chunker="table_aware",
                        page_start=u.page,
                        page_end=u.page,
                        section_path=_path(sec.path),
                        kind="table",
                        content=f"{header}\n{piece}",
                    )
                )
        if run:
            packer.add(sec.path, run)
    packer.flush()
    out += packer.out
    return out


# ------------------------------------------------------- ablation variants


def with_context_header(chunks: list[Chunk], doc_meta: dict, name: str) -> list[Chunk]:
    """Prefix chunks with the `Bank | Year | Section` header and rename the chunker."""
    out = []
    for c in chunks:
        header = _context(doc_meta, c.section_path.split(" > ") if c.section_path else [])
        out.append(c.model_copy(update={"chunker": name, "content": f"{header}\n{c.content}"}))
    return out


def without_context_header(chunks: list[Chunk], name: str) -> list[Chunk]:
    """Drop the first line (the context header) of table_aware chunks and rename the chunker."""
    return [
        c.model_copy(update={"chunker": name, "content": c.content.split("\n", 1)[1]})
        for c in chunks
    ]
