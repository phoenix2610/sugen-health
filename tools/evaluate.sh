#!/usr/bin/env bash
# Score the no-key path (or a given prediction dir) on dev + synthetic sets with the official scorer.
# usage: tools/evaluate.sh            -> runs python -m coder (whatever keys are in env) on each set
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
mkdir -p cache/eval
cat eval/synth_core.jsonl eval/synth_general.jsonl > cache/eval/synth_all.jsonl
for set in problem/data/dev_notes.jsonl cache/eval/synth_all.jsonl; do
  name=$(basename "$set" .jsonl)
  $PY -m coder "$set" "cache/eval/$name.pred.jsonl" 2>/dev/null
  echo "== $name"
  python3 problem/score.py --gold "$set" --pred "cache/eval/$name.pred.jsonl" --mms problem/data/mms-2026-01.json | grep -E 'slice|SCORE'
done
