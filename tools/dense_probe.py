"""Measure whether multilingual dense retrieval adds recall over the lexical ranker (dev tool).
python tools/dense_probe.py MODEL files..."""
import json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sentence_transformers import SentenceTransformer
from coder.kb import KB, softmax_top
from coder.nokey import Ranker
from coder.text import diagnosis_text
model_name, files = sys.argv[1], sys.argv[2:]
kb = KB(); r = Ranker(kb)
sel = [i for i, t in enumerate(kb.terms) if t[2] == "en" and t[3] != "inherit"]
texts = [kb.terms[i][1] for i in sel]
m = SentenceTransformer(model_name, device="cpu")
pre_q, pre_p = ("query: ", "passage: ") if "e5" in model_name else ("", "")
cache = f"cache/dense_{model_name.replace('/', '_')}.npy"
t = time.time()
if os.path.exists(cache) and np.load(cache).shape[0] == len(texts):
    E = np.load(cache)
else:
    E = m.encode([pre_p + x for x in texts], batch_size=256, normalize_embeddings=True, show_progress_bar=False).astype(np.float16)
    np.save(cache, E)
print(f"encoded {len(texts)} terms in {time.time()-t:.0f}s")
tc = kb.term_code[sel]
for f in files:
    rows = [json.loads(l) for l in open(f, encoding="utf-8")]
    hits = {"lex": 0, "dense": 0, "union": 0, "fused_t1": 0, "lex_t1": 0}
    for row in rows:
        g = set(row["gold"])
        s_lex = r.scores(row["text"])
        lex = [kb.codes[i]["c"] for i in softmax_top(s_lex, 30)]
        dx = diagnosis_text(row["text"]) or row["text"]
        q = m.encode([pre_q + dx[:1000], pre_q + row["text"][:2000]], normalize_embeddings=True)
        sim = (E.astype(np.float32) @ q.T).max(axis=1)
        cs = np.full(len(kb.codes), -1.0, dtype=np.float32); np.maximum.at(cs, tc, sim)
        # roll parents' similarity to .Z children, leaves only
        for pi, kids in kb.children.items():
            for k in kids:
                if kb.codes[k]["c"].endswith("Z"): cs[k] = max(cs[k], cs[pi])
        cs[~kb.leaf] = -1
        dense = [kb.codes[i]["c"] for i in softmax_top(cs, 30)]
        hits["lex"] += bool(g & set(lex)); hits["dense"] += bool(g & set(dense)); hits["union"] += bool(g & set(lex[:20] + dense[:20]))
        # simple fusion: normalised lexical + dense
        fused = s_lex / (s_lex.max() + 1e-6) + 1.0 * np.clip((cs - 0.75) / 0.25, 0, None)
        hits["fused_t1"] += kb.codes[int(np.argmax(fused))]["c"] in g; hits["lex_t1"] += lex[0] in g
    n = len(rows)
    print(os.path.basename(f), n, {k: round(v / n, 3) for k, v in hits.items()})
