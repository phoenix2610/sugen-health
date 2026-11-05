"""Sweep no-key knobs and report top1/top3/R@30 per eval file.
python tools/sweep.py 'kb.KB.COV_POW=[1,1.5,2]' file1.jsonl [file2 ...]"""
import json, os, sys, itertools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import coder.kb as kb_mod, coder.nokey as nk
kb = kb_mod.KB()
spec, files = sys.argv[1], sys.argv[2:]
target, values = spec.split("=", 1)
values = json.loads(values)
data = {f: [json.loads(l) for l in open(f, encoding="utf-8")] for f in files}
for v in values:
    obj, attr = target.rsplit(".", 1)
    holder = {"kb.KB": kb_mod.KB, "nk": nk}[obj]
    setattr(holder, attr, v)
    r = nk.Ranker(kb)
    out = []
    for f, rows in data.items():
        t1 = t3 = r30 = 0
        for row in rows:
            ranked = [c for c, _ in r.rank(row["text"], k=30)]
            g = set(row["gold"])
            t1 += ranked[0] in g; t3 += bool(g & set(ranked[:3])); r30 += bool(g & set(ranked))
        n = len(rows)
        out.append(f"{os.path.basename(f)[:14]}: t1={t1/n:.3f} t3={t3/n:.3f} R30={r30/n:.3f}")
    print(f"{target}={v}  " + " | ".join(out))
