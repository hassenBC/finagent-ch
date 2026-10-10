"""Build the RAG prompt: numbered sources with bank, report, page and section, plus the rules."""

from __future__ import annotations

from dataclasses import dataclass

from finagent.ingest.text import BANK_NAMES
from finagent.retrieval.types import Hit

SYSTEM = """You answer questions about Swiss banks using ONLY the numbered sources provided.
Rules:
- Use only facts stated in the sources. Never use outside knowledge.
- Cite every factual sentence with its source id(s) in square brackets, e.g. [S2] or [S1][S4].
- Give numbers with their unit and the period or date they refer to.
- Answer in the language of the question.
- If the sources do not contain the answer, set "abstain" to true and say briefly that the
  sources do not contain it.
- "citations" lists every source id you cited in the answer."""


@dataclass
class Source:
    sid: str  # "S1"
    hit: Hit
    bank: str
    year: int


def build_sources(hits: list[Hit], docs: dict[int, tuple[str, int]]) -> list[Source]:
    """docs: doc_id -> (bank key, fiscal year)."""
    return [Source(f"S{i}", h, *docs[h.doc_id]) for i, h in enumerate(hits, 1)]


def render_source(s: Source, section: str = "") -> str:
    pages = (
        f"p. {s.hit.page_start}"
        if s.hit.page_start == s.hit.page_end
        else f"pp. {s.hit.page_start}-{s.hit.page_end}"
    )
    head = f"[{s.sid}] {BANK_NAMES.get(s.bank, s.bank)} — Annual Report {s.year} — {pages}"
    if section:
        head += f" — {section}"
    return f"{head}\n{s.hit.content}"


def build_messages(question: str, sources: list[Source], sections: dict[int, str]) -> list[dict]:
    context = "\n\n".join(render_source(s, sections.get(s.hit.chunk_id, "")) for s in sources)
    user = f"Sources:\n\n{context}\n\nQuestion: {question}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
