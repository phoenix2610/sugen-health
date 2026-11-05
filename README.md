# ICD-11 coder: Sugen take-home

`docker compose run coder /in/notes.jsonl /out/predictions.jsonl` reads a JSONL file of notes and writes up to 3 ICD-11 MMS 2026-01 codes per note.
`problem/` holds the pack exactly as received. `DECISIONS.md` is the running log of choices.

## How it works
1. **No-key ranker** (`coder/nokey.py`, `coder/kb.py`). Every WHO term (title, full name, index terms, inclusions; English plus es, fr, pt, ar, ru, zh, de, tr) is scored by the rarity-weighted share of its words found in the note. The clinician's stated diagnosis (`A:`, `Imp:`, `Dx`, the doctor's turns with a diagnostic cue) gets full weight, the rest of the note 0.35. Scores roll up to **leaf codes only**: a `.Z` inherits its parent's terms, `.Y` is penalised, and obstetric or perinatal chapters need pregnancy or newborn wording in the note. All 60 notes run in under a second.
2. **Keyed path** (`coder/llm.py`). Call 1 extracts the main diagnosis **in English** with the ICD qualifiers (site, organism, acuity, complication, pregnancy). Retrieval reruns on that English text. Call 2 picks from about 40 candidates plus their families (parent, siblings, `.Z`). Codes are validated and forced to leaves. Uses Claude Haiku 5.5 if `ANTHROPIC_API_KEY` is set, else gpt-5-mini.
3. **Safety.** A complete no-key file is written before any API call, then rewritten atomically as answers arrive. There is a $5 budget guard, a 45-minute deadline guard, a 10 s connect timeout, and a circuit breaker for a bad key or dead proxy (measured: 3 s and 96 s).

## Scores (official `score.py`)
| | dev (60) | synthetic core (A) | synthetic general (B) |
|---|---|---|---|
| no key | **TBD** | TBD | TBD |
| keyed, projected* | **TBD** | TBD | TBD |

*We had no funded OpenAI or Anthropic key (the OpenAI key we have returns `insufficient_quota`). The keyed numbers run the identical pipeline with Gemini standing in, so they are a projection, probably a lower bound. **Hidden-score estimate:** TBD.
Projected cost for 600 notes at the measured tokens: Haiku 5.5 about $0.77, gpt-5-mini about $2.90 (cap $6).

## Data added
- **WHO ICD-11 API** (`id.who.int`, release 2026-01, OAuth): for all 13,041 non-residual categories, index terms, inclusions, full names and definitions in English, plus titles, index terms and inclusions in 8 more languages. Crawled by `tools/crawl_who.py`, compacted to `coder/data/kb.json.gz` (2.6 MB).
- **Clinical abbreviation list** (`coder/text.py`): general shorthand, written by hand, not derived from the dev notes.
- **Google Gemini** (the author's own free-tier key, stored outside the repo): **development only**, for synthetic notes and the keyed-path projection. The submitted system never calls it.

## Evaluation beyond the 60 dev notes
`tools/gen_synth.py` produced 400 synthetic notes. **Core** (150): East-African outpatient, the 3 dev styles, chapters weighted like dev. **General** (250): every chapter, 14 settings, about half non-English or code-mixed (fr, es, pt, sw, Hinglish, ar, de, zh, ru, am, tr, it, id, vi), 7 styles. The writer picks the code and sees its siblings, so the note carries (or omits, for `.Z`) the deciding detail. A different model then re-codes each note blind, and agreement is reported as `verified`. Known bias: LLM-written notes state the diagnosis more cleanly than real ones, so synthetic scores read high. The keyed projection uses Gemma, a different model family from the note writer.

## Where the AI tooling was wrong
TBD (author to write).

Hours spent: TBD
