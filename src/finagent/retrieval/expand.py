"""Multi-query expansion: an LLM rewrites the question, one rewrite in the other language."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel

from finagent.llm.client import LLMClient


class Reformulations(BaseModel):
    queries: list[str]


PROMPT = """Rewrite a question so it retrieves better from annual reports of Swiss banks
(English and French). Return {n} alternative search queries:
- keep every bank name, year and number exactly as given;
- use the financial terms and synonyms a report would use for the metric;
- write exactly one of them in {other} (the question is in {lang});
- keep each query short.

Question: {q}"""


@lru_cache
def _client(model: str) -> LLMClient:
    return LLMClient.from_config(model)


FAILURES: list[str] = []  # questions whose expansion failed (retrieval then uses the original only)


def expand_query(query: str, n: int = 3, model: str = "deepseek_flash") -> list[str]:
    try:
        return _expand(query, n, model)
    except ValueError as e:  # pydantic ValidationError subclasses ValueError
        FAILURES.append(query)
        print(f"expansion failed, using the original query only: {str(e)[:80]}", flush=True)
        return []


def _expand(query: str, n: int, model: str) -> list[str]:
    french = (
        sum(w in query.lower().split() for w in ("le", "la", "les", "des", "quel", "quelle")) > 0
    )
    lang, other = ("French", "English") if french else ("English", "French")
    r = _client(model).chat(
        [{"role": "user", "content": PROMPT.format(n=n, q=query, lang=lang, other=other)}],
        response_format=Reformulations,
        max_tokens=2000,
    )
    return [q.strip() for q in r.parsed.queries if q.strip()][:n]
