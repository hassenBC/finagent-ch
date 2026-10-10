"""answer(question, hits) -> Answer with citations mapped back to (doc, pages)."""

from __future__ import annotations

import re

from pydantic import BaseModel

from finagent.db import pool
from finagent.llm.client import ChatResult, LLMClient
from finagent.rag.prompt import Source, build_messages, build_sources
from finagent.retrieval.types import Hit

_SID = re.compile(r"\[(S\d+)\]")


class Answer(BaseModel):
    answer: str
    citations: list[str]  # ["S3", "S7"]
    abstain: bool


class CitedSource(BaseModel):
    sid: str
    chunk_id: int
    doc_id: int
    page_start: int
    page_end: int


class RagResult(BaseModel):
    answer: str
    abstain: bool
    citations: list[CitedSource]  # valid citations only
    invalid_citations: list[str]  # ids that point to no source in the context
    n_sources: int
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    cached: bool


def resolve_citations(ans: Answer, sources: list[Source]) -> tuple[list[CitedSource], list[str]]:
    """Union of the ids in `citations` and the [S#] markers in the text, mapped to pages."""
    by_id = {s.sid: s for s in sources}
    ids = list(dict.fromkeys([*ans.citations, *_SID.findall(ans.answer)]))
    valid, invalid = [], []
    for sid in ids:
        sid = sid.strip("[] ")
        if sid in by_id:
            h = by_id[sid].hit
            valid.append(
                CitedSource(
                    sid=sid,
                    chunk_id=h.chunk_id,
                    doc_id=h.doc_id,
                    page_start=h.page_start,
                    page_end=h.page_end,
                )
            )
        else:
            invalid.append(sid)
    return valid, invalid


def _doc_meta() -> dict[int, tuple[str, int]]:
    with pool().connection() as conn:
        return {d: (b, y) for d, b, y in conn.execute("SELECT doc_id, bank, year FROM documents")}


def _sections(chunk_ids: list[int]) -> dict[int, str]:
    with pool().connection() as conn:
        return dict(
            conn.execute(
                "SELECT chunk_id, coalesce(section_path, '') FROM chunks WHERE chunk_id = ANY(%s)",
                (chunk_ids,),
            ).fetchall()
        )


def answer(question: str, hits: list[Hit], llm: LLMClient, max_tokens: int = 2000) -> RagResult:
    sources = build_sources(hits, _doc_meta())
    messages = build_messages(question, sources, _sections([h.chunk_id for h in hits]))
    r: ChatResult = llm.chat(messages, response_format=Answer, max_tokens=max_tokens)
    ans: Answer = r.parsed
    valid, invalid = resolve_citations(ans, sources)
    return RagResult(
        answer=ans.answer,
        abstain=ans.abstain,
        citations=valid,
        invalid_citations=invalid,
        n_sources=len(sources),
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        latency_ms=r.latency_ms,
        cost_usd=r.cost_usd,
        cached=r.cached,
    )
