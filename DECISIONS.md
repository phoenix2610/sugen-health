# Decisions log

Kept as we go. Each entry has its time (IST), the commit it goes with, the decision and the options considered, the evidence that decided it, and what to revisit.

Window: the pack arrived just after midnight on 2026-11-05 IST, so the deadline is about 00:00 on 2026-11-08 IST.

---

## D1 · 2026-11-05 14:05 · repo layout

- **Decision:** one repo. The files Sugen gave us live untouched under `problem/`, and the solution lives beside them. `docker-compose.yml` has to sit at the repo root, because the graders run `docker compose run coder ...` from a clean clone.
- **Options:** a separate solution repo; the given files left at the root mixed in with our code; a `problem/` subdirectory.
- **Why:** a subdirectory keeps the history in one place, as the brief asks, and keeps the given files clearly separate from ours. `problem/score.py` is the exact grading script, so we never edit it.
- **Revisit:** nothing likely.

## D2 · 2026-11-05 14:05 · Gemini for development only, OpenAI/Anthropic at run time

- **Decision:** use Gemini (the author's existing key, kept outside the repo in `~/whatever/gemini.env`) only for offline, build-time work: generating synthetic evaluation notes, translations, and trying out prompts. At run time the system calls only OpenAI or Anthropic.
- **Options:** Gemini at run time; no LLM at all during development; Gemini as a development stand-in behind a provider-neutral interface.
- **Why:** the grading box can reach only `api.openai.com` and `api.anthropic.com` through `HTTPS_PROXY`, so a run-time Gemini call would always fail and drop us to the no-key path. The LLM layer is provider-neutral, so prompts we tune on Gemini carry over.
- **Risk:** the real run-time providers are untested until we have an OpenAI or Anthropic key. Gemini and Claude/GPT behave differently on the same prompt.
- **Revisit:** get even a small OpenAI or Anthropic key and run the full dev set through the real path before submitting.

## D3 · 2026-11-05 14:05 · WHO ICD-API for extra data

- **Decision:** pull per-code detail for all 18,375 MMS 2026-01 categories from the official WHO ICD-API (`id.who.int`, release `2026-01`, OAuth client credentials) at build time, and commit a compact derived index.
- **Options:** titles only; scraping the ICD browser; the API; the WHO offline Docker container.
- **Why:** a test entity (`1A00`) returns `definition`, `inclusion`, `indexTerm` and `fullySpecifiedName`, which is the synonym and lay-term coverage that titles lack. The API also serves non-English languages, which matter for the multilingual hidden slice.
- **Revisit:** whether the offline container is faster for a full crawl in several languages.

## D4 · 2026-11-05 14:40 · no paid OpenAI/Anthropic credit, so the keyed path is a projection

- **Decision:** build the OpenAI and Anthropic run-time path fully, but measure it by running the identical prompt and candidates through Gemini as a stand-in. Cost is projected from the measured token counts at OpenAI and Anthropic list prices.
- **Options:** buy credit; ship only the no-key path; project the keyed path from a stand-in model.
- **Evidence:** the OpenAI key we have authenticates (`/v1/models` returns 200 and lists gpt-5.x), but every completion fails with `429 insufficient_quota / credit_balance_exhausted`. The author is not in a position to add credit.
- **Consequence:** the no-key path is the only one we can verify end to end, so it gets real effort. The keyed path must degrade safely, per note, on any API error: bad key, quota, timeout or proxy.
- **Revisit:** a single real run on GPT or Claude would replace the projection with a measurement.

## D5 · 2026-11-05 14:45 · predict leaf codes only

- **Decision:** restrict candidates to the 15,912 leaf categories (10,578 specific plus 5,334 residual `.Y`/`.Z`). Never output a non-leaf parent.
- **Evidence:** all 61 dev gold codes are leaves. 14 (23%) are `.Z` unspecified, 0 are `.Y`. The brief says a parent does not count when a child fits.
- **Revisit:** if a non-leaf turns up as gold in our synthetic or translated checks.
