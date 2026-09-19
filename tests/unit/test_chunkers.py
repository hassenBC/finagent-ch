import pytest

from finagent.ingest.chunkers import chunk_fixed, chunk_structure, chunk_table_aware
from finagent.ingest.parse import Block


class WordTok:
    """One token per whitespace-separated word (newlines count as words to keep them)."""

    def __init__(self) -> None:
        self.vocab: dict[str, int] = {}
        self.inv: list[str] = []

    def encode(self, text: str) -> list[int]:
        ids = []
        for w in text.replace("\n", " \n ").split(" "):
            if not w:
                continue
            if w not in self.vocab:
                self.vocab[w] = len(self.inv)
                self.inv.append(w)
            ids.append(self.vocab[w])
        return ids

    def decode(self, ids: list[int]) -> str:
        return " ".join(self.inv[i] for i in ids).replace(" \n ", "\n")


def B(page, kind, text, path=(), level=None):
    return Block(doc_id=1, page_no=page, kind=kind, level=level, text=text, section_path=list(path))


def words(n, tag="w"):
    return " ".join(f"{tag}{i}" for i in range(n))


def table(n_rows):
    rows = [f"| row{i} | {i * 10} |" for i in range(n_rows)]
    return "\n".join(["| metric | value |", "|---|---|", *rows])


@pytest.fixture
def blocks():
    return [
        B(1, "heading", "Intro", ["Intro"], 1),
        B(1, "paragraph", words(30, "a"), ["Intro"]),
        B(2, "heading", "Capital", ["Intro", "Capital"], 2),
        B(2, "caption", "Table 3: Regulatory capital", ["Intro", "Capital"]),
        B(2, "table", table(60), ["Intro", "Capital"]),
        B(3, "paragraph", words(400, "b"), ["Intro", "Capital"]),
        B(4, "heading", "Outlook", ["Outlook"], 1),
        B(4, "paragraph", words(20, "c"), ["Outlook"]),
    ]


META = {"bank": "Vontobel", "year": 2025}
CAP = 100


def all_chunks(blocks):
    tok = WordTok()
    return tok, {
        "fixed": chunk_fixed(blocks, tok, size=CAP, overlap=10),
        "structure": chunk_structure(blocks, tok, max_tokens=CAP),
        "table_aware": chunk_table_aware(blocks, META, tok, max_tokens=CAP),
    }


def test_no_chunk_exceeds_token_cap(blocks):
    tok, chunkers = all_chunks(blocks)
    for name, chunks in chunkers.items():
        assert chunks, name
        for c in chunks:
            assert len(tok.encode(c.content)) <= CAP, (name, len(tok.encode(c.content)))


def test_fixed_windows_overlap_and_track_pages(blocks):
    _, chunkers = all_chunks(blocks)
    fixed = chunkers["fixed"]
    assert fixed[0].page_start == 1
    assert fixed[-1].page_end == 4
    assert all(c.page_start <= c.page_end for c in fixed)


def test_structure_merges_small_sections_and_keeps_pages(blocks):
    tok = WordTok()
    chunks = chunk_structure(blocks[:2] + blocks[-2:], tok, max_tokens=CAP)
    assert len(chunks) == 1  # two tiny sections merged
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 4)


def test_table_aware_isolates_tables_with_context_header(blocks):
    _, chunkers = all_chunks(blocks)
    tables = [c for c in chunkers["table_aware"] if c.kind == "table"]
    assert len(tables) > 1  # 60 rows do not fit in 100 tokens
    for t in tables:
        assert t.content.startswith("Bank: Vontobel | Year: 2025 | Section: Intro > Capital")
        assert "Table: Table 3: Regulatory capital" in t.content
        assert "| metric | value |" in t.content  # header row repeated in every piece
        assert t.page_start == t.page_end == 2
    texts = [c for c in chunkers["table_aware"] if c.kind == "text"]
    assert all("| row" not in c.content for c in texts)
    assert all(c.content.startswith("Bank: Vontobel") for c in texts)


def test_table_aware_keeps_every_row_once(blocks):
    _, chunkers = all_chunks(blocks)
    body = "\n".join(c.content for c in chunkers["table_aware"] if c.kind == "table")
    for i in range(60):
        assert body.count(f"| row{i} |") == 1


def test_caption_not_duplicated_as_text(blocks):
    _, chunkers = all_chunks(blocks)
    texts = [c for c in chunkers["table_aware"] if c.kind == "text"]
    assert not any("Table 3: Regulatory capital" in c.content for c in texts)
