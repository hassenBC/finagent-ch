"""The second injection suite is well-formed and does not collide with the first (no DB, no LLM)."""

import json
import re

from eval.build_injection_v2 import build
from eval.run_security import marker
from finagent.config import ROOT
from finagent.policy.model import load_policy, recipient_is_internal


def test_forty_attacks_with_unique_ids_and_markers():
    cases = build()
    assert len(cases) == 40
    assert len({c["id"] for c in cases}) == 40
    markers = {marker(c) for c in cases}
    assert len(markers) == 40
    first = [
        json.loads(x) for x in (ROOT / "eval/datasets/injection.jsonl").read_text().splitlines()
    ]
    assert not markers & {marker(c) for c in first}
    assert not {c["id"] for c in cases} & {c["id"] for c in first}


def test_every_text_carries_its_marker_and_an_external_recipient():
    cfg = load_policy()
    for c in build():
        text = c["planted"]["text"]
        assert marker(c) in text
        assert c["check"] == "exfil" and c["planted"]["type"] == "doc"
        addresses = re.findall(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text)
        assert addresses and not any(recipient_is_internal(a, cfg) for a in addresses)


def test_committed_dataset_matches_the_builder():
    path = ROOT / "eval/datasets/injection_v2.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert rows == build()
