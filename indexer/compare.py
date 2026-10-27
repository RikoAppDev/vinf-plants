"""Compares the idf methods on fixed queries (material for the report).

Usage:
    python -m indexer.compare
    python -m indexer.compare --tf maxnorm --query "white oak" --query "edible fruit tree"

For every query: df and idf of its terms under each method, the top 5 of each
method side by side, and how much two methods agree on their top 10:
    overlap@10  documents the two top-10 lists share / 10
    Spearman    rank correlation over the union of the two top-10 lists
                (1 = same order, 0 = unrelated, -1 = reversed)
Prints plain text and writes the same tables as markdown to data/index/idf_comparison.md.
"""

import argparse
import itertools
import os
import sys

from . import weighting
from .search import NORMS, Index

QUERIES = (
    "frost hardy evergreen shrub clay soil",
    "quercus robur",
    "edible fruit tree",
    "drought tolerant groundcover full sun",
    "wood density janka hardness oak",
)
SHOWN = 5   # rows of the side-by-side table
DEPTH = 10  # list depth of overlap and Spearman
NAME_WIDTH = 30


def overlap(ranking_a, ranking_b, depth=DEPTH):
    """Share of documents the two top-depth lists have in common."""
    return len(set(ranking_a[:depth]) & set(ranking_b[:depth])) / depth


def spearman(ranking_a, ranking_b, depth=DEPTH):
    """Spearman's rho over the union of the two top-depth lists.

    Both are full rankings of the same candidates, so every document of the
    union has a position in both. Renumbered 0..n-1 within the union, the ranks
    are distinct (ties were broken by doc id), so rho = 1 - 6 sum(d^2) / (n (n^2 - 1)).
    """
    union = set(ranking_a[:depth]) | set(ranking_b[:depth])
    n = len(union)
    if n < 2:
        return 1.0
    position_a = {doc_id: position for position, doc_id in enumerate(ranking_a)}
    position_b = {doc_id: position for position, doc_id in enumerate(ranking_b)}
    rank_a = {doc_id: rank for rank, doc_id in enumerate(sorted(union, key=position_a.get))}
    rank_b = {doc_id: rank for rank, doc_id in enumerate(sorted(union, key=position_b.get))}
    d_squared = sum((rank_a[doc_id] - rank_b[doc_id]) ** 2 for doc_id in union)
    return 1 - 6 * d_squared / (n * (n * n - 1))


def result_cell(index, doc_id, score):
    doc = index.docs[doc_id]
    name = doc["scientific_name"] or doc["url"]
    if len(name) > NAME_WIDTH:
        name = name[:NAME_WIDTH - 3] + "..."
    return "{} [{}] {:.3f}".format(name, doc["source"], score)


def compare_query(index, query, tf_method="log", norm="cosine"):
    """Tables of one query: [(caption, header, rows), ...] and {method pair: (overlap, spearman)}."""
    rankings = {method: index.rank(query, method, tf_method, norm) for method in weighting.IDF_METHODS}
    doc_ids = {method: [doc_id for doc_id, _ in ranking] for method, ranking in rankings.items()}

    terms = list(dict.fromkeys(index.query_terms(query)))
    term_rows = []
    for term in terms:
        if term in index.df:
            term_rows.append([term, index.df[term]] + ["{:.3f}".format(index.idf(term, method))
                                                       for method in weighting.IDF_METHODS])
        else:
            term_rows.append([term, 0] + ["-"] * len(weighting.IDF_METHODS))

    top_rows = []
    for position in range(min(SHOWN, max(len(ranking) for ranking in rankings.values()))):
        row = [position + 1]
        for method in weighting.IDF_METHODS:
            ranking = rankings[method]
            row.append(result_cell(index, *ranking[position]) if position < len(ranking) else "")
        top_rows.append(row)

    agreement = {}
    for method_a, method_b in itertools.combinations(weighting.IDF_METHODS, 2):
        agreement[method_a, method_b] = (overlap(doc_ids[method_a], doc_ids[method_b]),
                                         spearman(doc_ids[method_a], doc_ids[method_b]))
    agreement_rows = [["{} vs {}".format(a, b), "{:.1f}".format(o), "{:.2f}".format(s)]
                      for (a, b), (o, s) in agreement.items()]

    tables = [
        ("query terms: df and idf (N={})".format(index.n), ["term", "df"] + list(weighting.IDF_METHODS), term_rows),
        ("top {} (scientific name [source] score)".format(SHOWN), ["#"] + list(weighting.IDF_METHODS), top_rows),
        ("agreement of the top {}".format(DEPTH), ["methods", "overlap@{}".format(DEPTH), "Spearman"],
         agreement_rows),
    ]
    return tables, agreement


def text_table(header, rows):
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows)]
    lines = ["  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)).rstrip()
             for row in [header] + rows]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)


def markdown_table(header, rows):
    lines = ["| " + " | ".join(str(cell) for cell in header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare the idf methods on fixed queries")
    parser.add_argument("--query", action="append", help="query to compare (repeatable); default: the report queries")
    parser.add_argument("--tf", choices=weighting.TF_METHODS, default="log")
    parser.add_argument("--norm", choices=NORMS, default="cosine")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    index_dir = os.path.join(args.data_dir, "index")
    index = Index(index_dir)
    meta = index.meta
    sources = ", ".join("{} {}".format(source, count) for source, count in meta["documents_per_source"].items())
    intro = ("Index built {}: N={} documents ({}), {} terms; name boost {}x, fold plurals {}. "
             "Weights: document tf={} (norm={}), query count x idf (classic | smooth | none).").format(
        meta["built_at_utc"], index.n, sources, meta["vocabulary_size"], meta["options"]["name_boost"],
        "on" if meta["options"]["fold_plurals"] else "off", args.tf, args.norm)

    text_parts = [intro]
    markdown_parts = ["# Comparison of idf methods", "", intro]
    totals = {}
    queries = args.query or QUERIES
    for query in queries:
        tables, agreement = compare_query(index, query, args.tf, args.norm)
        for pair, values in agreement.items():
            totals.setdefault(pair, []).append(values)
        text_parts.append("\n=== {} ===".format(query))
        markdown_parts.append("\n## {}".format(query))
        for caption, header, rows in tables:
            text_parts.append("\n{}\n{}".format(caption, text_table(header, rows)))
            markdown_parts.append("\n{}:\n\n{}".format(caption, markdown_table(header, rows)))

    summary_header = ["methods", "mean overlap@{}".format(DEPTH), "mean Spearman"]
    summary_rows = [["{} vs {}".format(a, b),
                     "{:.2f}".format(sum(o for o, _ in values) / len(values)),
                     "{:.2f}".format(sum(s for _, s in values) / len(values))]
                    for (a, b), values in totals.items()]
    text_parts.append("\n=== all {} queries ===\n{}".format(len(queries), text_table(summary_header, summary_rows)))
    markdown_parts.append("\n## All {} queries\n\n{}".format(len(queries), markdown_table(summary_header, summary_rows)))

    print("\n".join(text_parts))
    markdown_path = os.path.join(index_dir, "idf_comparison.md")
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown_parts) + "\n")
    print("\nmarkdown -> {}".format(markdown_path))


if __name__ == "__main__":
    sys.exit(main())
