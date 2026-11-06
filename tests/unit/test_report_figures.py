"""Every report/paper figure renders from the committed results (catches a changed CSV breaking the
notebook or the paper before anyone opens them)."""

import sys
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "report"))
import figures as F  # noqa: E402

FIGS = [name for name in dir(F) if name.startswith("fig_")]


@pytest.mark.parametrize("name", FIGS)
def test_figure_renders(name, tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OUT", tmp_path)
    fig = getattr(F, name)()
    if name == "fig_models" and fig is None:  # needs Phase 9 results
        pytest.skip("no model-comparison results yet")
    assert (tmp_path / f"{name.removeprefix('fig_')}.pdf").exists() or any(tmp_path.iterdir())
    matplotlib.pyplot.close("all")


def test_every_figure_used_by_the_paper_has_a_function():
    tex = (Path(__file__).resolve().parents[2] / "paper/main.tex").read_text()
    import re

    used = set(re.findall(r"figures/([a-z_]+)\.pdf", tex))
    rendered = set()
    for name in FIGS:
        src = __import__("inspect").getsource(getattr(F, name))
        rendered |= set(re.findall(r'_save\(fig, "([a-z_]+)"\)', src))
    assert used <= rendered, used - rendered
