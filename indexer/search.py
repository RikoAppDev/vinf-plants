"""Ranked search over the inverted index: vector space model with tf-idf and cosine.

Usage:
    python -m indexer.search "frost hardy evergreen shrub clay"
    python -m indexer.search "quercus robur" --idf smooth --tf maxnorm --top 20 --source pfaf

Weights:
    document  w(t, d) = tf_weight(t, d) / length(d)      --tf log | raw | maxnorm
              length(d) = Euclidean length of the tf vector (norms.tsv); --norm none skips the division
    query     w(t, q) = (count of t in the query) * idf(t)   --idf classic | smooth | none
    score     sum over the query terms of w(t, q) * w(t, d)
idf is computed at query time from df and N, so switching --idf needs no rebuild.
A query term that is not in the dictionary is ignored.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

from . import tokenize, weighting

NORMS = ("cosine", "none")


def read_tsv(path):
    """(header, rows) of a TSV file whose first line is the header."""
    with open(path, encoding="utf-8") as handle:
        header = next(handle).rstrip("\n").split("\t")
        return header, [line.rstrip("\n").split("\t") for line in handle]


class Index:
    """The on-disk index, loaded for querying.

    A postings list stays an unparsed string until a query needs it: parsing all of them
    would take far longer than answering the query.
    """

    def __init__(self, index_dir):
        meta_path = os.path.join(index_dir, "meta.json")
        if not os.path.exists(meta_path):
            raise FileNotFoundError("no complete index in {} (run python -m indexer.build)".format(index_dir))
        with open(meta_path, encoding="utf-8") as handle:
            self.meta = json.load(handle)
        self.n = self.meta["N"]

        header, rows = read_tsv(os.path.join(index_dir, "docs.tsv"))
        self.docs = [dict(zip(header, row)) for row in rows]
        self.max_tf = [int(doc["max_tf"]) for doc in self.docs]

        header, rows = read_tsv(os.path.join(index_dir, "norms.tsv"))
        self.norms = {column: [float(row[position]) for row in rows]
                      for position, column in enumerate(header) if column != "doc_id"}

        self.df = {}
        self._raw_postings = {}
        self._parsed_postings = {}
        with open(os.path.join(index_dir, "postings.tsv"), encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                term, df, postings = line.rstrip("\n").split("\t")
                self.df[term] = int(df)
                self._raw_postings[term] = postings

    def postings(self, term):
        """[(doc_id, tf), ...] of a term (empty if unknown); parsed on first use, then cached."""
        if term not in self._parsed_postings:
            parsed = []
            for pair in self._raw_postings.get(term, "").split():
                doc_id, tf = pair.split(":")
                parsed.append((int(doc_id), int(tf)))
            self._parsed_postings[term] = parsed
        return self._parsed_postings[term]

    def query_terms(self, query):
        """Query text -> terms, tokenized with the same options as the documents were."""
        return tokenize.tokenize(query, fold_plurals=self.meta["options"]["fold_plurals"])

    def idf(self, term, method):
        return weighting.idf(method, self.df[term], self.n)

    def rank(self, query, idf_method="classic", tf_method="log", norm="cosine"):
        """(doc_id, score) of every document containing a query term, best first.

        Documents with score 0 stay in, so every idf method ranks the same candidates (compare.py).
        """
        if norm not in NORMS:
            raise ValueError("unknown norm: {}".format(norm))
        # idf weights only the query, documents get tf with Euclidean normalisation;
        # idf on both sides would square its effect.
        counts = Counter(term for term in self.query_terms(query) if term in self.df)
        query_weights = {term: count * self.idf(term, idf_method) for term, count in counts.items()}

        # Term at a time: one accumulator per document met in the postings lists.
        scores = defaultdict(float)
        for term, query_weight in query_weights.items():
            for doc_id, tf in self.postings(term):
                scores[doc_id] += query_weight * weighting.tf_weight(tf_method, tf, self.max_tf[doc_id])

        if norm == "cosine":
            # Only documents are normalised: dividing by the query length would not change the order.
            # A document met in a postings list has length > 0.
            lengths = self.norms[tf_method]
            for doc_id in scores:
                scores[doc_id] /= lengths[doc_id]
        # Ties are broken by doc id, so the order is reproducible.
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def search(index, query, idf_method="classic", tf_method="log", norm="cosine", top=10, source=None):
    """Best documents as (rank, score, doc) triples; a document with score 0 does not match."""
    results = []
    for doc_id, score in index.rank(query, idf_method, tf_method, norm):
        if score <= 0 or len(results) == top:
            break
        doc = index.docs[doc_id]
        if source and doc["source"] != source:
            continue
        results.append((len(results) + 1, score, doc))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ranked tf-idf search over the inverted index")
    parser.add_argument("query")
    parser.add_argument("--idf", choices=weighting.IDF_METHODS, default="classic")
    parser.add_argument("--tf", choices=weighting.TF_METHODS, default="log")
    parser.add_argument("--norm", choices=NORMS, default="cosine")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--source", help="show only documents of this source (idf still counts all sources)")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    index = Index(os.path.join(args.data_dir, "index"))
    loaded = time.perf_counter()
    if args.source and args.source not in index.meta["documents_per_source"]:
        parser.error("unknown source {!r}, indexed: {}".format(
            args.source, ", ".join(index.meta["documents_per_source"])))
    results = search(index, args.query, args.idf, args.tf, args.norm, args.top, args.source)
    finished = time.perf_counter()

    print("index N={}, {} terms, loaded in {:.2f} s, query answered in {:.3f} s".format(
        index.n, len(index.df), loaded - started, finished - loaded))
    print("weights: document tf={} (norm={}), query count x idf={}".format(args.tf, args.norm, args.idf))
    terms = list(dict.fromkeys(index.query_terms(args.query)))  # unique, in query order
    if not terms:
        print("the query has no index terms (only stop words or one-letter tokens)")
    for term in terms:
        if term in index.df:
            print("  {:<20} df={:<6} idf={:.4f}".format(term, index.df[term], index.idf(term, args.idf)))
        else:
            print("  {:<20} not in the dictionary, ignored".format(term))
    if terms and not results:
        print("no matching documents")
    for rank, score, doc in results:
        print("{:>3}  {:.4f}  {:<7} {:<40} {}".format(
            rank, score, doc["source"], doc["scientific_name"][:40], doc["url"]))


if __name__ == "__main__":
    sys.exit(main())
