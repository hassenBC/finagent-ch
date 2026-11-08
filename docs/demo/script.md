# Demo video: script and captions

77 s, 1920x1080, 30 fps, silent (captions only). Every scene is a real run: terminal scenes are recorded with VHS
(`tapes/*.tape`), web scenes with Playwright (`ui_scenes.py`), the cards and captions are added by `edit.py` (ffmpeg).
Re-record everything with `make demo` (or `./docs/demo/build.sh`).

| # | Scene | Source | Time | On-screen text |
|---|---|---|---|---|
| 1 | Title card | edit.py | 3.6 s | **finagent-ch** / Ask Swiss bank reports. Get cited, safe answers. |
| 2 | The problem | edit.py | 7.2 s | Bank reports run to hundreds of pages. / The numbers hide in tables, in French and English. / AI answers come with no proof, and risky tools. / finagent-ch: cited answers, and guardrails you can test. |
| 3 | Setup | tapes/setup.tape | ~8 s | Start the database, and the assistant is ready. (`docker compose up -d --wait db`, `finagent --help`) |
| 4 | Ask in the terminal | tapes/ask.tape | ~9.5 s | Ask a money question. It looks up the numbers and does the maths. (`finagent ask "...Julius Baer cost/income..."`: SQL, then calculator, cited answer) |
| 5 | Cited pages | ui_scenes.py `cite` | ~10 s | Ask in French. Every figure links to the exact report page. (preset "French question", click a citation, the PDF page opens) |
| 6 | Live trace | ui_scenes.py `trace` | ~8 s | Watch every step: what it searched, and what it can trust. (preset "Document search": FTS, vector, fusion spans, "untrusted" label) |
| 7 | Human approval | ui_scenes.py `approval` | ~13 s | Risky action? It pauses and asks a human first. (preset "Document -> e-mail: R3", click Allow, mock outbox) |
| 8 | Attack blocked | ui_scenes.py `attack` | ~12 s | Tricked into leaking data? The safety rules block it. (same request with defence "none", then "policy": denied by R2) |
| 9 | Results card | edit.py | 6.2 s | Measured, not guessed. Retrieval recall@5 0.44 -> 0.80; answer numeric match 0.25 -> 0.78; citation precision 0.48 -> 0.85, baseline -> final system (held-out test set, from the README) |
| 10 | End card | edit.py | 4.6 s | github.com/hassenBC/finagent-ch / git clone, then make setup / Star the repo. Read the report. Try the demo app. |

Notes
- Scenes use real data (the 12 public bank reports) and the synthetic demo e-mail addresses from the app's presets.
  LLM calls are cached, so recorded runs are quick and repeatable; a warm-up pass runs before recording.
- The mock outbox is emptied before recording (`clear_outbox.py`). Nothing is ever sent.
- No music: the video is silent, so there is no licence to track.
