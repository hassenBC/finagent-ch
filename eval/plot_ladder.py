"""Headline chart: what each retrieval change bought (recall@5), dev bars + test markers.

python -m eval.plot_ladder  ->  results/retrieval_ladder.png
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from finagent.config import ROOT  # noqa: E402

# Each step adds one change to the previous one.
STEPS = [
    ("A_fixed512_vector", "Baseline: fixed 512-token chunks,\ne5-small, vector search"),
    ("A_table_aware_vector", "+ table-aware chunks\nwith a context header"),
    ("B_table_aware_bge_m3_vector", "+ bge-m3 embeddings"),
    ("C_bge_m3_vector_filters", "+ bank / year metadata filters"),
    ("C_bge_m3_hybrid_filters_tsrank", "+ hybrid search (vector + FTS, RRF)"),
    ("C_bge_m3_hybrid_filters_translate_tsrank", "+ cross-lingual question translation"),
]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
DEV, TEST = "#2a78d6", "#eb6834"


def main() -> None:
    dev = pd.read_csv(ROOT / "results/retrieval.csv").set_index("config")
    test = pd.read_csv(ROOT / "results/retrieval_test.csv").set_index("config")
    fig, ax = plt.subplots(figsize=(8, 4.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ys = list(range(len(STEPS)))[::-1]
    for y, (cfg, _) in zip(ys, STEPS, strict=True):
        r = dev.loc[cfg]
        ax.barh(y, r["recall@5"], height=0.55, color=DEV, zorder=2,
                label="dev (n = 90), 95 % CI" if y == ys[0] else None)  # fmt: skip
        err = [[r["recall@5"] - r["recall@5_lo"]], [r["recall@5_hi"] - r["recall@5"]]]
        ax.errorbar(r["recall@5"], y, xerr=err, color=INK2, lw=1, capsize=3, zorder=3)
        ax.text(0.015, y, f"{r['recall@5']:.2f}", va="center", ha="left", color="white",
                fontsize=9, fontweight="bold", zorder=4)  # fmt: skip
        if cfg in test.index:
            ax.plot(test.loc[cfg, "recall@5"], y, "D", ms=8, color=TEST, mec=SURFACE, mew=2,
                    zorder=5, label="held-out test (n = 45), run once"
                    if cfg == "A_fixed512_vector" else None)  # fmt: skip
    ax.set_yticks(ys, [label for _, label in STEPS], color=INK, fontsize=9)
    ax.set_xlim(0, 1)
    ax.set_xlabel("recall@5 (page-level)", color=INK2, fontsize=9)
    ax.tick_params(colors=INK2, length=0, labelsize=9)
    ax.xaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=8,
              labelcolor=INK2, borderaxespad=0.2, handletextpad=0.5)  # fmt: skip
    ax.set_title("Retrieval: what each change bought", loc="left", color=INK, fontsize=11,
                 fontweight="bold", pad=22)  # fmt: skip
    fig.tight_layout()
    out = ROOT / "results/retrieval_ladder.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
