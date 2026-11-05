# ICD-11 coder: Sugen take-home

`docker compose run coder /in/notes.jsonl /out/predictions.jsonl` writes up to 3 ICD-11 MMS 2026-01 codes per note (`./in` and `./out` are mounted).
`problem/` holds the pack as received. `DECISIONS.md` logs each choice with its commit. `results/` holds the raw output behind every number.

> **No OpenAI or Anthropic key was used, so nothing here measures GPT or Claude.** Labels:
> **measured**: the shipped image with no key, official `score.py` ·
> **mocked**: the shipped image and its real SDKs against a scripted local server (behaviour, not accuracy) ·
> **live-unauth**: the real Anthropic and OpenAI endpoints through a local CONNECT proxy, invalid key ·
> **stand-in**: the same pipeline with Gemini answering through a dev-only harness (a Gemini result) ·
> **estimate**: a forecast.

## How it works
1. **No-key ranker** (`coder/kb.py`, `coder/nokey.py`). It scores WHO terms (en, es, fr, pt, ar) by the rarity-weighted share of their words in the note. The stated diagnosis gets full weight, the rest 0.35. It outputs only **leaf codes**, like all 61 dev gold codes. `.Z` inherits its parent's terms, and `.Y` is penalised.
2. **Keyed path** (`coder/llm.py`), two calls per note:
   1. Extract the main diagnosis **in English** with its ICD qualifiers.
   2. Rerun retrieval on that text, then choose from about 40 candidates plus their families.

   Codes are validated and forced to leaves. The model is Haiku 5.5 if `ANTHROPIC_API_KEY` is set, otherwise gpt-5-mini. Nothing else is called.
3. **Safety.**
   - A complete no-key file is written before any API call, then rewritten atomically as answers arrive.
   - A $5 budget guard reserves each call's worst case before sending.
   - A 45-minute deadline guard, a 10 s connect timeout and a circuit breaker.

## Results
| | label | result |
|---|---|---|
| dev, no key | measured | **52.9 / 75** (top-1 .667, top-3 .783) |
| 400 synthetic, no key | measured | 55.9 / 100 at hidden weighting (A 47.2/75, B 8.8/25; verified-only 63.3) |
| no-key latency | measured | 2.9 s for 60 notes, 5.2 s for 400, plus about 2 s container start |
| keyed integration | mocked, live-unauth | **20 / 20 cases pass** (`tools/mock_test.py` → `results/mock_tests.txt`) |
| dev, keyed pipeline | stand-in | 67.5 / 75 (top-1 .867, top-3 .967); 102 of 118 calls by `gemini-flash-lite-latest` |
| synthetic, keyed | none | not measured (the free-tier quota stopped it at about a third) |

**What the mocks check**, on the 60 dev notes in the shipped image:
- *Requests:* the SDKs send `claude-haiku-5-5` with `output_config` (JSON schema; effort low, then medium), and `gpt-5-mini` with `json_object` and `reasoning_effort`.
- *Answers:* they are used, invalid codes are dropped, and parents become leaves.
- *Fallback:* every note keeps its no-key answer on non-JSON, refusal, 401, 429, 5xx or a refused CONNECT.
- *Guards:* a bad-key run ends in 5–9 s, spend stays under $0.01 and $0.05 caps, and the deadline holds.
- *Live-unauth:* both real endpoints were reached through `HTTPS_PROXY` and rejected the key.

**The mocks caught three faults, all now fixed:**
1. A retry race in the `reasoning_effort` fallback lost 7 of 60 notes.
2. An `output_config` rejection was not remembered.
3. Calls in flight could overshoot the budget.

## Untested live behaviour
- Whether the live APIs accept `output_config` (Haiku 5.5) and `reasoning_effort` (gpt-5-mini) as sent. The retry is tested only for an error that names the parameter.
- Answer quality of Haiku 5.5 and gpt-5-mini.
- How often Haiku 5.5's default thinking uses up `max_tokens`. That note then keeps its no-key answer.
- Real tokens, cost, latency, rate limits at 8 workers, and the graders' proxy.

## Estimates (not results)
- **Cost, 600 notes** (stand-in tokens: 2.4k in, 0.2–2.1k out per note; Haiku tokens +30%): Haiku 5.5 about $0.3–1.0, gpt-5-mini about $0.6–2.9. If every call hit `max_tokens`, $1.8 and $7.0. In that case the gpt-5-mini guard stops near $5, and the rest keep no-key answers.
- **Latency with a key:** at 3–10 s per call on 8 workers, about 8–25 minutes for 600 notes.
- **Hidden score:** with a key, about 72–85 (point estimate 78). That is core about 60–68/75 (the stand-in's 67.5, discounted) plus generalisation about 12–17/25 (no-key 8.8). Without a key, about 55–60.

## Data added
- **WHO ICD-11 API** (release 2026-01), via `tools/crawl_who.py` → `coder/data/kb.json.gz` (3.2 MB, 254k terms), for all 13,041 non-residual categories. It holds English index terms, inclusions, full names and definitions, plus es, fr, pt and ar titles, index terms and inclusions (ar about 80%).
- **Clinical abbreviation list** (`coder/text.py`), written by hand as general shorthand, not taken from the dev notes.
- **Google Gemini** (the author's free-tier key, kept outside the repo): **dev only**, for synthetic notes and the stand-in. The submission never calls it.

## Evaluation beyond the 60 dev notes
`eval/` holds 400 synthetic notes from `tools/gen_synth.py`:
- **Core** (150): East-African outpatient, dev's 3 styles and chapter mix.
- **General** (250): all 26 chapters, 14 settings, 7 styles; 151 in 15 non-English languages or code-mixes.
- **Checks:** a second model re-coded each note blind (267 agree, 70 disagree, 63 unchecked).
- **Bias:** these notes name the diagnosis more cleanly than real ones.
- **Use:** settings were tuned on these frozen sets (`tools/ab.py`), not dev, and one dev-favoured choice was rejected.

## Where the AI tooling was wrong
1. **Timestamps.** The AI assistant estimated the D4–D9 times in `DECISIONS.md`, up to 2 h 24 m ahead of the commits. `git log` caught it, and the fix carries a note (`8d05b57`).
2. **Default model.** Its first OpenAI default, gpt-5.4-mini, would have overrun the $6 cap.
3. **Code it wrote.** The three mock-found faults were its code. Its D15 prompt revert also dropped a newline, caught by a byte comparison (D16).

Hours spent: about 8.5 (7:30–15:30 and 16:55–17:20 IST, 5 Nov 2026).
