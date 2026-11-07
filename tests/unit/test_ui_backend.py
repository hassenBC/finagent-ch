"""Demo-app backend invariants found in peer review (no database, no MCP server needed)."""

import threading

import pytest

from finagent.ui.app import Run, _render_page


def run() -> Run:
    return Run("q", "routed", "policy", "deepseek_flash")


def test_concurrent_emitters_get_unique_contiguous_sequence_numbers():
    r = run()
    threads = [threading.Thread(target=lambda: [r.emit("x", {}) for _ in range(200)])
               for _ in range(8)]  # fmt: skip
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seqs = [e["seq"] for e in r.log]
    assert seqs == list(range(1, 1601))


def test_replay_from_a_cursor_returns_exactly_the_missed_events():
    r = run()
    for k in ("a", "b", "c", "d"):
        r.emit(k, {})
    assert [e["kind"] for e in r.wait_events(2, 0.01)] == ["c", "d"]
    assert r.wait_events(4, 0.01) == []  # nothing new: returns after the timeout
    # several subscribers each see the full log (the log is not consumed)
    assert [e["kind"] for e in r.wait_events(0, 0.01)] == ["a", "b", "c", "d"]


def test_approval_is_accepted_only_for_the_pending_id_and_only_once():
    r = run()
    assert not r.answer_approval("anything", True)  # nothing pending
    r.pending_id = "a1"
    assert not r.answer_approval("other", True)  # wrong id
    assert r.answer_approval("a1", False)  # the pending one
    assert r.pending_answer is False and r.pending_event.is_set()
    assert not r.answer_approval("a1", True)  # double click / retry


@pytest.mark.parametrize(
    "source",
    ["", "efg", "efg-2025", "efg-2025-12", "efg-2025-p", "efg-25-p3", "evil-2025-p1",
     "efg-2025-p1/../../etc", "../efg-2025-p1", "efg-2025-p99999", "efg-2025-p1-extra"],
)  # fmt: skip
def test_page_renderer_rejects_bad_or_hostile_ids(source):
    assert _render_page(source) is None
