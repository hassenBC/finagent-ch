from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel, ValidationError

from finagent.llm.cache import request_key
from finagent.llm.client import LLMClient


class FakeOpenAI:
    """Mimics client.chat.completions.create; returns queued replies and records calls."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content, tool_calls = self.replies.pop(0)
        msg = NS(content=content, tool_calls=tool_calls)
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=100, completion_tokens=50))


def make_client(tmp_path, *replies):
    fake = FakeOpenAI(*replies)
    client = LLMClient(
        "http://x", "k", "m", price_in=2.0, price_out=10.0, cache_dir=str(tmp_path), client=fake
    )
    return client, fake


def tool_call(name, args):
    return NS(id="call_1", function=NS(name=name, arguments=args))


HI = [{"role": "user", "content": "hi"}]


def test_cost_is_computed_from_prices(tmp_path):
    client, _ = make_client(tmp_path, ("hello", None))
    r = client.chat(HI)
    assert r.text == "hello" and not r.cached
    assert r.cost_usd == pytest.approx((100 * 2.0 + 50 * 10.0) / 1e6)


def test_second_identical_call_is_cached_and_free(tmp_path):
    client, fake = make_client(tmp_path, ("hello", None))
    client.chat(HI)
    r = client.chat(HI)
    assert r.cached and r.cost_usd == 0.0 and r.text == "hello"
    assert len(fake.calls) == 1


def test_temperature_changes_cache_key(tmp_path):
    client, fake = make_client(tmp_path, ("a", None), ("b", None))
    client.chat(HI, temperature=0.0)
    r = client.chat(HI, temperature=0.7)
    assert r.text == "b" and len(fake.calls) == 2


def test_request_key_ignores_dict_order():
    assert request_key(a=1, b={"x": 1, "y": 2}) == request_key(b={"y": 2, "x": 1}, a=1)


def test_tool_calls_parsed_and_invalid_json_kept_raw(tmp_path):
    client, _ = make_client(
        tmp_path,
        (None, [tool_call("calculate", '{"expr": "1+1"}')]),
        (None, [tool_call("calculate", '{"expr": ')]),
    )
    ok = client.chat(HI, tools=[{"type": "function"}])
    bad = client.chat([{"role": "user", "content": "again"}], tools=[{"type": "function"}])
    assert ok.tool_calls[0].arguments == {"expr": "1+1"}
    assert bad.tool_calls[0].arguments is None
    assert bad.tool_calls[0].arguments_raw == '{"expr": '


class Verdict(BaseModel):
    label: str
    score: float


def test_response_format_validated(tmp_path):
    client, fake = make_client(tmp_path, ('{"label": "ok", "score": 0.9}', None))
    r = client.chat(HI, response_format=Verdict)
    assert r.parsed == Verdict(label="ok", score=0.9)
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_response_format_retries_once_and_sums_cost(tmp_path):
    client, fake = make_client(
        tmp_path, ('{"label": "ok"}', None), ('{"label": "ok", "score": 1}', None)
    )
    r = client.chat(HI, response_format=Verdict)
    assert r.parsed.score == 1.0
    assert len(fake.calls) == 2
    assert "invalid" in fake.calls[1]["messages"][-1]["content"]
    assert r.tokens_in == 200


def test_response_format_raises_after_second_failure(tmp_path):
    client, _ = make_client(tmp_path, ("nope", None), ("still nope", None))
    with pytest.raises(ValidationError):
        client.chat(HI, response_format=Verdict)


def test_cache_salt_gives_separate_entries_and_none_keeps_the_old_key(tmp_path):
    from finagent.llm.cache import request_key

    base = dict(model="m", messages=[], tools=None, json_mode=False, temperature=0.0,
                max_tokens=5)  # fmt: skip
    assert request_key(**base) != request_key(**base, salt="run1")
