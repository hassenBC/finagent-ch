"""Shared retrieval types: Hit, Filters and the experiment config."""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, Field

from finagent.config import ROOT


class Hit(BaseModel):
    chunk_id: int
    doc_id: int
    page_start: int
    page_end: int
    content: str
    score: float
    source: str  # 'fts' | 'vector' | 'fused' | 'rerank'


class Filters(BaseModel):
    banks: list[str] | None = None
    years: list[int] | None = None


class Fusion(BaseModel):
    k: int = 60
    fts_candidates: int = 50
    vector_candidates: int = 50


class FTSOptions(BaseModel):
    rank: Literal["cd", "plain"] = "cd"  # ts_rank_cd (cover density) or ts_rank
    normalization: int = 0  # Postgres rank normalisation flags, e.g. 1 = divide by 1+log(length)
    max_df: float | None = None  # drop query terms found in more than this share of chunks


class Rerank(BaseModel):
    enabled: bool = False
    model: str = "BAAI/bge-reranker-v2-m3"
    candidates: int = 50


class Expansion(BaseModel):
    enabled: bool = False
    n: int = 3
    model: str = "deepseek_flash"


class RetrievalConfig(BaseModel):
    name: str
    chunker: str = "table_aware"
    embedding_model: Literal["e5_small", "e5_large", "bge_m3"] = "e5_small"
    retrieval: Literal["fts", "vector", "hybrid"] = "hybrid"
    fusion: Fusion = Field(default_factory=Fusion)
    fts: FTSOptions = Field(default_factory=FTSOptions)
    use_metadata_filters: bool = False
    rerank: Rerank = Field(default_factory=Rerank)
    expansion: Expansion = Field(default_factory=Expansion)
    ann: bool = True  # False = exact vector search (no HNSW), for measuring approximation loss
    top_k: int = 10
    dataset: str = "eval/datasets/qa_dev.jsonl"

    @classmethod
    def from_yaml(cls, path: str) -> RetrievalConfig:
        with open(ROOT / path if not path.startswith("/") else path) as f:
            return cls.model_validate(yaml.safe_load(f))
