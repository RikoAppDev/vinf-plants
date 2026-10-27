"""Builds the inverted index from all extracted plant records.

Usage:
    python -m indexer.build
    python -m indexer.build --name-boost 1 --fold-plurals

One document = one record of data/extracted/<source>_plants.jsonl. Its text is
the scientific name, common names and synonyms (counted --name-boost times),
family, genus, description and the attribute values. The index is built in RAM
in one pass (SPIMI with a single block); doc ids grow in reading order, so no
postings list needs sorting. Only tf is stored and the vector lengths use tf
only: idf is computed at query time, so changing the idf method needs no rebuild.

Output in data/index/ (plain text, meta.json is written last):
    docs.tsv      doc_id, source, url, scientific_name, length, max_tf
    postings.tsv  term, df, postings "doc_id:tf doc_id:tf ..." (terms sorted, doc ids ascending)
    norms.tsv     doc_id, vector length for each tf variant (log, raw, maxnorm)
    meta.json     N, build time, token counts, vocabulary size, options
"""

import argparse
import glob
import json
import math
import os
import sys
import time
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import tokenize, weighting

RECORD_SUFFIX = "_plants.jsonl"
# The other top-level fields (url, source, authority, parsed numbers) are metadata.
# species is left out: it is already the second word of scientific_name.
NAME_FIELDS = ("scientific_name", "common_names", "synonyms")
TEXT_FIELDS = ("family", "genus", "description")
# A pronunciation guide ("a-BEE-lee-a chy-NEN-sis") is not text about the
# plant; its syllables would become made-up terms with the highest idf.
SKIPPED_ATTRIBUTES = {"Phonetic Spelling"}
# A name match is a stronger signal than the same word in a long description (1 = no boost).
DEFAULT_NAME_BOOST = 3

DOC_COLUMNS = ("doc_id", "source", "url", "scientific_name", "length", "max_tf")


def record_files(extracted_dir):
    """(source, path) of every <source>_plants.jsonl, sorted so doc ids are reproducible."""
    paths = sorted(glob.glob(os.path.join(extracted_dir, "*" + RECORD_SUFFIX)))
    return [(os.path.basename(path)[:-len(RECORD_SUFFIX)], path) for path in paths]


def read_records(path):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def field_texts(value):
    """Strings of a field holding a string or a list of strings; numbers and None give nothing."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def weighted_texts(record, name_boost=DEFAULT_NAME_BOOST):
    """(text, weight) pairs that make up the indexed text of one record."""
    for field in NAME_FIELDS:
        for text in field_texts(record.get(field)):
            yield text, name_boost
    for field in TEXT_FIELDS:
        for text in field_texts(record.get(field)):
            yield text, 1
    # Values only: a label such as "Flower Color" is on every page of a source. The extractors copy
    # some attributes into top-level fields (NCSU Family, Wood Database prose, "Common Name(s)"),
    # so a value already in the indexed text is skipped instead of counted twice.
    already_indexed = " | ".join(text for field in NAME_FIELDS + TEXT_FIELDS for text in field_texts(record.get(field)))
    names_as_printed = ", ".join(field_texts(record.get("common_names")))
    for label, values in (record.get("attributes") or {}).items():
        if label in SKIPPED_ATTRIBUTES or record.get(label.lower().replace(" ", "_")):
            continue
        for text in field_texts(values):
            if text in already_indexed or text == names_as_printed:
                continue
            yield text, 1


def document_terms(record, name_boost=DEFAULT_NAME_BOOST, fold_plurals=False):
    """(Counter term -> tf, regex token count, indexed token count); only tf includes the name boost."""
    tf = Counter()
    token_count = indexed_count = 0
    for text, weight in weighted_texts(record, name_boost):
        raw = tokenize.words(text)
        kept = tokenize.terms(raw, fold_plurals)
        token_count += len(raw)
        indexed_count += len(kept)
        for term in kept:
            tf[term] += weight
    return tf, token_count, indexed_count


def document_lengths(tf):
    """Euclidean length of the document vector for each tf variant.

    length(d) = sqrt(sum of tf_weight(t, d)^2 over the terms of d), the cosine denominator; no idf.
    """
    max_tf = max(tf.values(), default=0)
    return {method: math.sqrt(sum(weighting.tf_weight(method, count, max_tf) ** 2 for count in tf.values()))
            for method in weighting.TF_METHODS}


def build_index(extracted_dir, name_boost=DEFAULT_NAME_BOOST, fold_plurals=False):
    """(docs, postings, stats) of all records; postings: term -> array [doc_id, tf, doc_id, tf, ...]."""
    docs = []
    # array("I") stores each number in 4 bytes. A list of (doc_id, tf) tuples
    # would cost about 70 bytes per posting, hundreds of MB for all sources.
    postings = defaultdict(lambda: array("I"))
    stats = Counter()
    for source, path in record_files(extracted_dir):
        for record in read_records(path):
            doc_id = len(docs)
            tf, token_count, indexed_count = document_terms(record, name_boost, fold_plurals)
            for term, count in tf.items():
                postings[term].extend((doc_id, count))
            docs.append({
                "doc_id": doc_id,
                "source": source,
                "url": record.get("url", ""),
                "scientific_name": record.get("scientific_name", ""),
                "length": sum(tf.values()),
                "max_tf": max(tf.values(), default=0),
                "norms": document_lengths(tf),
            })
            stats["tokens"] += token_count
            stats["indexed_tokens"] += indexed_count
            stats["source:" + source] += 1
    return docs, dict(postings), stats


def pairs(postings_list):
    """(doc_id, tf) pairs of a packed postings array."""
    return zip(postings_list[0::2], postings_list[1::2])


def tsv_field(value):
    """A value safe for one TSV cell: tabs and newlines become single spaces."""
    return " ".join(str(value).split())


def write_lines(path, header, rows):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")


def write_index(index_dir, docs, postings):
    """docs.tsv, postings.tsv and norms.tsv; the caller writes meta.json last."""
    os.makedirs(index_dir, exist_ok=True)
    # Without meta.json the search refuses the index, so a build that is cut
    # off half way is never mistaken for a complete one.
    meta_path = os.path.join(index_dir, "meta.json")
    if os.path.exists(meta_path):
        os.remove(meta_path)
    write_lines(os.path.join(index_dir, "docs.tsv"), DOC_COLUMNS,
                ([tsv_field(doc[column]) for column in DOC_COLUMNS] for doc in docs))
    write_lines(os.path.join(index_dir, "postings.tsv"), ("term", "df", "postings"),
                ([term, str(len(postings[term]) // 2),
                  " ".join("{}:{}".format(doc_id, tf) for doc_id, tf in pairs(postings[term]))]
                 for term in sorted(postings)))
    write_lines(os.path.join(index_dir, "norms.tsv"), ("doc_id",) + weighting.TF_METHODS,
                ([str(doc["doc_id"])] + [format(doc["norms"][method], ".10g") for method in weighting.TF_METHODS]
                 for doc in docs))


def write_meta(index_dir, meta):
    with open(os.path.join(index_dir, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def index_size(index_dir):
    """Bytes of all index files on disk."""
    return sum(os.path.getsize(os.path.join(index_dir, name)) for name in os.listdir(index_dir)
               if name.endswith((".tsv", ".json")))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the inverted index from extracted plant records")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--name-boost", type=int, default=DEFAULT_NAME_BOOST,
                        help="tf multiplier of scientific name, common names and synonyms (1 = no boost)")
    parser.add_argument("--fold-plurals", action="store_true",
                        help="fold regular English plurals (trees -> tree); off by default")
    args = parser.parse_args(argv)
    if args.name_boost < 1:
        parser.error("--name-boost must be at least 1")

    started = time.perf_counter()
    extracted_dir = os.path.join(args.data_dir, "extracted")
    index_dir = os.path.join(args.data_dir, "index")
    files = record_files(extracted_dir)
    if not files:
        parser.error("no *{} files in {}".format(RECORD_SUFFIX, extracted_dir))

    docs, postings, stats = build_index(extracted_dir, args.name_boost, args.fold_plurals)
    n = len(docs)
    write_index(index_dir, docs, postings)

    sources = {source: stats["source:" + source] for source, _ in files}
    postings_count = sum(len(postings_list) // 2 for postings_list in postings.values())
    lengths = [doc["length"] for doc in docs]
    meta = {
        "N": n,
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_seconds": round(time.perf_counter() - started, 2),
        "documents_per_source": sources,
        "files": [os.path.basename(path) for _, path in files],
        "tokens": stats["tokens"],
        "tokens_dropped": stats["tokens"] - stats["indexed_tokens"],
        "tokens_indexed": stats["indexed_tokens"],
        "vocabulary_size": len(postings),
        "postings": postings_count,
        "avg_document_length": round(sum(lengths) / n, 1) if n else 0,
        "stopword_count": len(tokenize.STOPWORDS),
        "options": {"name_boost": args.name_boost, "fold_plurals": args.fold_plurals},
        "tf_methods": list(weighting.TF_METHODS),
        "idf_methods": list(weighting.IDF_METHODS),
        "maxnorm_alpha": weighting.MAXNORM_ALPHA,
    }
    write_meta(index_dir, meta)

    print("documents\t{} ({})".format(n, ", ".join("{} {}".format(s, c) for s, c in sources.items())))
    print("tokens\t{} by the regex, {} dropped (stop words, one-letter), {} indexed".format(
        meta["tokens"], meta["tokens_dropped"], meta["tokens_indexed"]))
    print("vocabulary\t{} terms, {} postings".format(meta["vocabulary_size"], postings_count))
    print("document length (tf sum, name boost {}x)\tavg {}, max {}".format(
        args.name_boost, meta["avg_document_length"], max(lengths, default=0)))
    print("stop words\t{}".format(meta["stopword_count"]))
    print("index size\t{:.1f} MB in {}".format(index_size(index_dir) / 1e6, index_dir))
    print("build time\t{:.1f} s".format(meta["build_seconds"]))


if __name__ == "__main__":
    sys.exit(main())
