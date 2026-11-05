"""Note text handling: tokenisation, clinical-abbreviation expansion, diagnosis-section extraction."""
import re
import unicodedata

# General clinical shorthand (not tuned to the dev notes). Expansions are appended, never replace the original.
ABBR = {
    "htn": "hypertension", "dm": "diabetes mellitus", "t2dm": "type 2 diabetes mellitus", "t1dm": "type 1 diabetes mellitus",
    "dm2": "type 2 diabetes mellitus", "dm1": "type 1 diabetes mellitus", "gdm": "gestational diabetes mellitus",
    "oa": "osteoarthritis", "ra": "rheumatoid arthritis", "uti": "urinary tract infection", "urti": "upper respiratory tract infection",
    "lrti": "lower respiratory tract infection", "cap": "community acquired pneumonia", "copd": "chronic obstructive pulmonary disease",
    "aecopd": "acute exacerbation chronic obstructive pulmonary disease", "dvt": "deep vein thrombosis", "pe": "pulmonary embolism",
    "gerd": "gastro-oesophageal reflux disease", "gord": "gastro-oesophageal reflux disease", "pud": "peptic ulcer disease",
    "pid": "pelvic inflammatory disease", "bph": "benign prostatic hyperplasia", "ccf": "congestive cardiac heart failure",
    "chf": "congestive heart failure", "hf": "heart failure", "af": "atrial fibrillation", "afib": "atrial fibrillation",
    "mi": "myocardial infarction", "stemi": "st elevation myocardial infarction", "nstemi": "non st elevation myocardial infarction",
    "acs": "acute coronary syndrome", "ihd": "ischaemic heart disease", "cad": "coronary artery disease", "cva": "stroke cerebrovascular",
    "tia": "transient ischaemic attack", "ckd": "chronic kidney disease", "aki": "acute kidney injury", "ptb": "pulmonary tuberculosis",
    "tb": "tuberculosis", "hiv": "human immunodeficiency virus hiv", "aids": "acquired immunodeficiency syndrome",
    "sti": "sexually transmitted infection", "std": "sexually transmitted disease", "bv": "bacterial vaginosis",
    "vvc": "vulvovaginal candidiasis", "ibs": "irritable bowel syndrome", "ibd": "inflammatory bowel disease",
    "age": "acute gastroenteritis", "aom": "acute otitis media", "ome": "otitis media with effusion", "om": "otitis media",
    "osa": "obstructive sleep apnoea", "mdd": "major depressive disorder depression", "gad": "generalised anxiety disorder",
    "ptsd": "post traumatic stress disorder", "adhd": "attention deficit hyperactivity disorder", "asd": "autism spectrum disorder",
    "ocd": "obsessive compulsive disorder", "sle": "systemic lupus erythematosus", "lbp": "low back pain", "ida": "iron deficiency anaemia",
    "sam": "severe acute malnutrition", "mam": "moderate acute malnutrition", "anc": "antenatal care pregnancy",
    "pih": "pregnancy induced hypertension", "pet": "pre-eclampsia", "aph": "antepartum haemorrhage", "pph": "postpartum haemorrhage",
    "prom": "premature rupture of membranes", "iugr": "intrauterine growth restriction", "ectopic": "ectopic pregnancy",
    "bppv": "benign paroxysmal positional vertigo", "migraine": "migraine", "ttc": "tension type headache",
    "tth": "tension type headache", "bcc": "basal cell carcinoma", "scc": "squamous cell carcinoma", "ca": "carcinoma cancer",
    "ugib": "upper gastrointestinal bleeding", "lgib": "lower gastrointestinal bleeding", "sob": "shortness of breath",
    "cp": "chest pain", "dka": "diabetic ketoacidosis", "hhs": "hyperosmolar hyperglycaemic state", "hypo": "hypoglycaemia",
    "pcos": "polycystic ovary syndrome", "aub": "abnormal uterine bleeding", "fibroids": "uterine leiomyoma fibroids",
    "nafld": "non alcoholic fatty liver disease", "masld": "metabolic dysfunction associated steatotic liver disease",
    "hbv": "hepatitis b", "hcv": "hepatitis c", "rhd": "rheumatic heart disease", "scd": "sickle cell disease",
    "vte": "venous thromboembolism", "pvd": "peripheral vascular disease", "pad": "peripheral arterial disease",
    "mrsa": "methicillin resistant staphylococcus aureus", "ards": "acute respiratory distress syndrome",
    "rti": "respiratory tract infection", "ent": "ear nose throat", "fb": "foreign body", "rta": "road traffic accident injury",
    "ssti": "skin and soft tissue infection", "hfmd": "hand foot and mouth disease", "conj": "conjunctivitis",
    "lmp": "", "bs": "blood smear", "mps": "malaria parasites", "mrdt": "malaria rapid diagnostic test", "rdt": "rapid diagnostic test",
    "ugs": "", "mcs": "microscopy culture sensitivity", "fbc": "full blood count", "cbc": "complete blood count",
    "esr": "", "crp": "", "rbs": "random blood sugar", "fbs": "fasting blood sugar", "hba1c": "glycated haemoglobin",
    "ecg": "", "cxr": "chest x-ray", "usg": "ultrasound", "u/e": "", "lft": "", "tft": "thyroid function",
    "nsaid": "", "ppi": "", "ors": "", "bd": "", "tds": "", "od": "", "prn": "", "stat": "",
}
SECTION = re.compile(
    r"(?im)^\s*(?:a|a/p|ass(?:essment)?|imp(?:ression)?|dx|ddx|diag(?:nosis|nosis/es)?|diagnoses|final diagnosis|"
    r"working diagnosis|conclusion|diagn[oó]stico|diagnostic|diagnose|impress[aã]o|impresi[oó]n|utambuzi|tathmini|"
    r"tashkhisi|valutazione|befund|beurteilung|tanı|tani|диагноз|заключение|诊断|印象|التشخيص|chẩn đoán|kesan|"
    r"diagnosa|निदान|ምርመራ)\s*[:\-–.]\s*(.+)$")
DOC_TURN = re.compile(r"(?im)^\s*(?:doctor|dr|clinician|médico|medico|médecin|daktari|arzt|врач|医生|الطبيب|bác sĩ|doktor)\s*:\s*(.+)$")
DX_CUE = re.compile(r"(?i)\b(this is|this looks like|looks like|you have|consistent with|in keeping with|diagnos\w*|"
                    r"so it'?s|it'?s an?|we'?re dealing with|impression|likely|probably|confirms?|due to)\b")


def fold(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
STOP = set("""a an the and or of in on at to for with without by from as is are was were be been being this that these those
it its into not no nor but if then than so such other others specified unspecified due type nos which who whom whose
de la le les des du et ou en el los las y o del por para con sin una un uno al da do das dos e em na no os as com sem
der die das und oder mit ohne von im zu ein eine""".split())


def tokens(text):
    """Lowercased, accent-folded word tokens; CJK runs become character bigrams."""
    out = []
    for w in _WORD.findall(fold(text)):
        if _CJK.search(w):
            chars = [c for c in w]
            out.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
            out.extend(chars)
        elif w not in STOP and (len(w) > 1 or w.isdigit()):
            out.append(w)
    return out


def expand(text):
    """Append expansions of known abbreviations (keeps the original text)."""
    extra = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9/]*", text):
        e = ABBR.get(w.lower())
        if e:
            extra.append(e)
    return text + ("\n" + " ".join(extra) if extra else "")


def diagnosis_text(text):
    """Best guess at the clinician's stated diagnosis: labelled sections, else doctor turns with diagnostic cues."""
    hits = [m.group(1).strip() for m in SECTION.finditer(text)]
    if hits:
        return " ; ".join(hits)
    turns = [m.group(1) for m in DOC_TURN.finditer(text)]
    if turns:
        cued = []
        for t in turns:
            for sent in re.split(r"(?<=[.!?])\s+", t):
                if DX_CUE.search(sent):
                    cued.append(sent)
        if cued:
            return " ".join(cued)
    # short notes: 'Dx'/'Imp' inline (e.g. "... Dx viral URTI, malaria excluded.")
    m = re.findall(r"(?i)\b(?:dx|imp|impression|diagnosis|assessment)\b\s*[:\-–]?\s*([^.;\n]+)", text)
    return " ; ".join(m)
