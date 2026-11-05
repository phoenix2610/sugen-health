"""Projection of the keyed path (DEV ONLY): run the real coder pipeline with Gemini standing in for
OpenAI/Anthropic, then score and project cost from the measured token counts.

python tools/project.py gold.jsonl out_pred.jsonl [--model gemini-3-flash-preview] [--limit N]
"""
import argparse
import collections
import json
import os
import sys
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import gemini  # noqa: E402
from coder import llm  # noqa: E402
from coder.__main__ import Writer  # noqa: E402
from coder.kb import KB  # noqa: E402
from coder.nokey import Ranker  # noqa: E402


class GeminiProvider:
    name = "gemini(dev-proxy)"

    def __init__(self, model, fallbacks):
        self.model, self.fallbacks = model, fallbacks
        self.served = collections.Counter()

    def complete(self, user, schema, effort="low", max_tokens=3000):
        text, u = gemini.generate(user, model=self.model, system=llm.SYSTEM, temperature=0.0, json_mode=True,
                                  fallbacks=self.fallbacks)
        self.served[u.get("model")] += 1
        tin = u.get("promptTokenCount", 0)
        tout = u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
        return text, "proxy", tin, tout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold")
    ap.add_argument("out")
    ap.add_argument("--model", default="gemini-3-flash-preview")
    ap.add_argument("--fallbacks", default="gemini-flash-lite-latest,gemini-3.5-flash-lite")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.gold, encoding="utf-8")]
    if a.limit:
        rows = rows[:a.limit]
    kb = KB()
    ranker = Ranker(kb)
    ids = [r["id"] for r in rows]
    base = {r["id"]: [c for c, _ in ranker.rank(r["text"], k=3)] for r in rows}
    w = Writer(a.out, ids)
    for nid in ids:
        w.preds[nid] = base[nid]
    w.flush()
    llm.WORKERS = a.workers
    llm.DEADLINE_S = 10 ** 9
    llm.BUDGET_USD = 10 ** 9  # Gemini is priced as an unknown model (5/25 per 1M), which would trip the $5 guard
    prov = GeminiProvider(a.model, tuple(x for x in a.fallbacks.split(",") if x))
    log = []
    t0 = time.time()
    b = llm.run_llm(rows, ids, kb, ranker, base, w, t_start=t0, provider=prov, log=log)
    w.flush()
    with open(a.out + ".log.jsonl", "w", encoding="utf-8") as f:
        for r in log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(rows)
    print(f"served by: {dict(prov.served)}  wall={time.time() - t0:.0f}s")
    print(f"tokens/note: in={b.tin / n:.0f} out={b.tout / n:.0f}")
    for model, (pin, pout) in llm.PRICES.items():
        per = (b.tin * pin + b.tout * pout) / 1e6 / n
        print(f"  projected {model:18}: ${per * 100:.3f} cents/note -> ${per * 600:.2f} for 600 notes")


if __name__ == "__main__":
    main()
