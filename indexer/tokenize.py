"""Regex tokenizer shared by the indexer and the search.

Documents and queries must be split by the same function, otherwise a query
term would never meet its postings list. A term is the lowercased word as it is
written: no lemmatisation and no stemming. The optional plural folding is a
tiny rule list that is used only when the index is built with --fold-plurals.
"""

import os
import re
import unicodedata

# [^\W\d_] is any Unicode letter, so accented letters stay inside a term while symbols such as the
# hybrid sign "×" split terms. A hyphen joins only parts that start with a letter: "semi-evergreen"
# is one term (so "evergreen" does not match it), while ranges such as "5-8 ft" split into numbers.
# A decimal point counts only between digits, so the full stop in "ft." is not part of a term.
TOKEN_RE = re.compile(r"""
    \d+(?:,\d{3})*(?:\.\d+)?[^\W_]*       # number: 5, 1.5, 1,360; may end in letters: 7a (zone), 18th
  | [^\W\d_][^\W_]*(?:-[^\W\d_][^\W_]*)*  # word starting with a letter, hyphen parts kept: uva-ursi
""", re.VERBOSE)

STOPWORDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stopwords_en.txt")


def load_stopwords(path=STOPWORDS_PATH):
    """Stop words from a file with one word per line; blank lines and # comments are skipped."""
    with open(path, encoding="utf-8") as handle:
        return frozenset(line.strip() for line in handle if line.strip() and not line.startswith("#"))


STOPWORDS = load_stopwords()

# Plurals in -ves are irregular (leaves -> leaf, but olives -> olive), so they
# are listed instead of ruled; species and series are the same in both numbers.
IRREGULAR_PLURALS = {
    "leaves": "leaf", "halves": "half", "calves": "calf", "wolves": "wolf",
    "knives": "knife", "shelves": "shelf", "loaves": "loaf",
    "species": "species", "series": "series",
}
# grasses -> grass, bushes -> bush, branches -> branch, boxes -> box
ES_PLURAL_ENDINGS = ("sses", "shes", "ches", "xes")
# Singular words that end in "s": grass, quercus, sylvestris, iris.
SINGULAR_S_ENDINGS = ("ss", "us", "is")


def fold_plural(term):
    """Regular English plural -> singular: trees -> tree, berries -> berry, leaves -> leaf."""
    if term in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[term]
    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    if term.endswith(ES_PLURAL_ENDINGS):
        return term[:-2]
    if len(term) > 3 and term.endswith("s") and not term.endswith(SINGULAR_S_ENDINGS):
        return term[:-1]
    return term


def words(text):
    """All regex tokens of a text, lowercased, before any filtering."""
    # NFKC turns compatibility characters (ligatures, full-width letters,
    # superscript digits) into their plain form before matching.
    text = unicodedata.normalize("NFKC", text).lower()
    # Only numbers can contain a comma, and there it is a thousands separator.
    return [match.group(0).replace(",", "") for match in TOKEN_RE.finditer(text)]


def terms(tokens, fold_plurals=False, stopwords=STOPWORDS):
    """Index terms from raw tokens: stop words and one-letter tokens are dropped.

    A single letter is a leftover ("children's" -> "s", "e.g.", the hybrid "x"); single digits stay ("5 ft").
    """
    result = []
    for token in tokens:
        if token in stopwords or (len(token) == 1 and not token.isdigit()):
            continue
        result.append(fold_plural(token) if fold_plurals else token)
    return result


def tokenize(text, fold_plurals=False):
    """Text -> list of index terms (the same function is used for queries)."""
    return terms(words(text), fold_plurals)
