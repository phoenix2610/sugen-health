# ICD-11 coder: Sugen take-home

`docker compose run coder /in/notes.jsonl /out/predictions.jsonl` writes up to 3 ICD-11 MMS 2026-01 codes per note (`./in` and `./out` are mounted).
`problem/` holds the pack exactly as received. `DECISIONS.md` logs every choice with its commit. `results/` holds the raw predictions and scorer output behind every number below.

> **Status.** We had no funded OpenAI or Anthropic key: the OpenAI key we hold authenticates but returns `429 insufficient_quota`. The keyed path is fully built but was **measured with Gemini standing in** (`tools/project.py` runs the identical pipeline). Those numbers are a projection, not a measurement on GPT or Claude.

## How it works
1. **No-key ranker** (`coder/kb.py`, `coder/nokey.py`). Every WHO term (title, full name, index terms, inclusions) in en, es, fr, pt and ar (ar about 80%) is scored by the rarity-weighted share of its words found in the note. The stated diagnosis (`A:`, `Imp:`, `Dx`, the doctor's turns with a diagnostic cue) gets full weight, the rest of the note 0.35. Only **leaf codes** are output (all 61 dev gold codes are leaves): `.Z` inherits its parent's terms, `.Y` is penalised, obstetric and perinatal chapters need pregnancy or newborn wording. 60 notes take under a second.
2. **Keyed path** (`coder/llm.py`), two calls per note. (1) Extract the main diagnosis **in English** with its ICD qualifiers. (2) Rerun retrieval on that English text, then choose from about 40 candidates plus their families (parent, siblings, `.Z`). Codes are validated and forced to leaves. Claude Haiku 5.5 if `ANTHROPIC_API_KEY` is set, otherwise gpt-5-mini.
3. **Safety.** A complete no-key file is written before any API call, then rewritten atomically as answers arrive. A $5 budget guard, a 45-minute deadline guard, a 10 s connect timeout and a circuit breaker for a bad key or dead proxy (measured: 3 s and 96 s in Docker).

## Scores (official `score.py`)
| | dev (60) | synthetic core, A (150) | synthetic general, B (250) | synthetic, hidden weighting |
|---|---|---|---|---|
| no key | **52.9 / 75** (top-1 .667, top-3 .783) | 47.2 / 75 | 8.8 / 25 | 55.9 / 100 (verified-only 63.3) |
| keyed, Gemini stand-in | **67.5 / 75** (top-1 .867, top-3 .967) | not measured | not measured | — |

The keyed synthetic run (Gemma, 160 notes) was stopped about a third of the way through when the free-tier quota became the bottleneck, so it gives no number. Projected cost for 600 notes, from measured tokens (2.4k input; 0.2–2.1k output depending on thinking): **Haiku 5.5 $0.2–0.8, gpt-5-mini about $2.9** (cap $6). gpt-5.4-mini would reach $6.8, so it is not the default.

**Hidden-score estimate.** With a working key: core about 60–68/75 (dev 67.5, discounted because the stand-in model differs), generalisation about 12–17/25 (no-key B is 8.8; the English extraction should help, but this is unmeasured). **About 72–85 in total, point estimate 78.** Without a key: about 55–60.

## Data added
- **WHO ICD-11 API** (`id.who.int`, release 2026-01, OAuth): for all 13,041 non-residual categories, index terms, inclusions, full names and definitions in English, plus titles, index terms and inclusions in es, fr, pt and ar. Crawled by `tools/crawl_who.py`, compacted to `coder/data/kb.json.gz` (3.2 MB, 254k terms).
- **Clinical abbreviation list** (`coder/text.py`), written by hand as general shorthand, not taken from the dev notes.
- **Google Gemini** (the author's own free-tier key, stored outside the repo): **development only**, for synthetic notes and the projection. The submitted system never calls it.

## Evaluation beyond the 60 dev notes
`eval/` holds 400 synthetic notes from `tools/gen_synth.py`. **Core** (150): East-African outpatient, the 3 dev styles, chapters weighted like dev. **General** (250): all 26 chapters, 14 settings, 151 notes in 15 non-English languages or code-mixes (fr, es, pt, sw, vi, id, de, Hinglish, ar, zh, ru, am, tr, it), 7 styles. The writer sees the chosen code's siblings so the note carries, or omits for `.Z`, the deciding detail. A different model re-codes each note blind: 267 agree, 70 disagree, 63 unchecked (quota). Scores are reported on all notes and on verified ones. Known bias: LLM-written notes name the diagnosis more cleanly than real ones. Setting changes were compared on these frozen sets (`tools/ab.py`) rather than on dev; one dev-favoured choice (coverage power 2.0) was rejected on that basis.

## Where the AI tooling was wrong
The AI assistant wrote `DECISIONS.md` timestamps for D4–D9 from its own estimate rather than the clock, up to 2 h 24 m ahead of the real commits. A log that is graded against git history would have contradicted that history. Checking the entries against `git log` caught it. The entries were corrected with a visible note (commit `8d05b57`), and every later entry takes its time from `date` and names its commit. (A second catch: the assistant's first OpenAI default, gpt-5.4-mini, would have overrun the $6 cap. That surfaced when measured tokens were multiplied by the published prices.)

Hours spent: about 8 (7:30–15:30 IST, 5 Nov 2026).
