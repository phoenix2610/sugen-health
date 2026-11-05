"""Knowledge base + lexical retrieval over WHO terms (titles, synonyms, index terms, inclusions, 9 languages)."""
import gzip
import json
import math
import os
from collections import defaultdict

import numpy as np
from scipy import sparse

from .text import tokens

DATA = os.path.join(os.path.dirname(__file__), "data")


class KB:
    def __init__(self, path=os.path.join(DATA, "kb.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
        self.codes = d["codes"]
        self.defs = d.get("defs", {})
        self.by_code = {c["c"]: i for i, c in enumerate(self.codes)}
        self.children = defaultdict(list)
        for i, c in enumerate(self.codes):
            if c["p"]:
                self.children[self.by_code[c["p"]]].append(i)
        self.leaf = np.array([c["leaf"] for c in self.codes])
        self.valid = {c["c"] for c in self.codes}

        terms = list(d["terms"])
        # a residual '.Z' child inherits its parent's terms: "falciparum malaria" with no detail -> 1F40.Z
        by_owner = defaultdict(list)
        for t in terms:
            by_owner[t[0]].append(t)
        for pi, kids in self.children.items():
            z = [k for k in kids if self.codes[k]["c"].endswith("Z") and self.codes[k]["res"]]
            if z:
                for t in by_owner.get(pi, []):
                    terms.append([z[0], t[1], t[2], "inherit"])
        self.terms = terms
        self.term_code = np.array([t[0] for t in terms], dtype=np.int32)
        self.term_kind = [t[3] for t in terms]

        vocab, rows, cols = {}, [], []
        for r, t in enumerate(terms):
            for tok in set(tokens(t[1])):
                j = vocab.setdefault(tok, len(vocab))
                rows.append(r)
                cols.append(j)
        self.vocab = vocab
        n_terms = len(terms)
        df = np.bincount(cols, minlength=len(vocab)).astype(np.float32)
        self.idf = np.log(1 + n_terms / (df + 1)).astype(np.float32)
        data = self.idf[cols]
        self.M = sparse.csr_matrix((data, (rows, cols)), shape=(n_terms, len(vocab)), dtype=np.float32)
        self.term_mass = np.asarray(self.M.sum(axis=1)).ravel() + 1e-6

    def qvec(self, text):
        v = np.zeros(len(self.vocab), dtype=np.float32)
        for tok in set(tokens(text)):
            j = self.vocab.get(tok)
            if j is not None:
                v[j] = 1.0
        return v

    COV_POW = 1.5

    def term_scores(self, text):
        """Per-term score: idf mass of the term's words found in the text, discounted by the share left unmatched.

        matched * coverage^p: a longer term that is mostly matched (more specific) beats a short generic one,
        while unmatched words (claims the note does not support, e.g. 'congenital') cost score."""
        q = self.qvec(text)
        if not q.any():
            return np.zeros(len(self.terms), dtype=np.float32)
        matched = self.M @ q
        cov = matched / self.term_mass
        return matched * cov ** self.COV_POW

    def code_scores(self, term_s):
        """Max over each code's terms."""
        out = np.zeros(len(self.codes), dtype=np.float32)
        np.maximum.at(out, self.term_code, term_s)
        return out

    def leaf_scores(self, code_s, parent_bonus=0.15):
        """Leaves keep their own score plus a small share of their ancestors' (tie-break toward the matched family)."""
        s = code_s.copy()
        for i, c in enumerate(self.codes):
            p = c["p"]
            if p is not None:
                s[i] += parent_bonus * code_s[self.by_code[p]]
        s[~self.leaf] = -1
        return s

    def title(self, code):
        return self.codes[self.by_code[code]]["t"]

    def family(self, code):
        """Parent + siblings + children of a code (for showing the LLM the specificity choices)."""
        i = self.by_code[code]
        c = self.codes[i]
        out = []
        if c["p"]:
            pi = self.by_code[c["p"]]
            out.append(pi)
            out.extend(self.children[pi])
        out.append(i)
        out.extend(self.children[i])
        seen, res = set(), []
        for k in out:
            if k not in seen:
                seen.add(k)
                res.append(k)
        return res


def softmax_top(scores, k):
    idx = np.argpartition(-scores, min(k, len(scores) - 1))[:k]
    return idx[np.argsort(-scores[idx])]


def entropy(p):
    p = p[p > 0]
    return -float((p * np.log(p)).sum()) if len(p) else 0.0


__all__ = ["KB", "softmax_top", "entropy", "math"]
