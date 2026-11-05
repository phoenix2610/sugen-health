# Decisions log

Kept as we go. Each entry has its time (IST, matching the commit), the commit it goes with, the decision and the options considered, the evidence that decided it, and what to revisit.

Window: the pack arrived just after midnight on 2026-11-05 IST, so the deadline is about 00:00 on 2026-11-08 IST.

---

## D1 · 2026-11-05 14:05 · commit `7033d39` · repo layout

- **Decision:** one repo. The files Sugen gave us live untouched under `problem/`, and the solution lives beside them. `docker-compose.yml` has to sit at the repo root, because the graders run `docker compose run coder ...` from a clean clone.
- **Options:** a separate solution repo; the given files left at the root mixed in with our code; a `problem/` subdirectory.
- **Why:** a subdirectory keeps the history in one place, as the brief asks, and keeps the given files clearly separate from ours. `problem/score.py` is the exact grading script, so we never edit it.
- **Revisit:** nothing likely.

## D2 · 2026-11-05 14:05 · commit `7033d39` · Gemini for development only, OpenAI/Anthropic at run time

- **Decision:** use Gemini (the author's existing key, kept outside the repo in `~/whatever/gemini.env`) only for offline, build-time work: generating synthetic evaluation notes, translations, and trying out prompts. At run time the system calls only OpenAI or Anthropic.
- **Options:** Gemini at run time; no LLM at all during development; Gemini as a development stand-in behind a provider-neutral interface.
- **Why:** the grading box can reach only `api.openai.com` and `api.anthropic.com` through `HTTPS_PROXY`, so a run-time Gemini call would always fail and drop us to the no-key path. The LLM layer is provider-neutral, so prompts we tune on Gemini carry over.
- **Risk:** the real run-time providers are untested until we have an OpenAI or Anthropic key. Gemini and Claude/GPT behave differently on the same prompt.
- **Revisit:** get even a small OpenAI or Anthropic key and run the full dev set through the real path before submitting.

## D3 · 2026-11-05 14:05 · commit `7033d39` (crawler: `2b8d494`) · WHO ICD-API for extra data

- **Decision:** pull per-code detail for all 18,375 MMS 2026-01 categories from the official WHO ICD-API (`id.who.int`, release `2026-01`, OAuth client credentials) at build time, and commit a compact derived index.
- **Options:** titles only; scraping the ICD browser; the API; the WHO offline Docker container.
- **Why:** a test entity (`1A00`) returns `definition`, `inclusion`, `indexTerm` and `fullySpecifiedName`, which is the synonym and lay-term coverage that titles lack. The API also serves non-English languages, which matter for the multilingual hidden slice.
- **Revisit:** whether the offline container is faster for a full crawl in several languages.

## D4 · 2026-11-05 14:30 · commit `2b8d494` · no paid OpenAI/Anthropic credit, so the keyed path is a projection

- **Decision:** build the OpenAI and Anthropic run-time path fully, but measure it by running the identical prompt and candidates through Gemini as a stand-in. Cost is projected from the measured token counts at OpenAI and Anthropic list prices.
- **Options:** buy credit; ship only the no-key path; project the keyed path from a stand-in model.
- **Evidence:** the OpenAI key we have authenticates (`/v1/models` returns 200 and lists gpt-5.x), but every completion fails with `429 insufficient_quota / credit_balance_exhausted`. The author is not in a position to add credit.
- **Consequence:** the no-key path is the only one we can verify end to end, so it gets real effort. The keyed path must degrade safely, per note, on any API error: bad key, quota, timeout or proxy.
- **Revisit:** a single real run on GPT or Claude would replace the projection with a measurement.

## D5 · 2026-11-05 14:31 · commit `2b8d494` · predict leaf codes only

- **Decision:** restrict candidates to the 15,912 leaf categories (10,578 specific plus 5,334 residual `.Y`/`.Z`). Never output a non-leaf parent.
- **Evidence:** all 61 dev gold codes are leaves. 14 (23%) are `.Z` unspecified, 0 are `.Y`. The brief says a parent does not count when a child fits.
- **Revisit:** if a non-leaf turns up as gold in our synthetic or translated checks.

## D6 · 2026-11-05 14:40 · commit `84f5443` · synthetic evaluation set: free-tier Gemini, so Gemma writes and flash-lite checks

- **Decision:** generate about 500 synthetic notes: 200 "core" (East-African outpatient, English, the 3 dev styles, chapters weighted like dev gold) and 300 "general" (all chapters, 14 settings, about half non-English or code-mixed, 7 styles). `gemma-4-26b-a4b-it` writes each note against a random 120-code slice of one chapter, seeing the chosen code's siblings so the note carries, or deliberately omits, the distinguishing detail. A different model (`gemini-3.1-flash-lite`) then re-codes it blind against the sibling family, and agreement is stored as `verified`.
- **Options:** hand-writing notes (too slow for every chapter); translating the dev notes (covers language only, not chapters); LLM-written notes with a blind re-coding check.
- **Evidence:** the first run used `gemini-3.6-flash`; 26 of the first calls failed with `429 ... free_tier_requests, limit: 20` (per day). The key is free tier. Probing showed Gemma 4 and the flash-lite models still serve, so the client now rotates models when one hits its daily limit.
- **Known bias:** an LLM writing for a code it was shown tends to name the diagnosis cleanly, so synthetic accuracy will read high. Report verified and unverified notes separately and weight dev accuracy above synthetic.
- **Revisit:** a paid tier for a stronger writer; a human pass over a sample.

## D7 · 2026-11-05 14:47 · commit `9a5f3e5` · lexical retrieval over WHO terms as the no-key path and candidate generator

- **Decision:** score every WHO term (titles, full names, index terms, inclusions; English plus 8 languages) by the rarity-weighted share of its words found in the note: `matched × coverage^p`. Roll terms up to codes by taking the maximum. Score the clinician's stated diagnosis (`A:`, `Imp:`, `Dx`, the doctor's turns with a diagnostic cue) at full weight and the whole note at 0.35. A `.Z` child inherits its parent's terms. Leaves only.
- **Options:** title-only search; full-text search over each code's concatenated terms (long documents get penalised); dense embeddings (deferred until measured); matching each term on its own.
- **Evidence (dev, 60):** the titles-and-coverage² baseline scored top-1 0.583, top-3 0.767, R@10 0.933, R@100 1.00. Sweeping the coverage power p gave 1.0 → 0.617, 1.5 → 0.650, 2.0 → 0.667, 3.0 → 0.617 top-1. Took 2.0 provisionally, pending the synthetic sets.
- **General rules, not tuned to dev:** `.Y` ×0.6 (never gold, rarely decidable from text). Obstetric (ch 18) and perinatal (ch 19) codes ×0.35 unless pregnancy or newborn wording appears; the regexes cover 10+ languages. These came from failures like `KA64.20 Congenital falciparum malaria` outranking adult malaria.
- **Revisit:** dense multilingual embeddings for Swahili, Hindi and Amharic, which have no WHO translation.

## D8 · 2026-11-05 14:48 · commit `9a5f3e5` · keyed path: extract, retrieve, choose; Claude Haiku 5.5 by default

- **Decision:** two calls per note. (1) Extract the main diagnosis in English, with its qualifiers, synonyms and other diagnoses. (2) Choose up to 3 codes from about 40 retrieved candidates plus the families of the leading candidates, so `.Z` versus a specific child is a visible choice. The output is validated against MMS and forced to a leaf, then topped up to 3 from the no-key ranking. Provider order: Anthropic, then OpenAI, then none.
- **Options:** a single call with candidates only (fails on non-English notes, because retrieval runs on the raw text); letting the LLM recall codes freely (risk of invalid or hallucinated codes); a two-call cascade with a bigger model only on low-confidence notes.
- **Evidence:** a projection on 5 dev notes with `gemini-3-flash-preview` as the stand-in got 5 of 5 right, using about 2.2k input and 2.1k output tokens per note. At list prices: Haiku 5.5 about 0.13¢ per note ($0.77 for 600); Sonnet 5.5 about 2.6¢ per note ($15, over the cap); gpt-5.4-mini about 1.1¢ (OpenAI prices unverified). Haiku 5.5 is the only strong option with real headroom under $6.
- **Safety:** a $5.00 budget guard, a 45-minute deadline guard, per-note fallback to the no-key answer, and an output file rewritten atomically after the no-key pass.
- **Revisit:** spend the remaining headroom (about $5) on a Sonnet second opinion for low-confidence notes.

## D9 · 2026-11-05 14:56 · commit `b19de65` · container, failure modes and a circuit breaker

- **Decision:** `python:3.12-slim` with numpy, scipy and pinned Anthropic and OpenAI SDKs; no torch for now. The knowledge base (`coder/data/kb.json.gz`) ships in the repo, and the image build fails if it does not load. Compose passes the keys and proxy variables through and mounts `./in` and `./out`.
- **Measured, exact grading command on dev:**
  - no key: complete file in 0.7 s, **53.7 / 75**;
  - bad key with real network: 401s, the breaker trips, done in 3 s, same 53.7;
  - dead proxy (`HTTPS_PROXY=10.255.255.1`): before the breaker, every call hung (60 s timeout × retries) until the deadline guard, 183 s for 60 notes, and on 600 notes it would have burnt the 45-minute guard. Added a 10 s connect timeout and a breaker (stop after 16 failures with no success): **96 s**.
- **Untestable surface:** the OpenAI key has no credit, and OpenAI checks credit *before* validating parameters (a deliberately bad `reasoning_effort` also returns 429), so our request body has not been validated against OpenAI. We know only that `gpt-5.4-mini` exists (a bad model name returns 404, ours does not). Anthropic is likewise checked only up to authentication. Mitigation: each provider retries without the optional parameters (`output_config`, `reasoning_effort`) if the API rejects them.
- **Revisit:** the volume layout, in case the graders mount differently. Worth asking by email.

> **Correction (15:08):** D4 to D9 were first written with times estimated by the AI assistant (up to 17:20) instead of read from the clock. They are now matched to the actual commit times from `git log`, and every entry names its commit. From here on, times come from `date` at commit.

## D10 · 2026-11-05 15:08 · commit `d07b525` · tuning on synthetic, not dev; OpenAI default changed to gpt-5-mini; dense retrieval held back

- **Coverage power:** on 60 dev plus 140 synthetic notes, p=2.0 won only on dev (0.667 against 0.650 at 1.5), while 1.5 matched or beat it on both synthetic slices (core 0.650 vs 0.633, general 0.237 vs 0.225). Took **1.5**, the less dev-fitted value.
- **No-key baseline, official scorer:** dev **52.5/75** (top-1 0.650, top-3 0.800). Synthetic, weighted like the hidden 450/150 split: core 49.6/75 plus general 7.5/25 = **57.0/100**. The general slice is the weak spot: non-English R@30 is 0.40 against 0.70 for English, and chapters 22 (injury), 24 (factors) and 16 (genitourinary) have about 0 recall.
- **OpenAI prices checked** on developers.openai.com/api/docs/pricing: gpt-5.4-mini /usr/bin/zsh.75/.50, gpt-5-mini /usr/bin/zsh.25/.00 per 1M tokens. At the measured 2.2k input and 2.1k output tokens per note, gpt-5.4-mini projects to **.76 for 600 notes, over the  cap**, so the  guard would cut about 150 notes back to no-key answers. Default changed to **gpt-5-mini** (about .90). Anthropic stays first (Haiku 5.5, about /usr/bin/zsh.77).
- **Dense retrieval (multilingual-e5-small over 66k English terms, 331 s to encode):** union recall on the general slice 0.533 → 0.622; fused top-1 +1 to 3 points. Costs torch plus a 470 MB model in the image. **Held back** until the keyed projection shows whether the LLM's English extraction already recovers that recall.

## D11 · 2026-11-05 15:14 · commit `57b6d36` · keyed path projected on dev: 67.5 / 75

- **Measured:** `tools/project.py` runs the real pipeline (`coder.llm.run_llm`) with Gemini standing in. Dev: **top-1 0.867, top-3 0.967, 67.5/75**, against 52.5 for no-key. One note of 60 failed and kept its no-key answer.
- **Caveat:** `gemini-3-flash-preview` hit its free-tier daily cap after 8 calls, so 102 of the 118 calls were served by `gemini-flash-lite-latest` (no thinking). The stand-in is weaker than Haiku 5.5 or gpt-5-mini, so we treat this as a lower bound.
- **Tokens:** 2,414 input and 221 output per note with a non-thinking stand-in. Real Haiku 5.5 or gpt-5-mini will add reasoning tokens, so cost planning keeps the earlier 2.1k-output measurement from the thinking stand-in (/usr/bin/zsh.77 for 600 on Haiku, about .90 on gpt-5-mini).
- **Remaining misses:** all are specificity choices the model saw. `.Z` was chosen over a specific child, or the reverse: "HTN stage 2" with 162/104 should be BA00.0 combined, `OA knees` should be FA01.Z rather than the broader FA0Z. One recall miss: hypoglycaemia in a diabetic should be 5A21.0, but 5A41 was picked.
- **Revisit:** sharper specificity rules in the choose prompt, checked on synthetic rather than dev.

## D12 · 2026-11-05 15:17 · commit `3bf59ac` · free-tier quota is now the binding constraint; the specificity prompt is not yet measured

- **What happened:** `gemini-3.5-flash-lite` and `gemini-flash-lite-latest` hit their daily caps (429 "exceeded your current quota"). (1) The synthetic verifier has failed silently since general note ~172, so those rows are `verified=false` only because `verifier_code` is empty. Added `tools/reverify.py` to re-check just those rows after the quota resets. (2) The dev re-projection of the new choose prompt went straight to the no-key fallback (`served by: {}`, 1 s), so **the prompt change is unmeasured**. The pipeline did behave as designed under total provider failure: complete output, 53.3/75.
- **Prompt change (in this commit, unmeasured):** a sibling-by-sibling qualifier checklist in CHOOSE, aimed at the main remaining error class (`.Z` versus a specific child, and a block-level "unspecified" versus a stated site). The "which BP components are raised" example reflects ICD-11's own split of BA00, but a dev miss (dev-042) is what drew my attention to it, so it is partly dev-informed.
- **Quota plan:** Gemma (separate quota) runs the 160-note synthetic projection now. Flash-lite quotas reset around 13:30 IST on 6 Nov, which is when the prompt A/B on dev and the re-verification happen.
- **Revisit:** if the prompt A/B shows no gain on synthetic, revert it.

## D13 · 2026-11-05 15:19 · commit `354f803` · synthetic sets frozen at 400 notes

- **Core** 150 (English, 17 chapters): 118 verified, 30 where the blind verifier chose a different code (gold noise or a hard case), 2 unchecked.
- **General** 250 (26 chapters; 99 English, the rest across 15 languages and code-mixes): 149 verified, 40 disagreeing, 61 unchecked (verifier quota, see D12).
- Frozen from here on, so before/after comparisons use identical notes. Earlier numbers in D10 came from growing partial sets and are not comparable. Scores will be reported both on all notes and on verified notes only.

## D14 · 2026-11-05 15:21 · commit `23aeed2` · no-key knobs left alone; dense retrieval dropped

- **A/B on frozen sets** (`tools/ab.py`; synthetic weighted 75/25 like the hidden set):

  | Setting | Dev /75 | Synthetic /100 |
  |---|---|---|
  | baseline | 53.3 | 55.6 |
  | COV_POW 1.0 | 54.6 | 56.0 |
  | COV_POW 2.0 | 54.6 | 55.7 |
  | no `.Y` penalty | 51.7 | 53.9 |
  | no chapter gates | 52.5 | 55.8 |
  | full-note weight 0.2 | 52.9 | 55.1 |
  | full-note weight 0.6 | 51.2 | 54.4 |
  | parent bonus 0 | 53.8 | 55.3 |
  | parent bonus 0.3 | 53.3 | 56.2 |

- **Read:** apart from `.Y` (-1.6 on dev and -1.7 on synthetic when removed), every knob is within about ±1 point, which is noise for 400 notes. Settings stay as they are rather than fitting noise. The chapter gates are neutral on synthetic and +0.8 on dev, and are kept because the rule is principled.
- **Dense embeddings dropped** (D10 probe: about +1 to 3 top-1 points and +9 recall on general, no-key only). A gain of 1 to 2 points to the fallback path does not justify about 1.5 GB of torch plus model in the image, and a heavier `docker compose build` is a bigger risk to the clean-clone gate than the gain is worth. The keyed path covers language through its English extraction.
- **Revisit:** an ONNX build of the embedding model (smaller, no torch) if time allows.

## D15 · 2026-11-05 15:29 · commit `8c20b5f` · stopping here: ship what was measured

- **Decision:** stop the remaining jobs (the Gemma synthetic projection at about 1/3 of 160 notes, and the WHO crawl after en, es, fr, pt and 80% of ar) and ship. The free-tier Gemini quota made every further keyed measurement slow and partial, and without a funded OpenAI or Anthropic key no further run would turn the projection into a measurement.
- **Reverted the D12 choose-prompt checklist.** It was never measured (quota), and the 67.5/75 projection was produced without it, so the shipped prompt is the measured one.
- **Final numbers** (official scorer; raw files in `results/`):
  - no-key: dev 52.9/75; synthetic 55.9/100 (verified-only 63.3);
  - keyed, Gemini stand-in: dev 67.5/75 (top-1 0.867, top-3 0.967);
  - keyed on synthetic: not measured.
- **Final knowledge base:** 254k terms, 3.2 MB.
- **Revisit with a funded key:** run `tools/project.py`-equivalent on Haiku 5.5 and gpt-5-mini over dev plus 400 synthetic notes, A/B the specificity checklist, then decide on a Sonnet second opinion for low-confidence notes (about  of headroom).

## D16 · 2026-11-05 17:13 · commit `7116ed3` · mocked integration tests; three keyed-path faults fixed

- **Trigger:** Sugen replied (16:34) that no development keys are supplied, and asked for mocked tests of the integration. They also asked that no-key, mocked, live and estimated numbers be kept clearly apart, and that untested live behaviour be documented.
- **Options:**
  - Unit tests with a fake provider object. Rejected: they bypass the SDKs, which is where request shape and retries live.
  - A local HTTP mock of both APIs that the shipped image reaches through `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`. Chosen.
- **Setup:** `tools/mock_api.py` and `tools/mock_test.py`. There are 18 mocked cases plus 2 live-unauth cases, in which a local CONNECT proxy relays to the real endpoints with an invalid key.
- **Evidence:** the first run passed 17 of 18 mocked cases. It exposed:
  1. An OpenAI fallback race. The shared `reasoning` flag was checked after a parallel worker had already cleared it, so 7 of 60 notes kept no-key answers.
  2. The Anthropic `output_config` rejection was retried on every call.
  3. The budget guard checked only spent money, so the 8 workers' in-flight calls could overshoot it.
- **Fixes:** a per-request retry condition, a remembered `structured` flag, and a worst-case reservation per call. Reserved cost is the input at 3 chars/token plus the `max_tokens` cap.
- **Result:** 20 of 20 pass (`results/mock_tests.txt`). The no-key output is byte-identical to `results/dev_nokey.pred.jsonl` (52.9/75).
- **Correction to D15:** the revert there dropped one newline in CHOOSE, so "the shipped prompt is the measured one" was not quite true. The newline is restored, and SYSTEM, EXTRACT, CHOOSE and both schemas now compare equal to `d07b525`, the version the 67.5 stand-in ran on.
- **Also:** `tools/project.py` now lifts the budget guard. It prices Gemini as an unknown model ($5/$25 per 1M tokens), which would stop a projection after about 60 notes.
- **Revisit:** with a real key, run `tools/mock_test.py`'s happy-path checks live first. Then run the stand-in harness with the real provider on dev and the 400 synthetic notes.
