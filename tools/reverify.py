"""Re-run the blind verifier only on synthetic rows where it never ran (verifier_code == "").
python tools/reverify.py eval/synth_general.jsonl [--model gemma-4-26b-a4b-it]"""
import argparse, json, os, random, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from gemini import generate
import gen_synth as G

ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--model", default="gemini-3.5-flash-lite")
ap.add_argument("--fallbacks", default="gemini-flash-lite-latest,gemma-4-26b-a4b-it"); ap.add_argument("--workers", type=int, default=3)
a = ap.parse_args()
rows = [json.loads(l) for l in open(a.path, encoding="utf-8")]
todo = [r for r in rows if not r.get("verifier_code")]
print(f"{len(todo)} rows to verify", flush=True)

def one(r):
    code = r["gold"][0]
    fam = [G.BY_CODE[code]] + G.family(code)
    random.Random(r["id"]).shuffle(fam)
    opts = "\n".join(f"{x['code']}\t{x['title']}" for x in fam)
    try:
        t, _ = generate(G.VERIFY.format(note=r["text"], opts=opts), model=a.model, temperature=0, json_mode=True,
                        fallbacks=tuple(x for x in a.fallbacks.split(",") if x))
        r["verifier_code"] = json.loads(t).get("code", "").strip()
        r["verified"] = r["verifier_code"] == code
    except Exception as e:
        print("fail", r["id"], str(e)[:100], flush=True)

with ThreadPoolExecutor(a.workers) as ex:
    list(ex.map(one, todo))
tmp = a.path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
os.replace(tmp, a.path)
print("verified now:", sum(r["verified"] for r in rows), "/", len(rows), "still empty:", sum(not r.get("verifier_code") for r in rows))
