"""Generate a synthetic evaluation set with Gemini (development only).

Two slices, mirroring the brief:
  core     -> same clinics/styles as the dev set (East-African outpatient, English, the 3 dev styles),
              chapters weighted like the dev gold codes.
  general  -> every chapter, many settings, ~half non-English (incl. code-mixed), extra styles.

Gold-label hygiene:
  * the writer model picks a leaf code from a random slice of one chapter, and is shown that code's
    siblings so the note carries exactly the detail that separates it from them (or lacks it, for .Z);
  * it is told not to copy the ICD title wording;
  * a second, different model re-codes the note blind against the sibling family; disagreements are kept
    but flagged (verified=false) so we can report both numbers.

Usage: python3 tools/gen_synth.py core 150 eval/synth_core.jsonl
       python3 tools/gen_synth.py general 300 eval/synth_general.jsonl
"""
import json
import os
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
from gemini import generate  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
MMS = json.load(open(os.path.join(ROOT, "problem", "data", "mms-2026-01.json")))
DEV = [json.loads(l) for l in open(os.path.join(ROOT, "problem", "data", "dev_notes.jsonl"))]
LEAF = [r for r in MMS if r["leaf"]]
BY_CODE = {r["code"]: r for r in MMS}
BY_CH = {}
for r in LEAF:
    BY_CH.setdefault(r["chapter"], []).append(r)

CORE_CH = {"01": 14, "12": 8, "13": 8, "16": 8, "05": 7, "11": 6, "18": 5, "14": 4, "15": 3,
           "04": 2, "24": 2, "06": 2, "09": 2, "08": 2, "10": 1, "22": 3, "21": 2}
GEN_CH = {c: 4 for c in BY_CH}
GEN_CH.update({"25": 1, "26": 1, "23": 1, "20": 2, "02": 3, "17": 2, "07": 3})

STYLES_CORE = ["typed_consult", "typed_consult", "short_consult", "ambient_transcript"]
STYLES_GEN = STYLES_CORE + ["referral_letter", "discharge_summary", "triage_note", "telehealth_message"]
LANGS_GEN = (["English"] * 10 + ["French", "Spanish", "Portuguese", "Swahili", "Swahili-English code-mixed",
             "Hindi-English code-mixed (romanised Hinglish)", "Arabic", "German", "Mandarin Chinese",
             "Russian", "Amharic", "Turkish", "Italian", "Indonesian", "Vietnamese"])
SETTINGS_GEN = ["a general practice in the UK", "an urban outpatient clinic in Kenya", "a district hospital OPD in India",
                "an emergency department in Brazil", "a family medicine clinic in Canada", "a rural health centre in Uganda",
                "a specialist outpatient clinic in Germany", "a paediatric clinic in Nigeria", "a psychiatry clinic in Spain",
                "an urgent care centre in the USA", "an antenatal clinic in Tanzania", "a dermatology clinic in France",
                "an occupational health clinic in the UAE", "a community clinic in the Philippines"]


def family(code):
    """The code, its parent-ish stem and siblings (used to show the writer what distinguishes it)."""
    stem = code.split(".")[0]
    if "." in code:
        tail = code.split(".")[1]
        pref = stem + "." + tail[:-1] if len(tail) > 1 else stem + "."
    else:
        pref = code[:-1]
    sib = [r for r in MMS if r["code"].startswith(pref) and r["code"] != code][:25]
    return sib


STYLE_HINT = {
    "typed_consult": "a typed SOAP-style consult note (S:/O:/Ix:/A:/P:), clinical shorthand, 60-160 words",
    "short_consult": "a very short one-to-three line consult note with abbreviations (e.g. 'c/o', 'x3/7', 'Dx')",
    "ambient_transcript": "an ambient-scribe transcript of the consultation as 'Doctor:' / 'Patient:' turns, 8-16 turns, "
                          "with the clinician's impression stated near the end as speech",
    "referral_letter": "a brief referral letter from one clinician to another",
    "discharge_summary": "a short discharge/visit summary",
    "triage_note": "a terse triage/nursing + doctor note",
    "telehealth_message": "a telehealth consult written up by the clinician after a video/phone call",
}


def make_prompt(slice_, rng):
    if slice_ == "core":
        ch = rng.choices(list(CORE_CH), weights=list(CORE_CH.values()))[0]
        style, lang = rng.choice(STYLES_CORE), "English"
        setting = "an outpatient clinic in East Africa (Kenya/Uganda/Tanzania): local context, generic drug names " \
                  "or local brands, rapid tests, cost-conscious investigations"
        ex = rng.sample([d for d in DEV if d["style"] == style] or DEV, 2)
    else:
        ch = rng.choices(list(GEN_CH), weights=list(GEN_CH.values()))[0]
        style, lang, setting = rng.choice(STYLES_GEN), rng.choice(LANGS_GEN), rng.choice(SETTINGS_GEN)
        ex = rng.sample(DEV, 2)
    pool = BY_CH[ch]
    cands = rng.sample(pool, min(120, len(pool)))
    cand_txt = "\n".join(f"{r['code']}\t{r['title']}" for r in cands)
    want_z = rng.random() < 0.25
    examples = "\n\n".join(f"EXAMPLE ({d['style']}):\n{d['text']}" for d in ex)
    prompt = f"""You are helping build an evaluation set for an ICD-11 coding system. Write ONE realistic clinical note.

Setting: {setting}.
Style: {STYLE_HINT[style]}.
Language of the note: {lang}. (Write the whole note in this language as a clinician there really would; keep standard
drug names/abbreviations as locals do.)

Pick ONE code from the candidate list below that would plausibly be the main diagnosis of a visit in this setting
(prefer something a real clinic would actually see; skip absurd picks). {"Prefer an '.Z' / 'unspecified' code if one fits: then the note must NOT contain the detail that would allow a more specific sibling." if want_z else "The note must contain the clinical detail that makes this code (not its parent or a sibling) the most specific correct one."}

Rules:
- Do NOT copy the ICD title wording verbatim; write like a busy clinician (abbreviations, lay patient words, partial info).
- Include realistic vitals/exam/tests/plan as the style allows. No headings like 'ICD code'. Never mention any code.
- One main diagnosis; incidental history is fine but must not be codable as the main problem.

Candidate codes (chapter {ch}):
{cand_txt}

Style examples from the real clinics (for tone only; do not reuse their diagnoses):
{examples}

Return JSON: {{"code": "<chosen code>", "note": "<the note>"}}"""
    return prompt, ch, style, lang


VERIFY = """You are a certified ICD-11 coder. Read the clinical note and choose the single most specific ICD-11 MMS code
from the list that the note supports. Use an 'unspecified' (.Z) code only when the note lacks the detail for a specific one.
Return JSON {{"code": "<code>"}}.

NOTE:
{note}

OPTIONS:
{opts}"""


def one(slice_, i, seed, lock, out):
    rng = random.Random(seed)
    for attempt in range(4):
        prompt, ch, style, lang = make_prompt(slice_, rng)
        try:
            txt, _ = generate(prompt, model="gemini-3.1-flash-lite", temperature=1.0, json_mode=True,
                              fallbacks=("gemini-flash-lite-latest", "gemini-3-flash-preview"))
            j = json.loads(txt)
            code, note = j["code"].strip(), j["note"].strip()
        except Exception as e:
            print("gen fail", i, e, flush=True)
            continue
        if code not in BY_CODE or not BY_CODE[code]["leaf"] or len(note) < 30:
            continue
        if re.search(re.escape(code), note):
            continue
        fam = [BY_CODE[code]] + family(code)
        rng.shuffle(fam)
        opts = "\n".join(f"{r['code']}\t{r['title']}" for r in fam)
        try:
            vt, _ = generate(VERIFY.format(note=note, opts=opts), model="gemini-3.5-flash-lite", temperature=0, fallbacks=("gemini-flash-lite-latest", "gemini-3-flash-preview"),
                             json_mode=True)
            vcode = json.loads(vt).get("code", "").strip()
        except Exception:
            vcode = ""
        row = {"id": f"syn-{slice_}-{i:04d}", "text": note, "gold": [code], "style": style, "lang": lang,
               "chapter": ch, "slice": "A" if slice_ == "core" else "B", "verified": vcode == code,
               "verifier_code": vcode}
        with lock:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
        return
    print("gave up", i, flush=True)


def main():
    slice_, n, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    have = set()
    if os.path.exists(path):
        have = {json.loads(l)["id"] for l in open(path, encoding="utf-8")}
    lock = threading.Lock()
    with open(path, "a", encoding="utf-8") as out, ThreadPoolExecutor(4) as ex:
        for i in range(n):
            if f"syn-{slice_}-{i:04d}" not in have:
                ex.submit(one, slice_, i, 1000 * (slice_ == "general") + i, lock, out)
    print("done", path, flush=True)


if __name__ == "__main__":
    main()
