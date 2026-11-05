"""Fast no-key A/B on frozen sets: points as the official scorer computes them, all vs verified-only.
python tools/ab.py [module.ATTR=value ...]   e.g. nk.Y_PENALTY=0.4 kb.KB.COV_POW=2"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import coder.kb as kb_mod, coder.nokey as nk, coder.text as tx
for arg in sys.argv[1:]:
    tgt, val = arg.split("=", 1)
    obj, attr = tgt.rsplit(".", 1)
    setattr({"kb.KB": kb_mod.KB, "nk": nk, "tx": tx}[obj], attr, json.loads(val))
kb = kb_mod.KB(); r = nk.Ranker(kb)
def run(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    res = []
    for row in rows:
        p = [c for c, _ in r.rank(row["text"], k=3)]; g = set(row["gold"])
        res.append((p[0] in g, bool(g & set(p)), row.get("verified", True)))
    def pts(sub, w1, w3):
        n = len(sub) or 1
        return w1 * sum(a for a, _, _ in sub) / n + w3 * sum(b for _, b, _ in sub) / n
    return res, pts
out = []
dev, p = run("problem/data/dev_notes.jsonl"); out.append(f"dev {p(dev, 50, 25):.1f}/75")
core, p = run("eval/synth_core.jsonl"); gen, _ = run("eval/synth_general.jsonl")
A, B = p(core, 50, 25), p(gen, 50 / 3, 25 / 3)
Av, Bv = p([x for x in core if x[2]], 50, 25), p([x for x in gen if x[2]], 50 / 3, 25 / 3)
out.append(f"synth A {A:.1f}/75 B {B:.1f}/25 = {A + B:.1f}/100 | verified-only A {Av:.1f} B {Bv:.1f} = {Av + Bv:.1f}")
print(" ".join(sys.argv[1:]) or "baseline", "::", " | ".join(out))
