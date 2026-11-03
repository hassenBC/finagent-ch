"""Figures for the report notebook and the paper, one function per figure, all from results/*.csv.

Style (dataviz guidance): grey for context and baselines, blue for "our system", status colours only for
pass/fail, one axis per chart, direct labels on few marks, white background so figures print.
Each function returns the matplotlib figure and saves paper/figures/<name>.pdf.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "paper/figures"

BLUE, BLUE_LIGHT = "#2a78d6", "#9ec5f4"
ORANGE, AQUA, VIOLET = "#eb6834", "#1baf7a", "#6250d6"
GREY, GREY_LIGHT, INK, MUTED = "#8a8a93", "#d4d4d8", "#1f1f23", "#5b5b63"
GOOD, WARN, BAD = "#0ca30c", "#fab219", "#d03b3b"

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 200, "font.size": 9.5, "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.labelcolor": MUTED,
    "axes.edgecolor": GREY_LIGHT, "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": False, "legend.frameon": False,
    "font.family": ["DejaVu Sans"], "pdf.fonttype": 42,
})  # fmt: skip


def _save(fig, name: str):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    return fig


def _hgrid(ax):
    ax.yaxis.grid(True, color="#ececef", lw=0.8)
    ax.set_axisbelow(True)


# --- data -----------------------------------------------------------------------------------
def dataset_mix() -> pd.DataFrame:
    rows = []
    for split in ("dev", "test"):
        for line in (ROOT / f"eval/datasets/qa_{split}.jsonl").read_text().splitlines():
            rows.append({"split": split, "type": json.loads(line)["type"]})
    return pd.crosstab(pd.DataFrame(rows)["type"], pd.DataFrame(rows)["split"])


def fig_dataset():
    t = dataset_mix().sort_values("dev")
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    y = np.arange(len(t))
    ax.barh(y + 0.2, t["dev"], height=0.38, color=BLUE, label="dev (100, used for tuning)")
    ax.barh(y - 0.2, t["test"], height=0.38, color=GREY, label="test (50, run once)")
    ax.set_yticks(y, [s.replace("_", " ") for s in t.index])
    ax.set_xlabel("questions")
    ax.legend(loc="lower right")
    ax.set_title("Evaluation set: 150 questions with known evidence pages")
    return _save(fig, "dataset")


# --- retrieval --------------------------------------------------------------------------------
LADDER = [
    ("A_fixed512_vector", "Baseline: fixed 512-token chunks,\ne5-small, vector"),
    ("A_table_aware_vector", "+ table-aware chunks\nwith context header"),
    ("B_table_aware_bge_m3_vector", "+ bge-m3 embeddings"),
    ("C_bge_m3_vector_filters", "+ bank/year filters"),
    ("C_bge_m3_hybrid_filters_tsrank", "+ hybrid (vector + FTS, RRF)"),
    ("C_bge_m3_hybrid_filters_translate_tsrank", "+ question translation"),
]


def fig_ladder():
    dev = pd.read_csv(RES / "retrieval.csv").set_index("config")
    test = pd.read_csv(RES / "retrieval_test.csv").set_index("config")
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    ys = np.arange(len(LADDER))[::-1]
    for i, (y, (cfg, _label)) in enumerate(zip(ys, LADDER, strict=True)):
        r = dev.loc[cfg]
        color = GREY if i == 0 else (BLUE if i == len(LADDER) - 1 else BLUE_LIGHT)
        ax.barh(y, r["recall@5"], height=0.6, color=color)
        ax.errorbar(r["recall@5"], y, xerr=[[r["recall@5"] - r["recall@5_lo"]],
                    [r["recall@5_hi"] - r["recall@5"]]], color=MUTED, lw=1, capsize=2.5)  # fmt: skip
        ax.text(0.012, y, f"{r['recall@5']:.2f}", va="center", color="white", fontsize=8.5,
                fontweight="bold")  # fmt: skip
        if cfg in test.index:
            ax.plot(test.loc[cfg, "recall@5"], y, "D", ms=6.5, color=ORANGE, mec="white", mew=1.2,
                    label="held-out test" if cfg == LADDER[0][0] else None)  # fmt: skip
    ax.set_yticks(ys, [lbl for _, lbl in LADDER], fontsize=8.5)
    ax.set_xlim(0, 1)
    ax.set_xlabel("recall@5 (share of questions whose evidence page is in the top 5)")
    ax.legend(loc="upper right")
    ax.set_title("Retrieval: what each change bought (dev bars, 95% CI)")
    return _save(fig, "retrieval_ladder")


def fig_header_ablation():
    dev = pd.read_csv(RES / "retrieval.csv").set_index("config")
    rows = [("A_fixed512_vector", "fixed 512 tokens", GREY),
            ("A_structure_vector", "structure chunks", GREY),
            ("X_structure_hdr_vector", "structure + header", BLUE),
            ("X_table_aware_nohdr_vector", "table-aware, no header", GREY),
            ("A_table_aware_vector", "table-aware + header", BLUE)]  # fmt: skip
    fig, ax = plt.subplots(figsize=(6.2, 2.6))
    y = np.arange(len(rows))[::-1]
    for yy, (cfg, _label, c) in zip(y, rows, strict=True):
        v = dev.loc[cfg, "recall@5"]
        ax.barh(yy, v, color=c, height=0.6)
        ax.text(v + 0.01, yy, f"{v:.2f}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y, [r[1] for r in rows])
    ax.set_xlim(0, 0.85)
    ax.set_xlabel("recall@5 (dev, e5-small, vector search)")
    ax.set_title("The one-line chunk header, not table isolation, drives the gain")
    return _save(fig, "header_ablation")


def fig_fts_rank():
    dev = pd.read_csv(RES / "retrieval.csv").set_index("config")
    rows = [
        ("A_table_aware_fts", "ts_rank_cd (cover density)", GREY),
        ("F_table_aware_fts_plain_norm1", "ts_rank + length normalisation", BLUE),
        ("A_table_aware_vector", "for reference: e5-small vector", GREY_LIGHT),
    ]
    fig, ax = plt.subplots(figsize=(6.2, 1.9))
    y = np.arange(len(rows))[::-1]
    for yy, (cfg, _label, c) in zip(y, rows, strict=True):
        v = dev.loc[cfg, "recall@5"]
        ax.barh(yy, v, color=c, height=0.6)
        ax.text(v + 0.01, yy, f"{v:.2f}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y, [r[1] for r in rows])
    ax.set_xlim(0, 0.85)
    ax.set_xlabel("recall@5, Postgres full-text search with an OR query (dev)")
    ax.set_title("A ranking function choice that nearly hid a result")
    return _save(fig, "fts_rank")


def fig_by_type():
    t = pd.read_csv(RES / "retrieval_test_by_type.csv")
    base, best = "A_fixed512_vector", "C_bge_m3_hybrid_filters_translate_tsrank"
    t = t[t["config"].isin([base, best])].pivot(index="type", columns="config", values="recall@5")
    t = t.sort_values(best)
    fig, ax = plt.subplots(figsize=(6.2, 2.8))
    y = np.arange(len(t))
    for yy, (_, r) in zip(y, t.iterrows(), strict=True):
        ax.plot([r[base], r[best]], [yy, yy], color=GREY_LIGHT, lw=2, zorder=1)
    ax.scatter(t[base], y, color=GREY, s=36, zorder=2, label="baseline")
    ax.scatter(t[best], y, color=BLUE, s=36, zorder=3, label="final system")
    ax.set_yticks(y, [s.replace("_", " ") for s in t.index])
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("recall@5 on the held-out test set, by question type")
    ax.legend(loc="lower right")
    ax.set_title("Gains by question type (test)")
    return _save(fig, "retrieval_by_type")


def fig_errors():
    e = pd.read_csv(RES / "error_analysis.csv")["cause"].value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(6.2, 2.2))
    colors = [BLUE if "cross-lingual" in c else GREY for c in e.index]
    ax.barh(e.index, e.values, color=colors, height=0.6)
    for i, v in enumerate(e.values):
        ax.text(v + 0.1, i, str(v), va="center", fontsize=8.5)
    ax.set_xlabel("missed questions (best dev configuration before the fix)")
    ax.set_title("Error analysis: the top cause was fixable")
    return _save(fig, "error_analysis")


# --- RAG --------------------------------------------------------------------------------------
def fig_k_sweep():
    d = pd.read_csv(RES / "rag_dev.csv").set_index("config")
    ks = [3, 5, 10]
    em = [d.loc[f"rag_best_k{k}", "numeric_em"] for k in ks]
    fa = [d.loc[f"rag_best_k{k}", "false_abstention_rate"] for k in ks]
    cost = [1000 * d.loc[f"rag_best_k{k}", "cost_per_query_usd"] for k in ks]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.3))
    for ax, vals, title, fmt, color in [
        (axes[0], em, "numeric answer correct", "{:.2f}", BLUE),
        (axes[1], fa, "refused although answerable", "{:.2f}", WARN),
        (axes[2], cost, "cost per question (US$ / 1000)", "{:.1f}", GREY),
    ]:  # fmt: skip
        ax.plot(ks, vals, "-o", color=color, lw=2, ms=5)
        for k, v in zip(ks, vals, strict=True):
            ax.annotate(fmt.format(v), (k, v), textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=8.5)  # fmt: skip
        ax.set_xticks(ks)
        ax.set_xlabel("passages given to the model (k)")
        ax.set_title(title, fontsize=9.5)
        ax.margins(y=0.25)
    fig.suptitle("More context helps up to k = 10 (dev, best retrieval)", x=0.02, ha="left",
                 fontweight="bold", fontsize=10.5)  # fmt: skip
    fig.tight_layout()
    return _save(fig, "rag_k_sweep")


def fig_rag_test():
    d = pd.read_csv(RES / "rag_test.csv").set_index("config")
    metrics = [("numeric_em", "numeric answer\ncorrect"), ("citation_precision", "citation\nprecision"),
               ("citation_recall", "citation\nrecall"), ("abstain_f1", "abstention F1")]  # fmt: skip
    fig, ax = plt.subplots(figsize=(6.2, 2.6))
    x = np.arange(len(metrics))
    for off, cfg, color, label in [(-0.2, "rag_baseline_k5", GREY, "baseline retrieval, k = 5"),
                                   (0.2, "rag_best_k10", BLUE, "final system, k = 10")]:  # fmt: skip
        vals = [d.loc[cfg, m] for m, _ in metrics]
        ax.bar(x + off, vals, width=0.38, color=color, label=label)
        for xx, v in zip(x + off, vals, strict=True):
            ax.text(xx, v + 0.02, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x, [m[1] for m in metrics])
    ax.set_ylim(0, 1.1)
    _hgrid(ax)
    ax.legend(loc="upper left", ncol=2)
    ax.set_title("Answers on the held-out test set (50 questions)")
    return _save(fig, "rag_test")


def fig_judge():
    """Agreement of the LLM judge with 50 human labels, before and after the rubric fix (counts from
    the validation runs, docs/summaries/phase-4.md)."""
    mats = {"original rubric (κ = 0.09)": [[1, 3], [6, 40]],
            "fixed rubric (κ = 1.00, in-sample)": [[4, 0], [0, 46]]}  # fmt: skip
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.6))
    for ax, (title, m) in zip(axes, mats.items(), strict=True):
        m = np.array(m)
        colors = np.array([[GOOD, BAD], [BAD, GOOD]])
        for i in range(2):
            for j in range(2):
                ax.add_patch(plt.Rectangle((j, 1 - i), 1, 1, color=colors[i, j],
                                           alpha=0.15 + 0.6 * (m[i, j] > 0)))  # fmt: skip
                ax.text(j + 0.5, 1.5 - i, str(m[i, j]), ha="center", va="center", fontsize=13,
                        fontweight="bold", color=INK)  # fmt: skip
        ax.set_xlim(0, 2)
        ax.set_ylim(0, 2)
        ax.set_xticks([0.5, 1.5], ["judge:\nunfaithful", "judge:\nfaithful"])
        ax.set_yticks([1.5, 0.5], ["human:\nunfaithful", "human:\nfaithful"])
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(title, fontsize=9.5)
    fig.suptitle("Validating the LLM judge against 50 human labels", x=0.02, ha="left",
                 fontweight="bold", fontsize=10.5)  # fmt: skip
    fig.tight_layout()
    return _save(fig, "judge_validation")


# --- figures and SQL ----------------------------------------------------------------------------
def fig_extraction():
    e = pd.read_csv(RES / "extraction.csv")
    e = e[e["metric"] != "ALL"].sort_values("accuracy")
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    colors = [BLUE if a == 1 else WARN for a in e["accuracy"]]
    ax.barh(e["metric"].str.replace("_", " "), e["accuracy"], color=colors, height=0.6)
    for i, (a, c, g) in enumerate(zip(e["accuracy"], e["correct"], e["n_gold"], strict=True)):
        ax.text(a + 0.01, i, f"{int(c)}/{int(g)}", va="center", fontsize=8)
    ax.set_xlim(0, 1.12)
    ax.set_xlabel("share of gold values extracted correctly (±0.5%)")
    ax.set_title("Key-figure extraction: 128 / 133 correct, no wrong values stored")
    return _save(fig, "extraction")


def fig_sql():
    s = pd.read_csv(RES / "figures_sql.csv").set_index("setting")
    rows = [
        ("gold", "generated SQL on gold figures\n(text-to-SQL errors only)", BLUE),
        ("oracle", "reference SQL on extracted figures\n(extraction errors only)", GREY),
        ("extracted", "generated SQL on extracted figures\n(end to end)", BLUE_LIGHT),
    ]
    fig, ax = plt.subplots(figsize=(6.2, 2.1))
    y = np.arange(len(rows))[::-1]
    for yy, (k, _label, c) in zip(y, rows, strict=True):
        v = s.loc[k, "execution_accuracy"]
        ax.barh(yy, v, color=c, height=0.6)
        ax.text(v + 0.01, yy, f"{v:.3f}", va="center", fontsize=8.5)
    ax.set_yticks(y, [r[1] for r in rows], fontsize=8.5)
    ax.set_xlim(0, 1.1)
    ax.set_xlabel("execution accuracy on 40 questions (result sets compared)")
    ax.set_title("Text-to-SQL: where the errors come from")
    return _save(fig, "sql")


# --- agent ---------------------------------------------------------------------------------------
def fig_agent():
    k = pd.read_csv(RES / "agent_by_kind.csv")
    order = ["documents", "figures", "documents_and_figures", "client", "out_of_scope"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6), gridspec_kw={"width_ratios": [1.4, 1]})
    x = np.arange(len(order))
    for off, mode, c in [(-0.2, "single", GREY), (0.2, "routed", BLUE)]:
        d = k[k["mode"] == mode].set_index("kind")
        axes[0].bar(
            x + off,
            [d.loc[o, "success"] for o in order],
            width=0.38,
            color=c,
            label={"single": "one agent, 5 tools", "routed": "router + sub-agents"}[mode],
        )
        axes[1].bar(x + off, [1000 * d.loc[o, "cost_per_task"] for o in order], width=0.38,
                    color=c)  # fmt: skip
    for ax in axes:
        ax.set_xticks(x, ["docs", "figures", "mixed", "client", "out of\nscope"], fontsize=8.5)
        _hgrid(ax)
    axes[0].set_ylim(0, 1.15)
    axes[0].set_title("task success", fontsize=9.5)
    axes[1].set_title("cost per task (US$ / 1000)", fontsize=9.5)
    fig.suptitle("Agent: same quality, 30% cheaper with routing (60 tasks)", x=0.02, ha="left",
                 fontweight="bold", fontsize=10.5)  # fmt: skip
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper left", ncol=2, fontsize=8,
               bbox_to_anchor=(0.02, 0.93))  # fmt: skip
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    return _save(fig, "agent")


# --- security --------------------------------------------------------------------------------------
def fig_security():
    s = pd.read_csv(RES / "security.csv")
    s["label"] = s["mode"] + " · " + s["defence"]
    order = [f"{m} · {d}" for m in ("single", "routed") for d in ("none", "prompt", "policy")]
    s = s.set_index("label").loc[order]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.7), sharey=True)
    y = np.arange(len(order))[::-1]
    colors = [BLUE if "policy" in o else GREY for o in order]
    axes[0].barh(y, 100 * s["ASR"], color=colors, height=0.6)
    axes[1].barh(y, 100 * s["benign_success"], color=colors, height=0.6)
    for yy, a, b in zip(y, s["ASR"], s["benign_success"], strict=True):
        axes[0].text(100 * a + 0.2, yy, f"{100 * a:.1f}%", va="center", fontsize=8)
        axes[1].text(100 * b + 1, yy, f"{100 * b:.0f}%", va="center", fontsize=8)
    axes[0].set_yticks(y, order)
    axes[0].set_xlim(0, 8)
    axes[1].set_xlim(0, 105)
    axes[0].set_title("attacks that succeeded (55)", fontsize=9.5)
    axes[1].set_title("legitimate tasks completed (75)", fontsize=9.5)
    fig.suptitle("Security: the policy engine guarantees 0 at a 5-point utility cost", x=0.02,
                 ha="left", fontweight="bold", fontsize=10.5)  # fmt: skip
    fig.tight_layout()
    return _save(fig, "security")


# --- regression -----------------------------------------------------------------------------------
def fig_regression_demo():
    rows = [("retrieval recall@5", 0.867, 0.789, 0.82, True),
            ("retrieval MRR@10", 0.722, 0.677, 0.68, True),
            ("RAG numeric correct", 0.750, 0.691, 0.70, True),
            ("RAG false refusals", 0.144, 0.211, 0.20, False)]  # fmt: skip
    fig, ax = plt.subplots(figsize=(6.2, 2.3))
    y = np.arange(len(rows))[::-1]
    for yy, (_label, good, bad, thr, _higher) in zip(y, rows, strict=True):
        ax.plot([good, bad], [yy, yy], color=GREY_LIGHT, lw=2)
        ax.scatter([good], [yy], color=BLUE, s=36, zorder=3, label="main" if yy == y[0] else None)
        ax.scatter([bad], [yy], color=BAD, s=36, zorder=3,
                   label="filters switched off" if yy == y[0] else None)  # fmt: skip
        ax.plot([thr, thr], [yy - 0.3, yy + 0.3], color=INK, lw=1.5,
                label="threshold" if yy == y[0] else None)  # fmt: skip
    ax.set_yticks(y, [r[0] for r in rows])
    ax.set_xlim(0, 1)
    ax.legend(loc="upper left", ncol=3, fontsize=8)
    ax.set_ylim(-0.6, len(rows) - 0.1)
    ax.set_title("A one-line breaking change fails the regression tier")
    return _save(fig, "regression_demo")


# --- self-hosted (Phase 9) ---------------------------------------------------------------------------
def phase9_table() -> pd.DataFrame | None:
    """Model comparison, built from whatever Phase 9 results exist (None if none yet)."""
    rag = (
        pd.read_csv(RES / "rag_dev.csv").set_index("config")
        if (RES / "rag_dev.csv").exists()
        else None
    )
    rows = []
    for key, label, rag_cfg, agent in [
        ("deepseek_flash", "DeepSeek flash (API)", "rag_best_k5", "agent_items.csv"),
        ("local_qwen4b_q4", "Qwen3-4B 4-bit (local)", "rag_local_qwen4b_q4_k5", "agent_items_local_qwen4b_q4.csv"),
        ("local_qwen4b_q8", "Qwen3-4B 8-bit (local)", "rag_local_qwen4b_q8_k5", "agent_items_local_qwen4b_q8.csv"),
        ("local_qwen8b_q4", "Qwen3-8B 4-bit (local)", "rag_local_qwen8b_q4_k5", "agent_items_local_qwen8b_q4.csv"),
    ]:  # fmt: skip
        r = {"model": label}
        if rag is not None and rag_cfg in rag.index:
            r["RAG numeric correct"] = rag.loc[rag_cfg, "numeric_em"]
            r["citation precision"] = rag.loc[rag_cfg, "citation_precision"]
        if (RES / agent).exists():
            a = pd.read_csv(RES / agent)
            a = a[a["mode"] == "routed"] if "mode" in a else a
            r["agent success (routed)"] = a["success"].mean()
            r["routing accuracy"] = a["route_ok"].mean()
            r["valid tool calls"] = a["n_valid_calls"].sum() / max(1, a["n_calls"].sum())
        sec = RES / "phase9" / f"{key}.csv"
        if key == "deepseek_flash" and (RES / "security_items.csv").exists():
            s = pd.read_csv(RES / "security_items.csv")
            s = s[(s["suite"] == "attack") & (s["defence"] == "none")]
            r["attack success, no defence"] = s["success"].mean()
        elif sec.exists():
            s = pd.read_csv(sec)
            s = s[(s["suite"] == "attack") & (s["defence"] == "none")]
            r["attack success, no defence"] = s["success"].mean()
        rows.append(r)
    df = pd.DataFrame(rows).set_index("model")
    return None if df.shape[1] == 0 else df


def fig_models():
    """Self-hosted vs API: one small multiple per metric, the API model as the grey reference."""
    t = phase9_table()
    if t is None:
        return None
    metrics = [c for c in ["RAG numeric correct", "citation precision", "agent success (routed)",
                           "routing accuracy", "valid tool calls", "attack success, no defence"]
               if c in t.columns and t[c].notna().sum() >= 2]  # fmt: skip
    if not metrics:
        return None
    fig, axes = plt.subplots(1, len(metrics), figsize=(2.0 * len(metrics) + 0.6, 2.6), sharey=True)
    axes = np.atleast_1d(axes)
    y = np.arange(len(t))[::-1]
    colors = [GREY if "API" in m else BLUE for m in t.index]
    for ax, m in zip(axes, metrics, strict=True):
        vals = t[m].to_numpy(dtype=float)
        ax.barh(y, np.nan_to_num(vals), color=colors, height=0.6)
        for yy, v in zip(y, vals, strict=True):
            ax.text(0.02 if np.isnan(v) else v + 0.02, yy, "n/a" if np.isnan(v) else f"{v:.2f}",
                    va="center", fontsize=8, color=MUTED if np.isnan(v) else INK)  # fmt: skip
        ax.set_xlim(0, 1.25)
        ax.set_xticks([0, 0.5, 1])
        ax.set_title(m, fontsize=8.5)
    axes[0].set_yticks(y, t.index, fontsize=8.5)
    fig.suptitle("Self-hosted models on a 4 GB GPU vs the API model", x=0.02, ha="left",
                 fontweight="bold", fontsize=10.5)  # fmt: skip
    fig.tight_layout()
    return _save(fig, "models")
