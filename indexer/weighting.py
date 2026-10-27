"""tf and idf weighting formulas.

The tf variants weight terms in documents (the build uses them for the vector
lengths, the search for the scores); idf weights the query terms (search.py).
Logarithms are base 10.
"""

import math

# idf methods; df = number of documents containing the term, N = all documents.
#   classic  log10(N / df)       standard idf; 0 for a term in every document
#   smooth   log10(1 + N / df)   always positive: a term in every document keeps log10(2)
#   none     1                   no idf, the baseline that shows what idf changes
IDF_METHODS = ("classic", "smooth", "none")

# tf variants for a term that occurs tf times in a document.
#   log      1 + log10(tf)                        20 occurrences are not 20x stronger than one
#   raw      tf                                   natural term frequency
#   maxnorm  a + (1 - a) * tf / max_tf(d), a=0.5  tf relative to the most frequent term of the document
TF_METHODS = ("log", "raw", "maxnorm")
MAXNORM_ALPHA = 0.5


def idf(method, df, n):
    """Inverse document frequency of a term with document frequency df among n documents."""
    if method == "classic":
        return math.log10(n / df)
    if method == "smooth":
        return math.log10(1 + n / df)
    if method == "none":
        return 1.0
    raise ValueError("unknown idf method: {}".format(method))


def tf_weight(method, tf, max_tf):
    """Weight of a term occurring tf times in a document whose most frequent term occurs max_tf times."""
    if tf <= 0:
        return 0.0
    if method == "log":
        return 1 + math.log10(tf)
    if method == "raw":
        return float(tf)
    if method == "maxnorm":
        return MAXNORM_ALPHA + (1 - MAXNORM_ALPHA) * tf / max_tf
    raise ValueError("unknown tf method: {}".format(method))
