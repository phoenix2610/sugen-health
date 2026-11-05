"""Build the shipped knowledge base from the MMS code list + the WHO ICD-API crawl cache.

Output: coder/data/kb.json.gz
  codes: [{c, t, ch, leaf, res, depth, p (parent code or null)}]
  terms: [[code_idx, text, lang, kind]]   kind: title|fsn|index|incl
  defs:  {code: short English definition}  (for the LLM prompt)
Works with a partial crawl (codes without WHO data keep their title only).
"""
import gzip
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
MMS = os.path.join(ROOT, "problem", "data", "mms-2026-01.json")
CACHE = os.path.join(ROOT, "cache", "who")
OUT = os.path.join(ROOT, "coder", "data", "kb.json.gz")
LANGS = ["en", "es", "fr", "pt", "ar", "ru", "zh", "de", "tr"]
MAX_INDEX = {"en": 40}  # other languages: cap below
MAX_INDEX_OTHER = 12


def parent_of(code, codes):
    if "." not in code:
        return None
    stem, tail = code.split(".", 1)
    cand = stem + "." + tail[:-1] if len(tail) > 1 else stem
    return cand if cand in codes else (stem if stem in codes else None)


def main():
    mms = json.load(open(MMS))
    codes = {r["code"]: r for r in mms}
    idx = {r["code"]: i for i, r in enumerate(mms)}
    out_codes = [{"c": r["code"], "t": r["title"], "ch": r["chapter"], "leaf": r["leaf"], "res": r["residual"],
                  "depth": r["depth"], "p": parent_of(r["code"], codes)} for r in mms]
    terms, seen, defs = [], set(), {}

    def add(code, text, lang, kind):
        if not text:
            return
        text = " ".join(text.split())
        key = (code, text.lower())
        if key in seen:
            return
        seen.add(key)
        terms.append([idx[code], text, lang, kind])

    for r in mms:
        add(r["code"], r["title"], "en", "title")

    have = {}
    for lang in LANGS:
        path = os.path.join(CACHE, f"{lang}.jsonl")
        if not os.path.exists(path):
            continue
        n = 0
        for line in open(path, encoding="utf-8"):
            e = json.loads(line)
            c = e["code"]
            if c not in idx:
                continue
            n += 1
            add(c, e.get("title"), lang, "title")
            add(c, e.get("fsn"), lang, "fsn")
            cap = MAX_INDEX.get(lang, MAX_INDEX_OTHER)
            for t in (e.get("index") or [])[:cap]:
                add(c, t, lang, "index")
            for t in (e.get("incl") or [])[:cap]:
                add(c, t, lang, "incl")
            if lang == "en":
                d = e.get("def") or ""
                if d:
                    defs[c] = d[:300]
        have[lang] = n

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"release": "2026-01", "codes": out_codes, "terms": terms, "defs": defs}, f, ensure_ascii=False)
    print("entities per language:", have)
    print(f"codes={len(out_codes)} terms={len(terms)} defs={len(defs)} -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
