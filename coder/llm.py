"""Keyed path: two small LLM calls per note on top of the lexical ranker.

  1. extract  - read the note (any language, any style) -> main diagnosis in English + the qualifiers ICD-11
                cares about (site, laterality, organism, acuity, severity, complication, pregnancy, age group).
  2. choose   - retrieval runs on that English text; the model picks up to 3 codes from the candidate list,
                which includes each candidate's family (parent, siblings, '.Z'), so specificity is a visible choice.

Robustness rules (graded box: OpenAI/Anthropic only, via HTTPS_PROXY, $6 cap, 60 min):
  * provider chosen from whichever key is present; any per-note failure keeps the no-key answer;
  * a $ budget tracker stops new calls before the cap; a wall-clock guard stops new notes after CODER_DEADLINE_S;
  * every returned code is validated against the MMS list and forced to a leaf.
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .kb import softmax_top

DEADLINE_S = float(os.environ.get("CODER_DEADLINE_S", 45 * 60))
BUDGET_USD = float(os.environ.get("CODER_BUDGET_USD", 5.0))
WORKERS = int(os.environ.get("CODER_WORKERS", 8))
N_CAND = int(os.environ.get("CODER_N_CAND", 40))
BREAKER = int(os.environ.get("CODER_BREAKER", 16))  # consecutive-from-start failures before giving up

# $ per 1M tokens (input, output), standard tier, checked 2026-11-05 (Anthropic model list; OpenAI pricing page).
# Unknown models are charged at (5, 25) so the budget guard errs on the safe side.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
}

SYSTEM = """You are an expert clinical coder for ICD-11 MMS (2026-01). Notes come from outpatient clinics and can be
typed SOAP notes, one-line consults, or ambient-scribe transcripts, in any language. Be precise and terse."""

EXTRACT = """Read this clinical note and identify the MAIN condition that the visit should be coded for (the
clinician's final assessment/diagnosis; if none is stated, the most specific supported problem, symptom, or reason for
encounter such as a routine check or antenatal visit).

Return JSON:
{{"language": "<language of the note>",
  "main": "<main diagnosis in standard English medical terms, as specific as the note supports>",
  "qualifiers": "<only what the note states: acute/chronic, severity, site, laterality, organism/test result,
                 complication or 'uncomplicated', exacerbation, stage, pregnancy/trimester, patient age group>",
  "synonyms": ["<2-4 alternative English phrasings / ICD-style names for the main diagnosis>"],
  "others": ["<other diagnoses explicitly made in the note, English, if any>"]}}

NOTE:
{note}"""

CHOOSE = """Choose ICD-11 MMS codes for this note.

Rules:
- Code the MAIN condition of the visit. Return up to 3 codes, best first; codes 2-3 are your next most likely answers
  (e.g. the sibling with more/less specificity, or another stated diagnosis).
- Use the MOST SPECIFIC code the note supports. If the note lacks the detail that a specific child needs, use the
  '.Z' / 'unspecified' code of that family rather than guessing a specific child.
- Avoid '.Y' ('other specified') unless the note names a specific type that none of the listed siblings cover.
- Never return a code marked [parent]; choose one of its leaves.
- A condition during pregnancy/childbirth goes to the pregnancy chapter (JA-JB) when such a code exists; a routine
  antenatal or check-up visit without disease goes to the 'factors influencing health status' codes (Q...).
- Prefer codes from the candidate list. Only if none fits may you give another ICD-11 MMS code you are sure of.

Extracted: {extract}

NOTE:
{note}

CANDIDATES (code | title | some index terms):
{cands}

Return JSON: {{"codes": ["<code1>", "<code2>", "<code3>"]}}"""

SCHEMA_EXTRACT = {
    "type": "object",
    "properties": {"language": {"type": "string"}, "main": {"type": "string"}, "qualifiers": {"type": "string"},
                   "synonyms": {"type": "array", "items": {"type": "string"}},
                   "others": {"type": "array", "items": {"type": "string"}}},
    "required": ["language", "main", "qualifiers", "synonyms", "others"], "additionalProperties": False}
SCHEMA_CHOOSE = {
    "type": "object", "properties": {"codes": {"type": "array", "items": {"type": "string"}}},
    "required": ["codes"], "additionalProperties": False}


def parse_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except Exception:
                pass
    return {}


class Budget:
    """Spend tracker. Each call first reserves its worst case (estimated input + the max_tokens cap), so parallel
    workers cannot jointly overshoot the limit; the reservation is replaced by the billed usage when the call ends."""

    def __init__(self, limit):
        self.limit, self.spent, self.reserved, self.lock = limit, 0.0, 0.0, threading.Lock()
        self.calls, self.tin, self.tout = 0, 0, 0

    @staticmethod
    def cost(model, tin, tout):
        pin, pout = PRICES.get(model, (5.0, 25.0))
        return (tin * pin + tout * pout) / 1e6

    def reserve(self, model, prompt, max_tokens):
        c = self.cost(model, len(prompt) // 3 + 200, max_tokens)  # ~3 chars/token errs high for the input
        with self.lock:
            if self.spent + self.reserved + c > self.limit:
                return None
            self.reserved += c
            return c

    def release(self, held):
        with self.lock:
            self.reserved -= held

    def add(self, model, tin, tout, held=0.0):
        with self.lock:
            self.reserved -= held
            self.calls += 1
            self.tin += tin
            self.tout += tout
            self.spent += self.cost(model, tin, tout)

    def ok(self):
        return self.spent + self.reserved < self.limit


# ---------------------------------------------------------------- providers
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model=None):
        import anthropic
        self.model = model or os.environ.get("CODER_ANTHROPIC_MODEL", "claude-haiku-5-5")
        self.client = anthropic.Anthropic(timeout=anthropic.Timeout(60.0, connect=10.0), max_retries=2)
        self.structured = True  # set False once the API rejects output_config; checked per call (thread-safe enough)

    def complete(self, user, schema, effort="low", max_tokens=3000):
        kw = dict(model=self.model, max_tokens=max_tokens, system=SYSTEM,
                  messages=[{"role": "user", "content": user}])
        if self.structured:
            kw["output_config"] = {"effort": effort, "format": {"type": "json_schema", "schema": schema}}
        try:
            r = self.client.messages.create(**kw)
        except Exception as e:  # older API surface / model without structured output: retry plain
            if "output_config" not in kw or ("output_config" not in str(e) and "format" not in str(e)):
                raise
            self.structured = False
            kw.pop("output_config")
            r = self.client.messages.create(**kw)
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, self.model, r.usage.input_tokens, r.usage.output_tokens


class OpenAIProvider:
    name = "openai"

    def __init__(self, model=None):
        import openai
        self.model = model or os.environ.get("CODER_OPENAI_MODEL", "gpt-5-mini")
        self.client = openai.OpenAI(timeout=openai.Timeout(60.0, connect=10.0), max_retries=2)
        self.reasoning = True

    def complete(self, user, schema, effort="low", max_tokens=3000):
        kw = dict(model=self.model, max_completion_tokens=max_tokens,
                  messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                  response_format={"type": "json_object"})
        if self.reasoning:
            kw["reasoning_effort"] = effort
        try:
            r = self.client.chat.completions.create(**kw)
        except Exception as e:
            if "reasoning_effort" in kw and "reasoning" in str(e):
                self.reasoning = False
                kw.pop("reasoning_effort")
                r = self.client.chat.completions.create(**kw)
            else:
                raise
        u = r.usage
        return r.choices[0].message.content, self.model, u.prompt_tokens, u.completion_tokens


def pick_provider():
    """Anthropic if its key is set (cheapest strong option), else OpenAI, else None. CODER_PROVIDER overrides."""
    want = os.environ.get("CODER_PROVIDER", "").lower()
    order = [want] if want else ["anthropic", "openai"]
    for name in order:
        try:
            if name == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
                return AnthropicProvider()
            if name == "openai" and os.environ.get("OPENAI_API_KEY"):
                return OpenAIProvider()
        except Exception as e:
            print(f"[llm] provider {name} unavailable: {e!r}", file=sys.stderr)
    return None


# ---------------------------------------------------------------- pipeline
def candidates(kb, ranker, text, ext, n=N_CAND):
    """Union of: ranking on the LLM's English diagnosis, ranking on the raw note, and the families of the leaders."""
    dx = " ; ".join([ext.get("main", ""), ext.get("qualifiers", ""), *ext.get("synonyms", [])])
    s_en = ranker.scores(text + "\n" + dx, dx=dx)
    s_raw = ranker.scores(text)
    order = []
    for i in list(softmax_top(s_en, n)) + list(softmax_top(s_raw, n // 3)):
        if i not in order:
            order.append(i)
    fam = []
    for i in order[:8]:
        for j in kb.family(kb.codes[i]["c"]):
            if j not in order and j not in fam:
                fam.append(j)
    for o in ext.get("others", [])[:2]:
        for i in softmax_top(ranker.scores(o, dx=o), 4):
            if i not in order and i not in fam:
                fam.append(i)
    return order + fam


def format_cands(kb, idxs, term_index):
    lines = []
    for i in idxs:
        c = kb.codes[i]
        tag = "" if c["leaf"] else " [parent]"
        syn = term_index.get(i, [])[:3]
        lines.append(f"{c['c']}{tag} | {c['t']}" + (f" | {'; '.join(syn)}" if syn else ""))
    return "\n".join(lines)


def to_leaf(kb, code, scores=None):
    """Map any valid code to a leaf: itself if leaf, else its '.Z' child, else its best-scored leaf child."""
    if code not in kb.by_code:
        return None
    i = kb.by_code[code]
    for _ in range(4):
        if kb.codes[i]["leaf"]:
            return kb.codes[i]["c"]
        kids = kb.children.get(i, [])
        if not kids:
            return None
        z = [k for k in kids if kb.codes[k]["c"].endswith("Z")]
        i = z[0] if z else (max(kids, key=lambda k: scores[k]) if scores is not None else kids[0])
    return kb.codes[i]["c"] if kb.codes[i]["leaf"] else None


def norm_code(c):
    return re.split(r"[&/]", str(c).strip().upper())[0].strip()


def call(provider, budget, prompt, schema, effort, max_tokens):
    held = budget.reserve(provider.model, SYSTEM + prompt, max_tokens)
    if held is None:
        raise RuntimeError("budget")
    try:
        t, m, i, o = provider.complete(prompt, schema, effort=effort, max_tokens=max_tokens)
    except Exception:
        budget.release(held)
        raise
    budget.add(m, i, o, held)
    return t, m, i, o


def code_note(provider, budget, kb, ranker, text, term_index, base):
    t, m, i, o = call(provider, budget, EXTRACT.format(note=text[:6000]), SCHEMA_EXTRACT, "low", 1500)
    ext = parse_json(t)
    if not isinstance(ext, dict):
        ext = {}
    ext = {k: ext.get(k) for k in ("language", "main", "qualifiers", "synonyms", "others")}
    ext["synonyms"] = [s for s in (ext.get("synonyms") or []) if isinstance(s, str)][:4]
    ext["others"] = [s for s in (ext.get("others") or []) if isinstance(s, str)][:3]
    ext["main"], ext["qualifiers"] = str(ext.get("main") or ""), str(ext.get("qualifiers") or "")
    idxs = candidates(kb, ranker, text, ext)
    prompt = CHOOSE.format(extract=json.dumps(ext, ensure_ascii=False), note=text[:6000],
                           cands=format_cands(kb, idxs, term_index))
    t, m, i, o = call(provider, budget, prompt, SCHEMA_CHOOSE, "medium", 4000)
    raw = parse_json(t).get("codes", []) if isinstance(parse_json(t), dict) else []
    scores = ranker.scores(text)
    out = []
    for c in raw[:5]:
        leaf = to_leaf(kb, norm_code(c), scores)
        if leaf and leaf not in out:
            out.append(leaf)
    for c in base:  # fill to 3 from the no-key ranking
        if len(out) >= 3:
            break
        if c not in out:
            out.append(c)
    return out[:3], ext


def build_term_index(kb, per_code=3):
    """A few English index terms per code to show the LLM (helps it map lay/clinical wording to titles)."""
    idx = {}
    for (ci, text, lang, kind) in kb.terms:
        if lang == "en" and kind in ("index", "incl") and text.lower() != kb.codes[ci]["t"].lower():
            lst = idx.setdefault(ci, [])
            if len(lst) < per_code:
                lst.append(text)
    return idx


def run_llm(notes, ids, kb, ranker, base, writer, t_start, provider=None, log=None):
    provider = provider or pick_provider()
    if provider is None:
        print("[llm] no API key found: keeping no-key predictions", file=sys.stderr)
        return None
    budget = Budget(BUDGET_USD)
    term_index = build_term_index(kb)
    print(f"[llm] provider={provider.name} model={provider.model} workers={WORKERS}", file=sys.stderr)
    fails = 0
    state = {"ok": 0, "err": 0}
    lock = threading.Lock()

    def work(n, nid):
        if time.time() - t_start > DEADLINE_S:
            return nid, None, "deadline"
        with lock:  # circuit breaker: provider unreachable / key invalid -> stop trying, keep no-key answers
            if state["ok"] == 0 and state["err"] >= BREAKER:
                return nid, None, "breaker"
        try:
            codes, ext = code_note(provider, budget, kb, ranker, str(n.get("text") or ""), term_index, base[nid])
            with lock:
                state["ok"] += 1
            return nid, codes, ext
        except Exception as e:
            with lock:
                state["err"] += 1
            return nid, None, repr(e)[:200]

    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(work, n, nid) for n, nid in zip(notes, ids)]
        for k, f in enumerate(as_completed(futs), 1):
            nid, codes, info = f.result()
            if codes:
                writer.set(nid, codes)
            else:
                fails += 1
                if fails <= 5 or fails % 50 == 0:
                    print(f"[llm] {nid}: kept no-key answer ({info})", file=sys.stderr)
            if log is not None:
                log.append({"id": nid, "codes": codes, "info": info})
            if k % 50 == 0:
                print(f"[llm] {k}/{len(ids)} ${budget.spent:.3f} {time.time() - t_start:.0f}s", file=sys.stderr)
    print(f"[llm] done: calls={budget.calls} in={budget.tin} out={budget.tout} est=${budget.spent:.3f} "
          f"fails={fails}", file=sys.stderr)
    return budget
