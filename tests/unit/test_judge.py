from types import SimpleNamespace

from eval.judge import Judgement, judge


class FakeLLM:
    """Empty output at the first budget (reasoning used it all), valid JSON at a larger one."""

    def __init__(self):
        self.budgets = []

    def chat(self, messages, response_format, max_tokens):
        self.budgets.append(max_tokens)
        if max_tokens <= 3000:
            raise ValueError("Invalid JSON: EOF while parsing")  # pydantic ValidationError is one
        parsed = Judgement(claims=[], correctness="correct")
        return SimpleNamespace(parsed=parsed, cost_usd=0.01)


def test_judge_retries_with_larger_budget_when_output_is_empty():
    llm = FakeLLM()
    j, cost = judge("q", "a", ["src"], "ref", llm)
    assert j.correctness == "correct"
    assert llm.budgets[0] == 3000  # first call unchanged so cached judgements stay valid
    assert llm.budgets[1] > 3000
    assert cost == 0.01
