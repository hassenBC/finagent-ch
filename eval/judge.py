"""LLM judge: claim-level faithfulness against the CITED chunks only, and correctness vs gold.

One call per answer (budget). Faithfulness is decided before the judge reads the reference answer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from finagent.llm.client import LLMClient


class ClaimVerdict(BaseModel):
    claim: str
    verdict: Literal["supported", "partially", "not_supported"]


class Judgement(BaseModel):
    claims: list[ClaimVerdict]
    correctness: Literal["correct", "partially", "incorrect"]


PROMPT = """You are grading an answer produced by a retrieval system over Swiss bank annual reports.

PART 1 — FAITHFULNESS. Use ONLY the cited sources below; do not use the reference answer or
outside knowledge for this part.
Split the answer into atomic factual claims (one number, date, name or statement each; skip
phrases like "the sources do not say"). For each claim decide:
- supported: the cited sources state it (numbers must match, including unit and period);
- partially: part of it is stated, or it needs an inference the sources do not make explicit;
- not_supported: the cited sources do not state it, or contradict it.

PART 2 — CORRECTNESS. Now compare the answer with the reference answer:
- correct: it gives the reference answer (equivalent wording, numbers within rounding);
- partially: it is incomplete or partly wrong;
- incorrect: wrong, or it does not answer the question.

Question: {question}

Answer to grade:
{answer}

Cited sources:
{sources}

Reference answer: {reference}"""


def judge(
    question: str, answer: str, cited: list[str], reference: str, llm: LLMClient
) -> tuple[Judgement, float]:
    """Returns the judgement and its cost in USD."""
    sources = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(cited, 1)) or "(none)"
    r = llm.chat(
        [{"role": "user", "content": PROMPT.format(
            question=question, answer=answer, sources=sources, reference=reference or "(none)")}],
        response_format=Judgement,
        max_tokens=3000,
    )  # fmt: skip
    return r.parsed, r.cost_usd


def scores(j: Judgement) -> dict:
    n = len(j.claims)
    sup = sum(c.verdict == "supported" for c in j.claims)
    part = sum(c.verdict == "partially" for c in j.claims)
    return {
        "n_claims": n,
        "faithfulness": sup / n if n else 1.0,
        "faithfulness_lenient": (sup + 0.5 * part) / n if n else 1.0,
        "faithful": float(n > 0 and sup == n),  # every claim fully supported
        "correctness": {"correct": 1.0, "partially": 0.5, "incorrect": 0.0}[j.correctness],
    }
