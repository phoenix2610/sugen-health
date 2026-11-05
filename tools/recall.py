"""Retrieval recall@k of the no-key ranker: python tools/recall.py gold.jsonl [gold2.jsonl ...]"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from coder.kb import KB
from coder.nokey import Ranker
kb = KB(); r = Ranker(kb)
for path in sys.argv[1:]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    ks = [1, 3, 10, 30, 50, 100]
    hit = {k: 0 for k in ks}
    for row in rows:
        ranked = [c for c, _ in r.rank(row["text"], k=100)]
        g = set(row["gold"])
        for k in ks:
            hit[k] += bool(g & set(ranked[:k]))
    print(os.path.basename(path), "n=%d" % len(rows), " ".join(f"R@{k}={hit[k]/len(rows):.3f}" for k in ks))
