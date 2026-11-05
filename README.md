# ICD-11 coder: Sugen take-home

Work in progress. This becomes the one-page README the brief asks for.

- `problem/` holds the take-home pack exactly as received: the brief, `score.py`, the dev notes and the MMS 2026-01 code list.
- `DECISIONS.md` is the running decision log.

## Third-party data and tools

- **WHO ICD-11 API** (`id.who.int`, release 2026-01): definitions, inclusions and index terms for each code, pulled at build time.
- **Google Gemini** (the author's own API key, stored outside the repo and never committed): used *only during development*, for synthetic evaluation notes and prompt trials. The submitted system never calls Gemini, because at run time it can reach only OpenAI and Anthropic.
