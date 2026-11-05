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


def generate(prompt, model="gemini-3.6-flash", system=None, temperature=0.7, json_mode=False, tries=5):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    for i in range(tries):
        req = urllib.request.Request(ENDPOINT.format(model=model), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            text = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
            return text, r.get("usageMetadata", {})
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(4 * (i + 1))
                continue
            raise RuntimeError(f"{e.code}: {msg}")
        except (KeyError, IndexError, urllib.error.URLError, TimeoutError):
            time.sleep(4 * (i + 1))
    raise RuntimeError("gemini: retries exhausted")


if __name__ == "__main__":
    import sys
    for m in sys.argv[1:] or ["gemini-3.6-flash"]:
        try:
            t, u = generate("Reply with only the ICD-11 MMS code for cholera.", model=m, temperature=0)
            print(m, repr(t.strip()), u)
        except Exception as e:
            print(m, "ERR", e)
