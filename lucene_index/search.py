"""Search the PyLucene index of the plant entities.

Usage (in the PyLucene image coady/pylucene, through lucene_docker.sh):
    ./lucene_docker.sh lucene_index.search "mountain laurel"
    ./lucene_docker.sh lucene_index.search "authority:L AND year:[1754 TO 1800] AND soil:clay AND zone_min:[* TO 5]"
    ./lucene_docker.sh lucene_index.search "quercus robur" --similarity classic --top 5 --explain
    ./lucene_docker.sh lucene_index.search "japanese maple" --operator and
    ./lucene_docker.sh lucene_index.search -- "-robur quercus"

Query syntax (StandardQueryParser, the flexible query parser of Lucene):
    free text        drought tolerant shrub
    field            soil:clay   iucn:en   source:tso   origin:europe
    Boolean          quercus AND robur   quercus NOT robur   +quercus -robur   (alba OR robur) AND soil:clay
    phrase           "mountain laurel"   light:"full sun"   "mountain laurel"~3
    fuzzy, wildcard  quercsu~   quercsu~1   rhodo*
    range            year:[1754 TO 1800]   zone_min:[* TO 5]   density:{700 TO *]   year>1800
    boost            name:robur^2
    all plants       *:*   *:* NOT robur
Words without a field are searched in DEFAULT_FIELDS with OR between them (--operator and: every word
must match). Operators are written in capitals. A query of only NOT clauses matches nothing, hence
*:* NOT robur. lucene_index.querycheck rejects what the parser would run with a misleading result
(an unknown field, a number field value that is no whole number) and explains syntax errors.
Plain words that are the whole name of a plant (acer palmatum) also match its key, boosted by KEY_BOOST,
so that plant comes first; the hits stay the same.

Scoring (--similarity), summed over the query terms and the fields they match in:
    bm25     BM25Similarity, the default: boost * idf * tf / (tf + k1 * (1 - b + b * length / average length))
             with idf = ln(1 + (docCount - docFreq + 0.5) / (docFreq + 0.5)), k1 = 1.2, b = 0.75
    classic  ClassicSimilarity: boost * idf * sqrt(tf) * 1 / sqrt(field length)
             with idf = 1 + ln((docCount + 1) / (docFreq + 1))
With ClassicSimilarity the length norm of the long text field (about 500 words on average) makes even
many matches there count for almost nothing, so a one-word query is decided by the short name fields:
oak ranks Quercus robur, whose text says oak 71 times, 19th with classic and first with BM25.
"""

import argparse
import os
import re
import sys
import time

import lucene
from java.lang import Float, IllegalArgumentException, IllegalStateException, Integer
from java.nio.file import Paths
from java.text import NumberFormat
from java.util import HashMap, Locale
from org.apache.lucene.index import DirectoryReader, Term
from org.apache.lucene.queryparser.flexible.core import QueryNodeException
from org.apache.lucene.queryparser.flexible.standard import StandardQueryParser
from org.apache.lucene.queryparser.flexible.standard.config import PointsConfig, StandardQueryConfigHandler
from org.apache.lucene.search import BooleanClause, BooleanQuery, BoostQuery, IndexSearcher, TermQuery
from org.apache.lucene.store import FSDirectory
from org.apache.lucene.util.automaton import TooComplexToDeterminizeException
from tools.merge_entities import entity_key

from . import querycheck
from .build import BUILD_COMMAND, DEFAULT_SIMILARITY, INDEX_DIR, SIMILARITIES, analyzer, start_vm
from .documents import NAME_FIELDS, NUMBER_FIELDS, TAG_FIELDS

# Fields of a word without a field name, with their boosts: a name match counts most, then a common
# name or synonym, then the descriptions, then the Wikipedia lead. The parser keeps a boost per field,
# so it also scales a query that names the field (name:robur^2 -> ((name:robur)^0.4)^2.0).
DEFAULT_FIELDS = (("name", 0.4), ("common_name", 0.3), ("synonym", 0.3), ("text", 0.2), ("wiki", 0.1))
# OR is the Lucene default and ranks like the old index; AND makes every word of free text required.
OPERATORS = ("or", "and")
DEFAULT_OPERATOR = "or"
# Plain words that are a plant's whole name also match its key: BM25 scales down the long joined text of a
# species, so its cultivars outranked it. Boost 1 put all 600 sampled names first; 2 leaves a margin.
KEY_BOOST = 2.0
# Stored values of a hit; the tag fields and origin show why a filter matched.
LIST_FIELDS = NAME_FIELDS + TAG_FIELDS + ("origin", "source", "iucn", "url")
SINGLE_FIELDS = ("id", "key", "wiki_title", "wiki_url", "wiki_match")
# Longest text of the values of one field in the "why it matched" line of the command line.
FIELD_VALUES_WIDTH = 60
TIME_LABEL = "first query in a fresh JVM"
# The same names as on the search page.
SIMILARITY_LABELS = {"bm25": "BM25", "classic": "classic tf-idf"}
EPILOG = """A query that starts with - goes after --, so that it is not taken for an option:
  ./lucene_docker.sh lucene_index.search -- "-robur quercus"
Operators are written in capitals (AND, OR, NOT); *:* matches all plants."""


class QueryError(ValueError):
    """A query that the user can correct.

    str() is plain text: the explanation, and on a second line Lucene's own message if there is one.
    """

    def __init__(self, explanation, lucene_message=None):
        super().__init__(explanation if lucene_message is None else "{}\nLucene: {}".format(explanation,
                                                                                          lucene_message))
        self.explanation = explanation
        self.lucene_message = lucene_message


def query_error(error, query_string):
    """QueryError of a Java error that the query caused; None for any other error."""
    java_error = error.getJavaException()
    message = " ".join((java_error.getMessage() or java_error.toString()).split())
    if QueryNodeException.instance_(java_error):
        return QueryError(querycheck.syntax_hint(query_string) or "Lucene cannot parse the query", message)
    if IndexSearcher.TooManyClauses.instance_(java_error):
        return QueryError("the query expands to more than {} terms (every fuzzy or wildcard term matches many "
                          "words); use fewer or longer terms".format(IndexSearcher.getMaxClauseCount()), message)
    if TooComplexToDeterminizeException.instance_(java_error):
        return QueryError("the regular expression is too complex for Lucene; write a simpler one", message)
    if IllegalArgumentException.instance_(java_error):
        return QueryError("Lucene rejects a part of the query", message)
    # fn:wildcard expands to a limited number of words. Other IllegalStateExceptions, such as a closed
    # index, are no fault of the query.
    if IllegalStateException.instance_(java_error) and "expanded to too many terms" in message:
        limit = re.search(r"limit (\d+)", message)
        return QueryError("the wildcard in fn:wildcard matches more than {} words; write a longer prefix".format(
            limit.group(1) if limit else "the allowed number of"), message)
    return None


def query_parser(operator=DEFAULT_OPERATOR):
    parser = StandardQueryParser(analyzer())
    # Java enum constants exist only once the JVM runs, so they are looked up here.
    parser.setDefaultOperator(getattr(StandardQueryConfigHandler.Operator, operator.upper()))
    # setMultiFields takes a CharSequence[], which JCC cannot build from Python; the config key it sets
    # accepts a String[], and a String[] is a CharSequence[] for Java.
    parser.getQueryConfigHandler().set(StandardQueryConfigHandler.ConfigurationKeys.MULTI_FIELDS,
                                       lucene.JArray("string")([field for field, _boost in DEFAULT_FIELDS]))
    boosts = HashMap()
    for field, boost in DEFAULT_FIELDS:
        boosts.put(field, Float(boost))
    parser.setFieldsBoost(boosts)
    # Without a PointsConfig a range on an IntPoint field would become a term range and match nothing.
    points = HashMap()
    for field in NUMBER_FIELDS:
        points.put(field, PointsConfig(NumberFormat.getIntegerInstance(Locale.ROOT), Integer.class_))
    parser.setPointsConfigMap(points)
    return parser


def hit_dict(rank, score_doc, document):
    """Stored values of one hit as a plain dict."""
    hit = {"rank": rank, "score": score_doc.score, "doc": score_doc.doc}
    for field in LIST_FIELDS:
        hit[field] = list(document.getValues(field))
    for field in SINGLE_FIELDS:
        hit[field] = document.get(field)
    for field in NUMBER_FIELDS:
        stored = document.getField(field)
        hit[field] = None if stored is None else stored.numericValue().intValue()
    return hit


def name_key(query_string):
    """Entity key that tools.merge_entities makes of the words of a query; "" if they are no plant name."""
    words = " ".join(querycheck.unescape(query_string).lower().split())
    # entity_key recognises a genus by its capital letter.
    return entity_key(words[:1].upper() + words[1:])


def index_exists(index_dir):
    """True if index_dir holds a Lucene index."""
    if not os.path.isdir(index_dir):
        return False
    start_vm()
    directory = FSDirectory.open(Paths.get(index_dir))
    try:
        return bool(DirectoryReader.indexExists(directory))
    finally:
        directory.close()


class Searcher:
    """An open index with its query parser, for one similarity and default operator."""

    def __init__(self, index_dir=INDEX_DIR, similarity=DEFAULT_SIMILARITY, operator=DEFAULT_OPERATOR):
        if similarity not in SIMILARITIES:
            raise ValueError("unknown similarity: {}".format(similarity))
        if operator not in OPERATORS:
            raise ValueError("unknown operator: {}".format(operator))
        start_vm()
        self.directory = FSDirectory.open(Paths.get(index_dir))
        self.reader = DirectoryReader.open(self.directory)
        self.searcher = IndexSearcher(self.reader)
        self.searcher.setSimilarity(SIMILARITIES[similarity]())
        self.parser = query_parser(operator)
        self.similarity = similarity

    def parse(self, query_string):
        """Lucene query of query_string, as search runs it; QueryError if the user has to correct it."""
        problem = querycheck.problem(query_string)
        if problem:
            raise QueryError(problem)
        try:
            # No default field: a term without a field is then expanded to DEFAULT_FIELDS.
            query = self.parser.parse(query_string, None)
        except lucene.JavaError as error:
            user_error = query_error(error, query_string)
            if user_error is None:
                raise
            raise user_error from None
        return self.with_key_clause(query, query_string)

    def with_key_clause(self, query, query_string):
        """query, or for plain words that are the key of a plant: query required, plus that key boosted.

        The hits stay the same; only the plant whose key the words are moves up.
        """
        if not querycheck.plain_words(query_string):
            return query
        key = name_key(query_string)
        if not key or not self.reader.docFreq(Term("key", key)):
            return query
        builder = BooleanQuery.Builder()
        builder.add(query, BooleanClause.Occur.MUST)
        builder.add(BoostQuery(TermQuery(Term("key", key)), KEY_BOOST), BooleanClause.Occur.SHOULD)
        return builder.build()

    def search(self, query_string, top=10):
        """(parsed query, total hits, [hit dict]) of the best top hits; QueryError for a query to correct."""
        query = self.parse(query_string)
        try:
            # Fuzzy and wildcard terms are expanded to the matching words once, not again by count and search.
            rewritten = self.searcher.rewrite(query)
            total = self.searcher.count(rewritten)
            score_docs = self.searcher.search(rewritten, max(top, 1)).scoreDocs
        except lucene.JavaError as error:
            user_error = query_error(error, query_string)
            if user_error is None:
                raise
            raise user_error from None
        stored = self.searcher.storedFields()
        hits = [hit_dict(rank, score_doc, stored.document(score_doc.doc))
                for rank, score_doc in enumerate(score_docs, 1)]
        return query, total, hits[:top]

    def explain(self, query, doc):
        return self.searcher.explain(query, doc).toString()

    def close(self):
        self.reader.close()
        self.directory.close()


_searchers = {}


def search(query_string, top=10, similarity=DEFAULT_SIMILARITY, operator=DEFAULT_OPERATOR, index_dir=INDEX_DIR):
    """(parsed query, total hits, [hit dict]); the index stays open for the next call."""
    key = (index_dir, similarity, operator)
    if key not in _searchers:
        _searchers[key] = Searcher(index_dir, similarity, operator)
    return _searchers[key].search(query_string, top)


def numbers_text(hit):
    parts = []
    # Some plants have a single zone (zone_min without zone_max).
    zones = [str(hit[field]) for field in ("zone_min", "zone_max") if hit[field] is not None]
    if zones:
        parts.append("zone " + "-".join(zones))
    if hit["height_max_cm"] is not None:
        parts.append("height {:g} m".format(hit["height_max_cm"] / 100))
    for field, label in (("year", "year"), ("density", "density"), ("janka", "janka"),
                         ("edibility", "edible"), ("medicinal", "medicinal")):
        if hit[field] is not None:
            parts.append("{} {}".format(label, hit[field]))
    if hit["iucn"]:
        parts.append("iucn " + hit["iucn"][0])
    return ", ".join(parts)


def matched_text(hit, fields, width=FIELD_VALUES_WIDTH):
    """'soil: Clay, Loam | origin: Europe': the stored values of the given fields, each cut to width."""
    parts = []
    for field in fields:
        value = hit.get(field)
        values = value if isinstance(value, list) else [] if value is None else [value]
        text = ", ".join(str(item) for item in values)
        if len(text) > width:
            text = text[:width - 3].rstrip() + "..."
        if text:
            parts.append("{}: {}".format(field, text))
    return " | ".join(parts)


def print_hit(hit, fields=()):
    names = "; ".join(hit["common_name"][:3])
    print("{:>3}  {:8.4f}  {}{}".format(hit["rank"], hit["score"], hit["name"][0] if hit["name"] else hit["key"],
                                        "  ({})".format(names) if names else ""))
    print("               {} | {} | wiki: {}".format(
        ", ".join(hit["family"]) or "-", " ".join(hit["source"]),
        "{} ({})".format(hit["wiki_title"], hit["wiki_match"]) if hit["wiki_title"] else "-"))
    details = numbers_text(hit)
    if details:
        print("               " + details)
    matched = matched_text(hit, fields)
    if matched:
        print("               " + matched)


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1, not {}".format(value))
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Search the PyLucene index of the plant entities", epilog=EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--top", type=positive_int, default=10, help="number of hits shown (default 10)")
    parser.add_argument("--similarity", choices=sorted(SIMILARITIES), default=DEFAULT_SIMILARITY)
    parser.add_argument("--operator", choices=OPERATORS, default=DEFAULT_OPERATOR,
                        help="operator between words without AND/OR (default or)")
    parser.add_argument("--explain", action="store_true", help="print the score explanation of every hit")
    parser.add_argument("--index", default=INDEX_DIR)
    args = parser.parse_args(argv)
    if not index_exists(args.index):
        print("error: no Lucene index in {}; build it with {}".format(args.index, BUILD_COMMAND), file=sys.stderr)
        return 2

    searcher = Searcher(args.index, args.similarity, args.operator)
    try:
        started = time.perf_counter()
        try:
            query, total, hits = searcher.search(args.query, args.top)
        except QueryError as error:
            print("error: {}".format(error), file=sys.stderr)
            return 2
        elapsed = time.perf_counter() - started
        for note in querycheck.notes(args.query):
            print("note: " + note, file=sys.stderr)
        print("query   {}".format(query))
        # A fresh JVM has not compiled the search code yet: a warm query takes a fraction of this time.
        print("{} hits, {} shown, {:.1f} ms ({}), {} similarity, default operator {}".format(
            total, len(hits), elapsed * 1000, TIME_LABEL, SIMILARITY_LABELS[args.similarity], args.operator.upper()))
        fields = querycheck.fields(args.query)
        for hit in hits:
            print_hit(hit, fields)
            if args.explain:
                print(searcher.explain(query, hit["doc"]))
    finally:
        searcher.close()


if __name__ == "__main__":
    sys.exit(main())
