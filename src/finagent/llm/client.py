"""The only place the code talks to an LLM.

One client for every OpenAI-compatible endpoint (DeepSeek, vLLM on vast.ai, ...), with a
disk cache, retries, structured-output validation and per-call cost accounting.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from finagent.config import ROOT, load_config, secret
from finagent.llm.cache import DiskCache, request_key


class ToolCall(BaseModel):
    id: str
    name: str
    arguments_raw: str
    arguments: dict[str, Any] | None  # None when the model emitted invalid JSON


class ChatResult(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float  # 0.0 on a cache hit
    cached: bool
    model: str
    parsed: Any = Field(default=None, exclude=True)  # set when response_format is given


def _parse_tool_calls(raw: list[Any] | None) -> list[ToolCall]:
    calls = []
    for tc in raw or []:
        args_raw = tc.function.arguments or ""
        try:
            args = json.loads(args_raw)
            args = args if isinstance(args, dict) else None
        except json.JSONDecodeError:
            args = None
        calls.append(
            ToolCall(id=tc.id, name=tc.function.name, arguments_raw=args_raw, arguments=args)
        )
    return calls


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        price_in: float,
        price_out: float,
        cache_dir: str = str(ROOT / ".cache" / "llm"),
        max_retries: int = 5,
        client: Any = None,
    ):
        self.model = model
        self.price_in = price_in
        self.price_out = price_out
        self.cache = DiskCache(cache_dir)
        # The openai SDK retries 408/409/429/5xx and timeouts with exponential backoff.
        self._client = client or OpenAI(base_url=base_url, api_key=api_key, max_retries=max_retries)

    @classmethod
    def from_config(cls, name: str | None = None) -> LLMClient:
        cfg = load_config().llm
        spec = cfg.models[name or cfg.default]
        provider = cfg.providers[spec.provider]
        return cls(
            base_url=provider.base_url,
            api_key=secret(provider.api_key_env),
            model=spec.model,
            price_in=spec.price_in,
            price_out=spec.price_out,
            cache_dir=str(ROOT / cfg.cache_dir),
        )

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: type[BaseModel] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ChatResult:
        if response_format is None:
            return self._complete(messages, tools, False, temperature, max_tokens)

        schema = json.dumps(response_format.model_json_schema())
        messages = [
            {
                "role": "system",
                "content": f"Reply with one JSON object matching this schema:\n{schema}",
            },
            *messages,
        ]
        first = self._complete(messages, tools, True, temperature, max_tokens)
        try:
            first.parsed = response_format.model_validate_json(first.text or "")
            return first
        except ValidationError as err:
            retry_messages = [
                *messages,
                {"role": "assistant", "content": first.text or ""},
                {
                    "role": "user",
                    "content": f"That JSON was invalid:\n{err}\nReturn only corrected JSON.",
                },
            ]
        second = self._complete(retry_messages, tools, True, temperature, max_tokens)
        second.parsed = response_format.model_validate_json(
            second.text or ""
        )  # raises if still bad
        return second.model_copy(
            update={
                "tokens_in": first.tokens_in + second.tokens_in,
                "tokens_out": first.tokens_out + second.tokens_out,
                "latency_ms": first.latency_ms + second.latency_ms,
                "cost_usd": first.cost_usd + second.cost_usd,
                "cached": first.cached and second.cached,
            }
        )

    def _complete(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        key = request_key(
            model=self.model,
            messages=messages,
            tools=tools,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        start = time.perf_counter()
        if (hit := self.cache.get(key)) is not None:
            elapsed = int((time.perf_counter() - start) * 1000)
            return ChatResult(
                **hit, latency_ms=elapsed, cost_usd=0.0, cached=True, model=self.model
            )

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)

        msg = resp.choices[0].message
        usage = resp.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        payload = {
            "text": msg.content,
            "tool_calls": [tc.model_dump() for tc in _parse_tool_calls(msg.tool_calls)],
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
        self.cache.set(key, payload)
        return ChatResult(
            **payload,
            latency_ms=latency_ms,
            cost_usd=self.cost(tokens_in, tokens_out),
            cached=False,
            model=self.model,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="One-off LLM call through the cached client.")
    parser.add_argument("prompt", nargs="?", default="Say hi")
    parser.add_argument("--model", help="key under llm.models in configs/base.yaml")
    parser.add_argument(
        "--list-models", action="store_true", help="list ids served by the endpoint"
    )
    args = parser.parse_args()

    client = LLMClient.from_config(args.model)
    if args.list_models:
        for m in client._client.models.list():
            print(m.id)
        return
    r = client.chat([{"role": "user", "content": args.prompt}])
    print(r.text)
    print(
        f"model={r.model} cached={r.cached} tokens_in={r.tokens_in} tokens_out={r.tokens_out} "
        f"latency_ms={r.latency_ms} cost_usd={r.cost_usd:.6f}"
    )


if __name__ == "__main__":
    main()
