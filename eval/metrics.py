"""Retrieval metrics with page-level relevance, plus bootstrap confidence intervals."""

from __future__ import annotations

import math

import numpy as np

from finagent.retrieval.types import Hit

Pages = set[tuple[int, int]]  # (doc_id, page_no)


def is_relevant(hit: Hit, pages: Pages) -> bool:
    """A chunk is relevant if its page span overlaps any gold/alternate page of the same doc."""
    return any((hit.doc_id, p) in pages for p in range(hit.page_start, hit.page_end + 1))


def recall_at_k(rel: list[bool], k: int) -> float:
    return float(any(rel[:k]))


def reciprocal_rank(rel: list[bool], k: int = 10) -> float:
    for i, r in enumerate(rel[:k], 1):
        if r:
            return 1.0 / i
    return 0.0


def ndcg_at_k(rel: list[bool], k: int, n_relevant: int) -> float:
    """Binary-relevance nDCG; the ideal list holds min(k, n_relevant) relevant chunks."""
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(rel[:k], 1) if r)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, max(n_relevant, 1)) + 1))
    return dcg / ideal


def page_coverage(hits: list[Hit], primary: Pages, k: int) -> float:
    """Share of the primary gold pages that some top-k hit covers (multi-page answers)."""
    if not primary:
        return 0.0
    covered = {
        (h.doc_id, p) for h in hits[:k] for p in range(h.page_start, h.page_end + 1)
    } & primary
    return len(covered) / len(primary)


def bootstrap_ci(
    values: list[float], n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Mean and percentile-bootstrap CI, resampling questions."""
    x = np.asarray(values, dtype=float)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(x.mean()), float(lo), float(hi)


def paired_bootstrap(
    a: list[float], b: list[float], n_boot: int = 1000, seed: int = 0
) -> tuple[float, float, float]:
    """Mean of (a - b) per question with its CI; claim 'a beats b' only if the CI excludes 0."""
    if len(a) != len(b):
        raise ValueError("paired samples must be aligned")
    return bootstrap_ci(list(np.asarray(a) - np.asarray(b)), n_boot, seed)


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")
