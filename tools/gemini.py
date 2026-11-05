"""Gemini client for DEVELOPMENT ONLY (synthetic eval data, prompt trials, keyed-path projection).

The graded system never imports this: at run time only api.openai.com / api.anthropic.com are reachable.
Key is read from GEMINI_KEY_FILE (default ~/whatever/gemini.env, line API_KEY=...), never from the repo.
"""
import json
import os
import time
import urllib.error
import urllib.request

KEY_FILE = os.path.expanduser(os.environ.get("GEMINI_KEY_FILE", "~/whatever/gemini.env"))
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _key():
    for line in open(KEY_FILE):
        if line.startswith("API_KEY"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("no API_KEY in " + KEY_FILE)


EXHAUSTED = set()  # models whose free-tier daily quota is used up this run


def generate(prompt, model="gemma-4-26b-a4b-it", system=None, temperature=0.7, json_mode=False, tries=6,
             fallbacks=("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest")):
    """Call Gemini; on a daily-quota 429 move to the next model in `fallbacks` (free-tier key)."""
    models = [m for m in (model, *fallbacks) if m not in EXHAUSTED]
    last = None
    for m in models:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode and not m.startswith("gemma"):
            body["generationConfig"]["responseMimeType"] = "application/json"
        for i in range(tries):
            req = urllib.request.Request(ENDPOINT.format(model=m), data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
            try:
                r = json.load(urllib.request.urlopen(req, timeout=180))
                parts = r["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                if json_mode:
                    a, b = text.find("{"), text.rfind("}")
                    text = text[a:b + 1] if a >= 0 else text
                u = r.get("usageMetadata", {})
                u["model"] = m
                return text, u
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:600]
                last = f"{m} {e.code}: {msg[:200]}"
                if e.code == 429 and "per day" in msg.lower() or "PerDay" in msg:
                    EXHAUSTED.add(m)
                    break
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(min(60, 5 * (i + 1)))
                    continue
                break
            except (KeyError, IndexError, urllib.error.URLError, TimeoutError, OSError) as e:
                last = f"{m}: {e!r}"
                time.sleep(3 * (i + 1))
    raise RuntimeError("gemini: all models failed; last=" + str(last))


if __name__ == "__main__":
    import sys
    for m in sys.argv[1:] or ["gemini-3.6-flash"]:
        try:
            t, u = generate("Reply with only the ICD-11 MMS code for cholera.", model=m, temperature=0)
            print(m, repr(t.strip()), u)
        except Exception as e:
            print(m, "ERR", e)
