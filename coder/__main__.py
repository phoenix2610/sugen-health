"""Entry point: python -m coder <in.jsonl> <out.jsonl>

Contract (from the brief): every input id gets a line with up to 3 valid MMS codes, best first.
Safety: the no-key answer for every note is computed first and written immediately; the file is then
atomically rewritten as LLM answers arrive, so a hard kill at any moment still leaves a complete file.
"""
import json
import os
import sys
import threading
import time

from .kb import KB
from .nokey import Ranker

FALLBACK_CODE = "MG26"  # 'Fever of other or unknown origin'-style safety net; replaced below if invalid


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


class Writer:
    def __init__(self, path, ids):
        self.path, self.ids, self.preds = path, ids, {}
        self.lock = threading.Lock()
        self.last = 0.0

    def set(self, nid, codes, flush=False):
        with self.lock:
            self.preds[nid] = codes
            if flush or time.time() - self.last > 2.0:
                self._flush()

    def _flush(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for nid in self.ids:
                f.write(json.dumps({"id": nid, "codes": self.preds.get(nid, [])}) + "\n")
        os.replace(tmp, self.path)
        self.last = time.time()

    def flush(self):
        with self.lock:
            self._flush()


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: python -m coder <in.jsonl> <out.jsonl>")
    t0 = time.time()
    inp, out = argv
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    notes = read_jsonl(inp)
    ids = [str(n.get("id")) for n in notes]
    w = Writer(out, ids)
    kb = KB()
    fallback = FALLBACK_CODE if FALLBACK_CODE in kb.valid else next(c["c"] for c in kb.codes if c["leaf"])
    for nid in ids:  # complete (if poor) file before anything else can fail
        w.preds[nid] = [fallback]
    w.flush()

    ranker = Ranker(kb)
    base = {}
    for n, nid in zip(notes, ids):
        try:
            codes = [c for c, _ in ranker.rank(str(n.get("text") or ""), k=3)]
        except Exception as e:  # never lose a note
            print(f"[nokey] {nid}: {e!r}", file=sys.stderr)
            codes = [fallback]
        base[nid] = codes or [fallback]
        w.set(nid, base[nid])
    w.flush()
    print(f"[coder] no-key predictions for {len(ids)} notes in {time.time() - t0:.1f}s", file=sys.stderr)

    try:
        from .llm import run_llm
        run_llm(notes, ids, kb, ranker, base, w, t_start=t0)
    except Exception as e:
        print(f"[coder] LLM stage skipped: {e!r}", file=sys.stderr)
    w.flush()
    print(f"[coder] done in {time.time() - t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
