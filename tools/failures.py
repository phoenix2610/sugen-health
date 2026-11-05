"""Show misses: python3 tools/failures.py gold.jsonl pred.jsonl"""
import json, sys
mms = {r["code"]: r["title"] for r in json.load(open("problem/data/mms-2026-01.json"))}
gold = {r["id"]: r for r in map(json.loads, open(sys.argv[1], encoding="utf-8"))}
pred = {r["id"]: r["codes"] for r in map(json.loads, open(sys.argv[2], encoding="utf-8"))}
for nid, g in gold.items():
    p = pred.get(nid, [])
    if p[:1] and p[0] in g["gold"]:
        continue
    tag = "TOP3" if set(p[:3]) & set(g["gold"]) else "MISS"
    print(f"{tag} {nid} [{g.get('lang', '')}] gold={[(c, mms.get(c, '?')[:45]) for c in g['gold']]}")
    print("      pred=", [(c, mms.get(c, '?')[:40]) for c in p[:3]])
