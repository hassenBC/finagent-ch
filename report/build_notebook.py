"""Build report/finagent_report.ipynb (run: uv run --with nbformat --with nbclient --with ipykernel
python report/build_notebook.py). Text lives here; figures come from report/figures.py; numbers are
read from results/*.csv when the notebook runs, so re-running it after new results updates it."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).parent
cells = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(text.strip()))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(text.strip()))


def plain(text: str) -> None:
    md("> **In plain words.** " + text.strip())


def expert(text: str) -> None:
    md("<details><summary><b>For experts</b></summary>\n\n" + text.strip() + "\n\n</details>")


md("""
# finagent-ch: what we built, how we measured it, and what we learned

A question-answering assistant over the **annual reports of six Swiss banks** (Julius Baer, Vontobel,
EFG International, Swissquote, BCV, BCGE; fiscal years 2024 and 2025; English and French; table-heavy PDFs),
grown step by step into a **tool-using agent with a security layer**, and **measured at every step**.

**How to read this report.** Every section has the same four parts:

* **In plain words**: two or three sentences, no jargon. If you only read these, you get the story.
* **Method**: what we did and why, including the optimisations we tried in order.
* **Result**: a figure and the numbers behind it, read live from `results/*.csv`.
* **For experts** (click to open): statistics, caveats, and the mistakes we made and corrected.

A glossary of every metric is right below. All numbers are reproducible with the commands in the README.
""")

md("""
## Glossary

| Term | Meaning |
|---|---|
| **Retrieval** | Finding the right passages (chunks of the PDFs) for a question, before any answer is written. |
| **recall@5** | Share of questions whose evidence page appears in the first 5 passages found. 1.0 = always found. |
| **MRR@10** | How high the first correct passage is ranked (1 = first place, 0.5 = second place, …), averaged. |
| **RAG** | Retrieval-augmented generation: a language model writes the answer from the retrieved passages and cites them. |
| **Numeric match** | The answer contains the correct number (within rounding). |
| **Citation precision / recall** | Share of cited pages that are right / share of right pages that were cited. |
| **Abstention** | The system says "I cannot answer"; correct for questions the reports do not answer. |
| **Faithfulness** | Every claim in the answer is supported by the pages it cites (checked by an LLM judge we validated). |
| **Cohen's κ (kappa)** | Agreement between two raters beyond chance: 0 = chance level, 1 = perfect, ≥ 0.6 usually "substantial". |
| **Agent / tool** | A model that decides which tools to call (search, SQL, calculator, client notes, e-mail) to finish a task. |
| **MCP** | Model Context Protocol: the standard way we expose the tools to the agent. |
| **Policy engine** | Deterministic code (not a model) that allows, denies or escalates each tool call. |
| **Prompt injection** | Instructions hidden in a document or note that try to make the agent do something else. |
| **ASR** | Attack success rate: share of attacks that actually achieved their goal. |
| **95% CI** | Bootstrap confidence interval: the range the true value likely lies in, given only ~100 questions. |
""")

code("""
import sys, json
from pathlib import Path
import pandas as pd
ROOT = Path.cwd().parent if Path.cwd().name == "report" else Path.cwd()
sys.path.insert(0, str(ROOT / "report"))
import figures as F
RES = ROOT / "results"
pd.set_option("display.precision", 3)
""")

# ------------------------------------------------------------------------------------------------
md("## 1. The evaluation set came first")
plain("""Before building anything we wrote down **150 questions with known answers and the exact page that
contains the evidence**. 100 are used to tune the system (dev); 50 are locked away and run only once per
final configuration (test), so the final numbers are not flattered by tuning.""")
md("""**Method.** Pages were sampled evenly across the 12 reports; an LLM proposed one question per page in a
requested style (table lookup, text lookup, computation, comparison across banks, French, cross-lingual,
unanswerable), and code checked each proposal against the page (the evidence words and numbers must be on
it). Gold labels are **pages**, not chunks, so the same questions can judge any way of cutting the PDFs.""")
code("F.fig_dataset(); F.dataset_mix()")
expert("""Question generation was model-assisted and machine-checked, not hand-written; a blind AI-assisted spot
check of 20 items re-derived all 20 answers from the PDFs (a sample, not a human audit). Numeric tolerances are
half a unit of the answer's last digit with a 0.1 % floor. The test file's sha256 is in the README; it was run
once per final configuration and never used for a decision.""")

# ------------------------------------------------------------------------------------------------
md("## 2. Retrieval: finding the right page")
plain("""Most wrong answers start with the wrong passage. We tried many ways of cutting the reports into
passages and of searching them, kept what measurably helped, and ended at **80 % of test questions with the
right page in the top 5, up from 44 %** for a simple baseline.""")
md("""**Method: the optimisation path.** One change at a time, each compared on the same 90 answerable dev
questions with paired bootstrap confidence intervals ("A beats B" only if the interval of the per-question
difference excludes 0):

1. **Chunking**: fixed 512-token pieces → document-structure pieces → *table-aware* pieces that keep each table
   whole and prepend a one-line header `Bank | Year | Section`.
2. **Embeddings**: multilingual-e5-small → e5-large → **bge-m3**.
3. **Metadata filters**: restrict the search to the bank and year the question names.
4. **Hybrid search**: combine vector search with Postgres full-text search by reciprocal rank fusion (RRF).
5. **Reranking and query expansion** (a cross-encoder, and three LLM rephrasings).
6. **Error analysis → question translation** when the question's language differs from the report's.""")
code("F.fig_ladder();")
code("""dev = pd.read_csv(RES / "retrieval.csv").set_index("config")
dev.loc[[c for c, _ in F.LADDER], ["recall@5", "recall@5_lo", "recall@5_hi", "mrr@10", "latency_p50_ms"]]""")
md("""**Two findings that changed our minds.** First, the table-aware chunker looked like the winner, but an
ablation showed the gain came almost entirely from the **one-line context header**: adding the header to plain
structure chunks gave the same result, and removing it from table-aware chunks erased the gain.""")
code("F.fig_header_ablation();")
md("""Second, full-text search first looked useless (recall@5 0.26) and we concluded that "hybrid search does
not help". The cause was Postgres' default **cover-density ranking** (`ts_rank_cd`), which ranks OR-queries
almost arbitrarily. With `ts_rank` and length normalisation, full-text search alone reached 0.71, as good as
vector search, and hybrid search became useful. We re-ran every affected experiment.""")
code("F.fig_fts_rank();")
md("""**Error analysis.** We read every miss of the best dev configuration. The top cause was **cross-lingual**:
English questions about the French-language BCGE report. Translating the question to the report's language
fixed most of them (cross-lingual recall@5 0.50 → 0.80).""")
code("F.fig_errors();")
code("F.fig_by_type();")
expert("""Reranking (+1 s) and 3-query expansion (+2.6 s) were not significant alone and added nothing on top of
filters, so they were dropped: a "negative" result that saved latency and cost. Filters: +0.09 recall@5
[+0.03, +0.14] at no latency cost. bge-m3 vs e5-small: MRR +0.11 [+0.03, +0.20]; e5-large = e5-small.
On test, the two final configurations are indistinguishable (recall@5 +0.00 [−0.09, +0.09]); the dev advantage
of the hybrid one (0.87) was partly selection on dev. Approximate (HNSW) vector search cost up to 0.04
recall@5 for unfiltered queries because one index serves five chunkers.""")

# ------------------------------------------------------------------------------------------------
md("## 3. Answers with citations")
plain("""The language model reads the retrieved passages and writes a short answer that **cites the page of
every figure**, or refuses when the passages do not contain the answer. Better retrieval carried straight
through: on the test set **78 % of numeric answers are correct** (baseline 25 %) and 85 % of citations point
to the right page.""")
md("""**Method.** Generator `deepseek-flash` at temperature 0 with structured output (answer, citations,
abstain flag). We varied **k**, the number of passages given to the model.""")
code("F.fig_k_sweep();")
code("F.fig_rag_test();")
code("""pd.read_csv(RES / "rag_test.csv").set_index("config")[["numeric_em", "numeric_em_lo", "numeric_em_hi",
    "citation_precision", "citation_recall", "abstain_f1", "false_abstention_rate", "cost_per_query_usd"]]""")
md("""**Is the answer faithful to its sources?** An LLM judge splits each answer into claims and checks each
against the cited pages only. A judge is only useful if it agrees with people, so we compared it with **50
human labels**. The first rubric agreed barely above chance (κ = 0.09): it marked correct arithmetic ("the
difference is CHF 8.5 bn") as unsupported and accepted numbers whose unit appeared only in the question.
Stating both rules explicitly gave full agreement.""")
code("F.fig_judge();")
expert("""κ = 1.00 is **in-sample** (the rubric was revised after seeing these 50 disagreements), and with
only 4 unfaithful answers one label moves κ by ~0.3; treat it as "no known disagreement", not a held-out
accuracy. Faithful answers on test: final system 40/41 = 0.98 [0.87, 1.00], baseline 13/17 = 0.76 [0.53,
0.90]; intervals overlap and the baseline is judged only on the questions it does not refuse, so its main
failure is refusing, not inventing. Judge: `deepseek-v4-pro` (≈ $0.009 per answer, a reasoning model that
silently returns empty JSON when it hits its token budget; this is handled by a retry and a recorded judge error).""")

# ------------------------------------------------------------------------------------------------
md("## 4. Key figures and safe SQL")
plain("""Questions like "rank the banks by CET1 ratio" are easier with a table of numbers than with text. We
had an LLM **extract 12 key figures** per report into a database (96 % correct, never a wrong value stored)
and let the agent query it with **SQL that cannot change or leak anything**.""")
md("""**Method.** For each (bank, year, metric) the extractor gets the top table passages and must return the
value as printed, its unit, the period, the page and a verbatim quote; code rejects it unless the quote is in
the passage, the value is in the quote, the period is the requested year (not the prior-year column) and the
unit fits. Gold: 133 values collected by hand (AI-assisted, then validated). SQL safety: one SELECT only,
allow-listed tables and functions, regenerated from the parse tree, run as a read-only role with a 2 s timeout;
40 hostile inputs are rejected in CI.""")
code("F.fig_extraction();")
code("F.fig_sql();")
expert("""Extraction errors were all "not found" (retrieval did not surface the table); no prior-year, unit,
sign or wrong-metric errors. Caveat: gold and extractor are both LLM-assisted, so a shared mistake would not
show. The two text-to-SQL failures on gold are a correct answer in another shape and a correct value rounded
to one decimal; the metric was kept strict rather than loosened after seeing results.""")

# ------------------------------------------------------------------------------------------------
md("## 5. The agent and its router")
plain("""The agent chooses tools by itself. A small **router** first decides what kind of question it is and
gives the agent **only the tools it needs**: a document question never sees the client database or e-mail.
On 60 tasks this was as accurate as one agent with every tool, and **30 % cheaper**.""")
code("F.fig_agent();")
code("""pd.read_csv(RES / "agent.csv")[["mode", "success", "routing_acc", "arg_validity", "calls_per_task",
    "cost_per_task", "latency_p50_ms"]]""")
expert("""Tasks are checked automatically (numbers with tolerance, the first bank named, or a refusal): no LLM
judge. 91.7 % vs 90.0 % success is one task out of 60: not a difference. Repeating 20 tasks three times with
fresh API calls gave identical outcomes. Main failure: the agent searching until its step limit on document
questions.""")

# ------------------------------------------------------------------------------------------------
md("## 6. Security: a policy engine and 55 attacks")
plain("""We tried to trick the agent into **e-mailing confidential (synthetic) client data outside the bank**, with instructions hidden in documents, in client notes, in other languages, in base64, and by simply
asking. A deterministic **policy engine** checks every tool call: no data leaves after confidential data was
read, e-mail only to the bank's own domain, a human must approve actions after reading untrusted documents.
With it, **0 of 55 attacks succeeded**; without it, 2 did.""")
code("F.fig_security();")
code("""pd.read_csv(RES / "security_by_category.csv").pivot_table(index="category",
    columns=["mode", "defence"], values="ASR")""")
expert("""The model itself (`deepseek-flash`) followed **none of the 48 planted instructions**, even with no
defence, including 15 "in-task" redirections added after the first 40 proved too easy. Both successes were
direct requests involving public data (a 5-recipient mailing, figures to an outside domain). So on this model
the policy engine is a guarantee, not the thing that stopped the attacks; its measured price is 5 points of
unattended task success (every legitimate "read a document, then e-mail" task waits for a human). 0/55
bounds the true attack success only at ≤ ~6.5 % (95 %, rule of three). Section 8 asks whether small local
models are easier to trick.""")

# ------------------------------------------------------------------------------------------------
md("## 7. Keeping it working: regression tests")
plain("""Every change is checked automatically. A fast tier runs on each push without any API key; a full
tier re-runs all evaluations against thresholds and lists **which questions** got worse. A deliberate one-line
mistake (switching off the bank/year filters) is caught immediately.""")
code("F.fig_regression_demo();")
expert("""Fast tier: lint, 264 unit tests (incl. SQL injection inputs and policy rules), the read-only role
against Postgres, and retrieval on 31 dev questions against a 4-report fixture that stores only FTS vectors,
embeddings and page numbers, not the report text. Averages hide regressions: moving to the final retrieval
configuration looked like +4 questions but was 7 fixes and 3 regressions. Re-runs are not bit-identical (2 of
100 RAG items changed with unchanged code, from approximate vector search), so thresholds carry a margin.""")

# ------------------------------------------------------------------------------------------------
md("## 8. Can it run on our own hardware?")
plain("""Banks often cannot send data to an outside API. We ran the same evaluations with small **open models
on a laptop GPU (4 GB)** and compared them with the API model on quality, tool use, security and speed.""")
code("""t = F.phase9_table()
t if t is not None else "Phase 9 results not available yet: re-run this notebook after the overnight run." """)
code("F.fig_models();")
md("""**Method.** Qwen3-4B (4-bit and 8-bit) and Qwen3-8B (4-bit) served by Ollama in Docker; identical
prompts and code; the judge kept fixed (API). Only the 4-bit 4B fits the 4 GB GPU entirely (37/37 layers,
~3 s per answer); the 8-bit 4B and the 8B spill onto the CPU (minutes per answer), so they ran on half-size
subsets. The 8B did not finish (over 11 minutes per answer, about nine hours for 50 RAG questions), so the
chart shows no 8B numbers.""")
plain("""**Result.** The small 4-bit model answers key-figure questions correctly 57 % of the time (API model: 69 %)
and completes 42 % of the agent tasks (API model: 92 %); it often refuses or answers without searching.
On the injection suite 4 of 55 attacks succeed without a defence in single mode (API model: 2 of 55), but the
small model often did not use its tools at all, so this says little about robustness; with the permission layer,
none succeed. The 8-bit model, tested without a defence only, followed one planted instruction (the API model
followed none).""")
expert("""A first finding before any score: partial offload, not model size, is the bottleneck on a 4 GB card
(52 s vs 3.3 s for the same answer once the 4B fits entirely with an 8k context and one request slot; two
parallel slots made it worse by doubling the KV cache). The local 4B produced invalid tool arguments and
refused document questions without searching more often than the API model; prompts were kept identical,
not tuned for it.""")

# ------------------------------------------------------------------------------------------------
md("## 9. What it cost, what we would do next")
plain("""All language-model calls together cost **under 10 US dollars** (API, peak list prices), thanks to a
cache that makes re-runs free and a cost cap on every run.""")
md("""**Limitations.** ~100 dev / 50 test questions give wide intervals; questions were model-proposed and
machine-checked; the gold figures and the judge validation are AI-assisted; the security suite is 55 attacks
on one API model; the policy's flow tracking is coarse (one confidential read taints the whole session).

**Next.** A held-out set of human labels for the judge; finer, per-value information-flow labels (as in
CaMeL); a larger injection suite with adaptive attacks; a local translation model for a fully on-premise
setup; streaming answers.""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3",
                                                              "display_name": "Python 3"}})  # fmt: skip
nbf.write(nb, HERE / "finagent_report.ipynb")
print(f"wrote {HERE / 'finagent_report.ipynb'} ({len(cells)} cells)")
