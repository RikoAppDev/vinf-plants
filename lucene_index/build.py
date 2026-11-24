"""Builds the PyLucene index of the plant entities: one Lucene document per entity.

Usage (in the PyLucene image coady/pylucene, through lucene_docker.sh):
    ./lucene_docker.sh lucene_index.build
    ./lucene_docker.sh lucene_index.build --out data/lucene/index --stats data/lucene/stats.json

lucene_index.documents assembles the documents from the Spark output (MANUAL.md, section 8); this
module only maps their fields to Lucene fields and writes the index (data/lucene/index/) and its
statistics (data/lucene/stats.json). A build that fails or is interrupted leaves the previous index.

Field types:
    TextField    analyzed, with positions (phrase queries); NAME_FIELDS, TAG_FIELDS and origin are stored
    StringField  id, key, source, iucn: one exact term per value, stored
    IntPoint     the numbers, for range queries; a StoredField of the same name keeps the value
    StoredField  page URLs and the Wikipedia title, URL and match kind: shown, never searched
"""

import argparse
import glob
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import lucene
from java.nio.file import Paths
from java.util import HashMap
from org.apache.lucene.analysis.core import KeywordTokenizerFactory, LowerCaseFilterFactory, StopFilterFactory
from org.apache.lucene.analysis.custom import CustomAnalyzer
from org.apache.lucene.analysis.en import EnglishPossessiveFilterFactory, PorterStemFilterFactory
from org.apache.lucene.analysis.miscellaneous import PerFieldAnalyzerWrapper
from org.apache.lucene.analysis.pattern import PatternReplaceCharFilterFactory
from org.apache.lucene.analysis.standard import StandardTokenizerFactory
from org.apache.lucene.document import Document, Field, IntPoint, StoredField, StringField, TextField
from org.apache.lucene.index import (DirectoryReader, IndexWriter, IndexWriterConfig, LogByteSizeMergePolicy,
                                     MultiTerms)
from org.apache.lucene.search.similarities import BM25Similarity, ClassicSimilarity
from org.apache.lucene.store import FSDirectory

from . import documents
from .documents import EXACT_FIELDS, NUMBER_FIELDS, STORED_FIELDS, TEXT_FIELDS

INDEX_DIR = os.path.join("data", "lucene", "index")
STATS_PATH = os.path.join("data", "lucene", "stats.json")
BUILD_COMMAND = "./lucene_docker.sh lucene_index.build"
# The Spark jobs that write the input folders (MANUAL.md, section 8).
SPARK_JOBS = {"entities": "./spark_docker.sh sparkjobs.join_wiki",
              "records": "./spark_docker.sh sparkjobs.extract_sites"}
# lucene_index.search scores with one of these; BM25 is the default of Lucene.
SIMILARITIES = {"classic": ClassicSimilarity, "bm25": BM25Similarity}
DEFAULT_SIMILARITY = "bm25"
# A JVM crash log goes to /tmp, not into the working directory (the project folder).
VM_ARGS = ["-Djava.awt.headless=true", "-XX:ErrorFile=/tmp/hs_err_pid%p.log"]

# Values shown in the result list or needed to check why a filter matched: the short name and tag
# values, and origin, which can be a sentence but is the only way to see why origin:europe matched.
# The long texts (uses, text, wiki, category) are not stored: the source JSON has them and the index
# stays small.
STORED_TEXT_FIELDS = set(documents.NAME_FIELDS + documents.TAG_FIELDS + ("origin",))
# Prose: stemming lets "tolerant" find "tolerates" and "hedges" find "hedge".
ENGLISH_FIELDS = ("text", "wiki", "uses")
# The name fields of free text drop stop words as the prose fields do: with the default operator AND,
# "for" in "shrubs for shade" would otherwise be a required word that only a name can match.
# The tag fields are no fields of free text, so that reason does not apply to them: they keep their
# stop words, and landscape:"garden for the blind" matches the value word for word.
STOP_NAME_FIELDS = ("name", "common_name", "synonym")
# "Semi-evergreen" would be split into semi + evergreen and match leaf:evergreen; the leaf field joins
# it into one word before tokenizing, in the index and in a query alike.
SEMI_EVERGREEN = ("(?i)\\bsemi-evergreen\\b", "semievergreen")
# Positions between two values of a multi-valued field, so that a phrase cannot join the end of one
# common name to the start of the next (the same default as Solr).
POSITION_GAP = 100


def start_vm():
    """Starts the JVM once per process; a later call only attaches the current thread."""
    env = lucene.getVMEnv()
    if env is None:
        return lucene.initVM(vmargs=VM_ARGS)
    env.attachCurrentThread()
    return env


def standard_analyzer():
    """StandardAnalyzer (StandardTokenizer, lower case, no stop words) with POSITION_GAP."""
    return (CustomAnalyzer.builder()
            .withTokenizer(StandardTokenizerFactory.class_, [])
            .addTokenFilter(LowerCaseFilterFactory.class_, [])
            .withPositionIncrementGap(POSITION_GAP)
            .build())


def name_analyzer():
    """standard_analyzer with the English stop words of english_analyzer."""
    return (CustomAnalyzer.builder()
            .withTokenizer(StandardTokenizerFactory.class_, [])
            .addTokenFilter(LowerCaseFilterFactory.class_, [])
            .addTokenFilter(StopFilterFactory.class_, [])
            .withPositionIncrementGap(POSITION_GAP)
            .build())


def leaf_analyzer():
    """standard_analyzer that first rewrites semi-evergreen (SEMI_EVERGREEN)."""
    pattern, replacement = SEMI_EVERGREEN
    return (CustomAnalyzer.builder()
            .addCharFilter(PatternReplaceCharFilterFactory.class_, ["pattern", pattern, "replacement", replacement])
            .withTokenizer(StandardTokenizerFactory.class_, [])
            .addTokenFilter(LowerCaseFilterFactory.class_, [])
            .withPositionIncrementGap(POSITION_GAP)
            .build())


def english_analyzer():
    """EnglishAnalyzer (possessives, lower case, English stop words, Porter stemmer) with POSITION_GAP."""
    return (CustomAnalyzer.builder()
            .withTokenizer(StandardTokenizerFactory.class_, [])
            .addTokenFilter(EnglishPossessiveFilterFactory.class_, [])
            .addTokenFilter(LowerCaseFilterFactory.class_, [])
            .addTokenFilter(StopFilterFactory.class_, [])
            .addTokenFilter(PorterStemFilterFactory.class_, [])
            .withPositionIncrementGap(POSITION_GAP)
            .build())


def exact_analyzer():
    """Whole input as one lower-case term: what a query on a StringField must produce."""
    return (CustomAnalyzer.builder()
            .withTokenizer(KeywordTokenizerFactory.class_, [])
            .addTokenFilter(LowerCaseFilterFactory.class_, [])
            .build())


def analyzer():
    """The analyzer of every field, used for indexing and for parsing queries."""
    per_field = HashMap()
    english = english_analyzer()
    for field in ENGLISH_FIELDS:
        per_field.put(field, english)
    names = name_analyzer()
    for field in STOP_NAME_FIELDS:
        per_field.put(field, names)
    per_field.put("leaf", leaf_analyzer())
    # StringFields are not analyzed when indexed; this only shapes the query term (iucn:EN -> en).
    exact = exact_analyzer()
    for field in EXACT_FIELDS:
        per_field.put(field, exact)
    return PerFieldAnalyzerWrapper(standard_analyzer(), per_field)


def lucene_document(doc):
    """Lucene Document of one lucene_index.documents dict."""
    document = Document()
    for field in TEXT_FIELDS:
        store = Field.Store.YES if field in STORED_TEXT_FIELDS else Field.Store.NO
        for value in doc[field]:
            document.add(TextField(field, value, store))
    for field in EXACT_FIELDS:
        for value in doc[field]:
            document.add(StringField(field, value, Field.Store.YES))
    for field in NUMBER_FIELDS:
        value = doc[field]
        if value is not None:
            document.add(IntPoint(field, [value]))
            document.add(StoredField(field, value))
    for field in STORED_FIELDS:
        for value in doc[field]:
            document.add(StoredField(field, value))
    return document


def field_counts(doc, counts):
    """Adds the documents and values of every field of one document to counts."""
    for field in documents.FIELDS:
        value = doc[field]
        values = ([] if value is None else [value]) if field in NUMBER_FIELDS else value
        if values:
            counts[field, "documents"] += 1
            counts[field, "values"] += len(values)


def directory_size(folder):
    return sum(os.path.getsize(os.path.join(folder, name)) for name in os.listdir(folder)
               if os.path.isfile(os.path.join(folder, name)))


def term_stats(index_dir):
    """({field: (distinct terms, tokens)} of the indexed fields, number of segments), read back from the index."""
    directory = FSDirectory.open(Paths.get(index_dir))
    reader = DirectoryReader.open(directory)
    try:
        found = {}
        for field in TEXT_FIELDS + EXACT_FIELDS:
            terms = MultiTerms.getTerms(reader, field)
            if terms is not None:
                found[field] = (terms.size(), terms.getSumTotalTermFreq())
        return found, reader.leaves().size()
    finally:
        reader.close()
        directory.close()


def build_index(docs, index_dir, similarity=DEFAULT_SIMILARITY):
    """Writes the index of docs into index_dir and returns per-field counts.

    Nothing is committed before the last document is added and merged, so a build that fails or is
    interrupted (an error, Ctrl+C, a killed process) leaves the previous index; on a Python exception,
    or without a single document, the writer also rolls back and removes its unfinished files.
    """
    os.makedirs(index_dir, exist_ok=True)
    config = IndexWriterConfig(analyzer())
    config.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
    # Both similarities store the length of a field as the same one-byte norm, so the index written
    # with the default can be searched with either one.
    config.setSimilarity(SIMILARITIES[similarity]())
    # A log merge policy merges only neighbouring segments: doc ids keep the entity order, so documents
    # with equal scores (pure filters) are listed by key.
    config.setMergePolicy(LogByteSizeMergePolicy())
    directory = FSDirectory.open(Paths.get(index_dir))
    try:
        writer = IndexWriter(directory, config)
        counts = Counter()
        try:
            for doc in docs:
                writer.addDocument(lucene_document(doc))
                counts["documents"] += 1
                field_counts(doc, counts)
            if not counts["documents"]:
                raise ValueError("no documents to index")
            # The index is written once and read many times: one segment is smaller and faster to search.
            writer.forceMerge(1)
            writer.commit()
        except BaseException:
            # close() would commit what was added so far, and with OpenMode.CREATE that part would
            # replace the previous index.
            writer.rollback()
            raise
        writer.close()
    finally:
        directory.close()
    return counts


def missing_input(entities_dir, records_dir):
    """One-line message naming the first input folder without Spark output (part-* files); None if all have it."""
    folders = [(entities_dir, "entities")] + [(os.path.join(records_dir, site), "records") for site in documents.SITES]
    for folder, kind in folders:
        if not glob.glob(os.path.join(folder, "part-*")):
            return "no Spark output (part-* files) in {}: {} writes it (MANUAL.md, section 8), then run {}".format(
                folder, SPARK_JOBS[kind], BUILD_COMMAND)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the PyLucene index of the plant entities")
    parser.add_argument("--entities", default=documents.ENTITIES_DIR, help="joined entities (Spark output folder)")
    parser.add_argument("--records", default=documents.RECORDS_DIR, help="extracted records, one folder per site")
    parser.add_argument("--out", default=INDEX_DIR, help="index folder (replaced)")
    parser.add_argument("--stats", default=STATS_PATH)
    args = parser.parse_args(argv)

    # A wrong input folder would otherwise give an empty index, or documents without attributes,
    # in place of the good one.
    problem = missing_input(args.entities, args.records)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    started = time.perf_counter()
    docs = list(documents.read_documents(args.entities, args.records))
    read_seconds = time.perf_counter() - started
    if not docs:
        print("no documents in {}: {} writes the entities (MANUAL.md, section 8), then run {}".format(
            args.entities, SPARK_JOBS["entities"], BUILD_COMMAND), file=sys.stderr)
        return 2
    start_vm()
    started = time.perf_counter()
    counts = build_index(docs, args.out)
    build_seconds = time.perf_counter() - started
    terms, segments = term_stats(args.out)

    stats = {
        "documents": counts["documents"],
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Writing, merging and committing the index; reading the Spark output is read_seconds.
        "build_seconds": round(build_seconds, 2),
        "read_seconds": round(read_seconds, 2),
        "index_size_bytes": directory_size(args.out),
        "segments": segments,
        "lucene_version": lucene.VERSION,
        "similarity": SIMILARITIES[DEFAULT_SIMILARITY].__name__,
        "fields": {field: {"documents": counts[field, "documents"], "values": counts[field, "values"],
                           "terms": terms.get(field, (None, None))[0], "tokens": terms.get(field, (None, None))[1]}
                   for field in documents.FIELDS},
    }
    os.makedirs(os.path.dirname(args.stats) or ".", exist_ok=True)
    with open(args.stats, "w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=2)
        handle.write("\n")

    print("lucene {}, {} documents: inputs read in {:.1f} s, index built in {:.1f} s".format(
        stats["lucene_version"], stats["documents"], read_seconds, build_seconds))
    print("index {:.1f} MB in {} ({} segment)".format(stats["index_size_bytes"] / 1e6, args.out, segments))
    print("{:<14} {:>9} {:>8} {:>8} {:>9}".format("field", "documents", "values", "terms", "tokens"))
    for field, row in stats["fields"].items():
        print("{:<14} {:>9} {:>8} {:>8} {:>9}".format(field, row["documents"], row["values"],
                                                      "" if row["terms"] is None else row["terms"],
                                                      "" if row["tokens"] is None else row["tokens"]))


if __name__ == "__main__":
    sys.exit(main())
