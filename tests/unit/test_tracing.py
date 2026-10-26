from finagent import tracing


def test_spans_are_off_by_default_and_nest_when_on(monkeypatch):
    saved = []
    monkeypatch.setattr(tracing, "_save", lambda *a: saved.append(a))
    with tracing.span("off"):
        pass
    assert saved == []  # FINAGENT_TRACING not set

    monkeypatch.setenv("FINAGENT_TRACING", "1")
    tracing.start("00000000-0000-0000-0000-000000000001")
    with tracing.span("outer", a=1) as outer:
        with tracing.span("inner") as inner:
            inner.set(hits=3)
        outer.set(done=True)
    (t1, sid_in, parent_in, name_in, *_r1, attrs_in), (t2, sid_out, parent_out, name_out, *_r2,
                                                       attrs_out) = saved  # fmt: skip
    assert (name_in, name_out) == ("inner", "outer") and parent_in == sid_out and parent_out is None
    assert attrs_in == {"hits": 3} and attrs_out == {"a": 1, "done": True} and t1 == t2


def test_errors_are_recorded_and_reraised(monkeypatch):
    saved = []
    monkeypatch.setattr(tracing, "_save", lambda *a: saved.append(a))
    monkeypatch.setenv("FINAGENT_TRACING", "1")
    tracing.start("00000000-0000-0000-0000-000000000002")
    try:
        with tracing.span("boom"):
            raise ValueError("x")
    except ValueError:
        pass
    assert "ValueError" in saved[0][-1]["error"]
