"""No-key path: lexical retrieval over WHO terms -> ranked leaf codes. Also produces candidates for the LLM path."""
import re

import numpy as np

from .kb import KB, softmax_top
from .text import diagnosis_text, expand

W_DX, W_FULL, PARENT_BONUS = 1.0, 0.35, 0.15
Y_PENALTY = 0.6          # '.Y other specified': never gold in dev, rarely decidable from text
GATE_PENALTY = 0.35      # obstetric / perinatal chapters without pregnancy / newborn context

PREGNANT = re.compile(
    r"(?i)(pregnan|antenatal|\banc\b|gravid|\bg\d+\s*p\d+|\d+\s*/\s*40\b|\d+\s*(?:weeks?|wks?)\s*(?:gestation|pregnant|ga)|"
    r"trimester|primigravida|multigravida|postpartum|post-partum|puerper|labou?r|deliver|caesarean|miscarriage|abortion|"
    r"ectopic|embaraz|gestaci|grossesse|enceinte|gravidez|gestante|grávida|mjamzito|ujauzito|schwanger|беремен|妊娠|孕|حامل|حمل|hamile|gebelik)")
NEWBORN = re.compile(
    r"(?i)(newborn|neonat|new-born|\b\d+\s*(?:days?|d)\s*old|days? of life|\bday\s*\d+\s*of life|preterm|premature baby|"
    r"birth ?weight|\bnicu\b|\bnbu\b|recém-nascido|\brn\b|recién nacido|nouveau-né|nouveau né|mtoto mchanga|neugeboren|"
    r"новорожд|新生儿|新生|حديث الولادة|yenidoğan|sơ sinh|\d+\s*ngày tuổi)")


class Ranker:
    def __init__(self, kb: KB):
        self.kb = kb
        self.parent_idx = np.array([kb.by_code[c["p"]] if c["p"] else -1 for c in kb.codes])
        self.has_parent = self.parent_idx >= 0
        self.is_y = np.array([c["res"] and c["c"].endswith("Y") for c in kb.codes])
        self.ch18 = np.array([c["ch"] == "18" for c in kb.codes])
        self.ch19 = np.array([c["ch"] == "19" for c in kb.codes])

    def scores(self, text, dx=None):
        kb = self.kb
        dx = diagnosis_text(text) if dx is None else dx
        s = np.zeros(len(kb.codes), dtype=np.float32)
        if dx.strip():
            s += W_DX * kb.code_scores(kb.term_scores(expand(dx)))
        s += W_FULL * kb.code_scores(kb.term_scores(expand(text)))
        leaf = s.copy()
        leaf[self.has_parent] += PARENT_BONUS * s[self.parent_idx[self.has_parent]]
        leaf[self.is_y] *= Y_PENALTY
        if not PREGNANT.search(text):
            leaf[self.ch18] *= GATE_PENALTY
        if not NEWBORN.search(text):
            leaf[self.ch19] *= GATE_PENALTY
        leaf[~kb.leaf] = -1
        return leaf

    def rank(self, text, k=3, dx=None):
        s = self.scores(text, dx)
        top = softmax_top(s, k)
        return [(self.kb.codes[i]["c"], float(s[i])) for i in top]
