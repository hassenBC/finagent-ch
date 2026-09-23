"""Dataset invariants: file checks, plus gold pages and evidence against the ingested DB."""

import json
from collections import Counter
from pathlib import Path

import psycopg
import pytest

from eval.build_candidates import TARGETS
from eval.dataset_utils import evidence_on_pages
from finagent.config import env

DATA = Path(__file__).resolve().parents[2] / "eval" / "datasets"
TYPES = set(TARGETS)


def load(name):
    return [json.loads(line) for line in (DATA / f"qa_{name}.jsonl").read_text().splitlines()]


@pytest.fixture(scope="module")
def items():
    return load("dev") + load("test")


def test_sizes_and_unique_ids(items):
    assert len(load("dev")) == 100 and len(load("test")) == 50
    assert len({i["id"] for i in items}) == len(items) == 150
    assert not {i["question"] for i in load("dev")} & {i["question"] for i in load("test")}


def test_type_mix_matches_targets_within_two(items):
    counts = Counter(i["type"] for i in items)
    assert set(counts) == TYPES
    for t, n in TARGETS.items():
        assert abs(counts[t] - n) <= 2, (t, counts[t], n)


def test_schema_and_answerability(items):
    for i in items:
        assert i["lang"] in {"en", "fr"} and i["type"] in TYPES
        assert len(i["question"].strip()) > 20
        if i["answerable"]:
            assert i["gold_pages"] and i["evidence"] and i["answer"]
        else:
            assert i["type"] == "unanswerable" and not i["gold_pages"]
        if i["type"] == "comparison":
            assert len({(p["sha256"], p["page"]) for p in i["gold_pages"]}) == 2
        if i["answer_numeric"]:
            assert i["answer_numeric"]["tolerance"] > 0


def test_split_is_stratified_by_type(items):
    dev, test = Counter(i["type"] for i in load("dev")), Counter(i["type"] for i in load("test"))
    for t in TYPES:
        assert abs(test[t] / (dev[t] + test[t]) - 1 / 3) < 0.15, t


def test_about_half_paraphrased(items):
    share = sum(i["paraphrased"] for i in items) / len(items)
    assert 0.4 <= share <= 0.7


@pytest.mark.integration
def test_gold_pages_exist_and_contain_evidence(items):
    try:
        conn = psycopg.connect(env().database_url, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (make db-up)")
    with conn:
        pages = {
            (sha, pn): text
            for sha, pn, text in conn.execute(
                "SELECT d.sha256, p.page_no, p.text FROM pages p JOIN documents d USING (doc_id)"
            )
        }
    if not pages:
        pytest.skip("no documents ingested (make ingest)")
    for i in items:
        texts = []
        for g in i["gold_pages"]:
            assert (g["sha256"], g["page"]) in pages, (i["id"], g)
            texts.append(pages[(g["sha256"], g["page"])])
        if i["answerable"]:
            assert evidence_on_pages(i["evidence"], texts), (i["id"], i["evidence"][:80])
