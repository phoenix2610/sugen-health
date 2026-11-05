"""Crawl WHO ICD-API per-entity detail for every non-residual MMS 2026-01 category.

Usage: python3 tools/crawl_who.py en es fr ...
Writes cache/who/<lang>.jsonl (resumable; one trimmed entity per line).
cache/ is gitignored; the derived index built from it is what ships.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
from who_api import WHO, BASE  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
MMS = os.path.join(ROOT, "problem", "data", "mms-2026-01.json")
OUT = os.path.join(ROOT, "cache", "who")


def labels(xs):
    return [x["label"]["@value"] for x in xs or [] if "label" in x]


def val(x):
    return x.get("@value") if isinstance(x, dict) else None


def trim(code, e, lang):
    r = {"code": code, "title": val(e.get("title")), "fsn": val(e.get("fullySpecifiedName")),
         "index": labels(e.get("indexTerm")), "incl": labels(e.get("inclusion"))}
    if lang == "en":
        r.update({
            "def": val(e.get("definition")), "ldef": val(e.get("longDefinition")),
            "note": val(e.get("codingNote")),
            "excl": [{"label": x["label"]["@value"], "ref": x.get("linearizationReference")}
                     for x in e.get("exclusion", []) if "label" in x],
            "pc": [s.get("axisName", "").rsplit("/", 1)[-1] for s in e.get("postcoordinationScale", [])],
        })
    return r


def main(langs):
    os.makedirs(OUT, exist_ok=True)
    rows = [r for r in json.load(open(MMS)) if r["uri"].rsplit("/", 1)[-1].isdigit()]
    who = WHO()
    for lang in langs:
        path = os.path.join(OUT, f"{lang}.jsonl")
        done = set()
        if os.path.exists(path):
            done = {json.loads(l)["code"] for l in open(path, encoding="utf-8")}
        todo = [r for r in rows if r["code"] not in done]
        print(f"[{lang}] {len(done)} cached, {len(todo)} to fetch", flush=True)
        with open(path, "a", encoding="utf-8") as f, ThreadPoolExecutor(12) as ex:
            futs = {ex.submit(who.get, f"{BASE}/{r['uri'].rsplit('/', 1)[-1]}", lang): r for r in todo}
            for n, fut in enumerate(as_completed(futs), 1):
                r = futs[fut]
                try:
                    e = fut.result()
                except Exception as exc:  # keep going; a rerun picks it up
                    print("ERR", r["code"], exc, flush=True)
                    continue
                if e:
                    f.write(json.dumps(trim(r["code"], e, lang), ensure_ascii=False) + "\n")
                if n % 1000 == 0:
                    f.flush()
                    print(f"[{lang}] {n}/{len(todo)}", flush=True)
        print(f"[{lang}] done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or ["en"])
