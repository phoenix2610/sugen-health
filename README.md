# ICD-11 coder: Sugen take-home

`docker compose run coder /in/notes.jsonl /out/predictions.jsonl` writes up to 3 ICD-11 MMS 2026-01 codes per note (`./in` and `./out` are mounted).
`problem/` holds the pack exactly as received. `DECISIONS.md` logs every choice with its commit. `results/` holds the raw output behind every number below.

> **No OpenAI or Anthropic key was used, so nothing here is a live measurement of GPT or Claude.** Each number carries a label:
> **measured**: the shipped image with no key, scored by the official `score.py` ·
> **mocked**: the shipped image and its real SDKs against a scripted local server; checks behaviour, not accuracy ·
> **live-unauth**: real `api.anthropic.com` / `api.openai.com` through a local CONNECT proxy, with an invalid key ·
> **stand-in**: the same pipeline with Gemini answering, through a dev-only harness; it measures Gemini, not Claude or GPT ·
> **estimate**: a forecast.

## How it works
1. **No-key ranker** (`coder/kb.py`, `coder/nokey.py`). Every WHO term (title, full name, index terms, inclusions) in en, es, fr, pt and ar (ar about 80%) is scored by the rarity-weighted share of its words found in the note. The stated diagnosis (`A:`, `Imp:`, `Dx`, the doctor's turns with a diagnostic cue) gets full weight, the rest of the note 0.35. Only **leaf codes** are output (all 61 dev gold codes are leaves): `.Z` inherits its parent's terms, `.Y` is penalised, and the obstetric and perinatal chapters need pregnancy or newborn wording.
2. **Keyed path** (`coder/llm.py`), two calls per note. The first extracts the main diagnosis **in English** with its ICD qualifiers. Retrieval then reruns on that text, and the second call chooses from about 40 candidates plus their families. Codes are validated and forced to leaves. The model is Claude Haiku 5.5 if `ANTHROPIC_API_KEY` is set, otherwise gpt-5-mini. Only those two APIs are called at runtime.
3. **Safety.** A complete no-key file is written before any API call, then rewritten atomically as answers arrive. A $5 budget guard reserves each call's worst case (input plus the `max_tokens` cap) before sending, so parallel calls cannot overshoot it. Also: a 45-minute deadline guard, a 10 s connect timeout, and a circuit breaker for a bad key or dead proxy.

## Results
| | label | result |
|---|---|---|
| dev, no key | measured | **52.9 / 75** (top-1 .667, top-3 .783) |
| 400 synthetic notes, no key | measured | 55.9 / 100 at hidden weighting (A 47.2/75, B 8.8/25; verified-only 63.3) |
| no-key latency | measured | 2.9 s for 60 notes, 5.2 s for 400 (plus about 2 s container start) |
| keyed integration, 20 cases | mocked, live-unauth | **20 / 20 pass** (`tools/mock_test.py`, `results/mock_tests.txt`) |
| dev, keyed pipeline | stand-in | 67.5 / 75 (top-1 .867, top-3 .967), 102 of 118 calls answered by `gemini-flash-lite-latest`, 1 note fell back |
| synthetic, keyed | none | not measured (the free-tier quota stopped the run at about a third) |

**What the mocks check.** The checks run on the 60 dev notes in the shipped image.
- *Requests:* the SDKs send `claude-haiku-5-5` with `output_config` (JSON schema, effort low then medium), and `gpt-5-mini` with `json_object`, `reasoning_effort` and `max_completion_tokens`.
- *Answers:* they are used, invalid codes are dropped and parent codes become leaves.
- *Fallback:* every note keeps its no-key answer on non-JSON output, refusal, 401, 429, 5xx after the SDK's retries, or a proxy that refuses CONNECT.
- *Breaker:* a bad key ends the run in 5 s, 429 in 9 s, and a refused proxy in 9 s.
- *Budget:* billed spend stays under $0.01 and $0.05 caps.
- *Deadline:* the deadline guard stops new notes in time.
- *Provider choice:* Anthropic is used when both keys are set.
- *Live-unauth:* both real endpoints were reached through `HTTPS_PROXY` and rejected the key, and the run fell back cleanly.

**The mocks caught three faults, all now fixed:**
1. In the OpenAI path, parallel rejections of `reasoning_effort` raced on a shared flag and lost 7 of 60 notes to the no-key answer.
2. An `output_config` rejection was retried on every call instead of being remembered.
3. The budget guard could be overshot by calls already in flight.

## Untested live behaviour
- Whether the live APIs accept `output_config` (Haiku 5.5) and `reasoning_effort` (gpt-5-mini) as sent. Both have a tested retry when the error names the parameter. A differently worded rejection would leave notes on their no-key answers.
- Answer quality of Haiku 5.5 and gpt-5-mini. 67.5 is a Gemini number.
- Haiku 5.5 thinks by default. A call that spends its `max_tokens` on thinking returns no text and keeps the no-key answer. How often that happens is unknown.
- Real token counts, cost, latency, rate limits at 8 parallel workers, and the graders' proxy itself.

## Estimates (not results)
- **Cost for 600 notes**, from stand-in tokens (2.4k in, 0.2k out per note; up to 2.1k out with thinking), with Haiku 5.5's tokenizer counted about 30% higher:
  - Haiku 5.5: about $0.3–1.0.
  - gpt-5-mini: about $0.6–2.9.
  - If every call used its full `max_tokens`: Haiku $1.8; gpt-5-mini $7.0. In that case the guard stops near $5 and the remaining notes keep their no-key answers.
- **Latency with a key:** 2 calls per note on 8 workers. At 3–10 s per call, 600 notes take about 8–25 minutes.
- **Hidden score with a working key:** about 72–85, point estimate 78.
  - Core: about 60–68/75. This is the stand-in's 67.5, discounted for the model difference.
  - Generalisation: about 12–17/25. No-key scores 8.8; the English extraction should help, but that is unmeasured.
- **Hidden score without a key:** about 55–60.

## Data added
- **WHO ICD-11 API** (`id.who.int`, release 2026-01, OAuth), crawled by `tools/crawl_who.py` and compacted to `coder/data/kb.json.gz` (3.2 MB, 254k terms). It covers all 13,041 non-residual categories:
  - English: index terms, inclusions, full names and definitions.
  - es, fr, pt and ar: titles, index terms and inclusions.
- **Clinical abbreviation list** (`coder/text.py`), written by hand as general shorthand, not taken from the dev notes.
- **Google Gemini** (the author's own free-tier key, stored outside the repo): **development only**, for the synthetic notes and the stand-in. The submitted system never calls it.

## Evaluation beyond the 60 dev notes
`eval/` holds 400 synthetic notes written by `tools/gen_synth.py`:
- **Core** (150): East-African outpatient, the 3 dev styles, chapters weighted like dev.
- **General** (250): all 26 chapters, 14 settings and 7 styles. 151 of them are in 15 non-English languages or code-mixes.
- **Construction:** the writer sees the chosen code's siblings, so the note carries the deciding detail, or omits it for a `.Z` code.
- **Verification:** a different model re-coded each note blind. 267 agree, 70 disagree, and 63 were not checked (quota).
- **Known bias:** LLM-written notes name the diagnosis more cleanly than real ones.
- **Use:** setting changes were compared on these frozen sets (`tools/ab.py`), not on dev. One choice that dev favoured was rejected on that basis.

## Where the AI tooling was wrong
1. **Timestamps.** The AI assistant wrote the `DECISIONS.md` timestamps for D4–D9 from its own estimate rather than the clock, up to 2 h 24 m ahead of the real commits. Checking against `git log` caught it, and the entries were corrected with a visible note (commit `8d05b57`).
2. **Default model.** Its first OpenAI default, gpt-5.4-mini, would have overrun the $6 cap. This showed up when measured tokens were priced.
3. **Code it wrote.** The three faults the mocks caught above were in code it wrote. Its D15 revert of an unmeasured prompt change also dropped a newline, so the shipped prompt differed from the measured one until a byte comparison caught it (D16).

Hours spent: about 8 (7:30–15:30 IST, 5 Nov 2026).
