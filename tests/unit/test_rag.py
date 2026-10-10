from finagent.rag.answer import Answer, resolve_citations
from finagent.rag.prompt import build_messages, build_sources, render_source
from finagent.retrieval.types import Hit


def H(cid, doc, a, b, content="x"):
    return Hit(
        chunk_id=cid, doc_id=doc, page_start=a, page_end=b, content=content, score=0, source="x"
    )


DOCS = {1: ("vontobel", 2025), 2: ("bcv", 2024)}


def test_sources_are_numbered_and_rendered_with_bank_year_page_section():
    srcs = build_sources([H(10, 1, 48, 48, "CET1 19.7%"), H(11, 2, 3, 4)], DOCS)
    assert [s.sid for s in srcs] == ["S1", "S2"]
    assert render_source(srcs[0], "Capital").startswith(
        "[S1] Vontobel — Annual Report 2025 — p. 48 — Capital\nCET1 19.7%"
    )
    assert "pp. 3-4" in render_source(srcs[1])
    msgs = build_messages("q?", srcs, {})
    assert msgs[0]["role"] == "system" and "[S2] BCV — Annual Report 2024" in msgs[1]["content"]


def test_citations_merge_list_and_inline_markers_and_flag_invalid_ids():
    srcs = build_sources([H(10, 1, 48, 48), H(11, 2, 3, 4)], DOCS)
    ans = Answer(answer="CET1 was 19.7% [S1]. Also [S9].", citations=["S2", "S1"], abstain=False)
    valid, invalid = resolve_citations(ans, srcs)
    assert [c.sid for c in valid] == ["S2", "S1"]
    assert (valid[1].doc_id, valid[1].page_start) == (1, 48)
    assert invalid == ["S9"]
