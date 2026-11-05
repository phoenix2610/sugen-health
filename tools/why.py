"""Debug: top matched terms for a note id. python tools/why.py gold.jsonl dev-001"""
import json, sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from coder.kb import KB
from coder.text import diagnosis_text, expand
kb = KB()
row = next(json.loads(l) for l in open(sys.argv[1]) if json.loads(l)["id"] == sys.argv[2])
dx = diagnosis_text(row["text"]); print("DX:", dx); print("GOLD:", row["gold"], [kb.title(c) for c in row["gold"]])
for name, txt in (("dx", expand(dx)), ("full", expand(row["text"]))):
    ts = kb.term_scores(txt); top = np.argsort(-ts)[:8]
    print(f"-- {name}")
    for t in top: print(f"   {ts[t]:.2f} {kb.codes[kb.term_code[t]]['c']:9} [{kb.term_kind[t]}] {kb.terms[t][1][:70]}")
for g in row["gold"]:
    gi = kb.by_code[g]; mask = kb.term_code == gi
    print("gold terms:", [kb.terms[i][1] for i in np.where(mask)[0]][:15])
