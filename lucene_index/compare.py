"""Old index (indexer/, own tf-idf over the crawled records) against the PyLucene index (one document per plant).

Usage (in the PyLucene image coady/pylucene, see lucene_docker.sh; the old index is plain Python and runs
in the same container):
    ./lucene_docker.sh lucene_index.compare
    ./lucene_docker.sh lucene_index.compare --out data/lucene/compare.md --warmup 100 --repeats 30

Every query runs on both indexes. The six questions K1-1 to K1-6 are natural language for the old index
and a hand-written structured query (fields, ranges) for Lucene; each question also runs as free text on
Lucene ("K1-n free"), which tells the effect of the index apart from that of the query language. The other
queries are the same string on both. The old index ranks records, so its ranking is mapped to entities
through the record URL before the top 10 are compared. Lucene runs with the default similarity of
lucene_index.search; the last column compares it with the other similarity.

Times are medians of --repeats timed rounds after --warmup untimed rounds, every round running each query
once on both indexes: the JVM compiles hot code only after many calls and the old index parses a postings
list on first use. Both sides are timed for the ranking only (hit count and top 10), without result rows.
"""

import argparse
import functools
import glob
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone

from indexer import search as old_search

from . import documents

try:
    import lucene
except ImportError:
    lucene = None

if lucene:
    from .build import INDEX_DIR
    from .search import DEFAULT_OPERATOR, DEFAULT_SIMILARITY, SIMILARITIES, Searcher
else:
    # Without PyLucene only the pure functions work; main() says where to run the comparison.
    INDEX_DIR = None

OLD_INDEX_DIR = os.path.join("data", "index")
OUT_PATH = os.path.join("data", "lucene", "compare.md")
TOP = 10
SHOWN = 5
# The JVM compiles hot code only after many calls: a round of all Lucene queries gets no faster after
# about 50 rounds, and with 100 warm-up rounds two runs of the tool give medians within 3 % of each other.
WARMUP = 100
REPEATS = 30
# Operator of the second free-text table; the main table uses DEFAULT_OPERATOR.
ALL_WORDS = "and"

# (label, query types, old index query, Lucene query): the six questions, each with a structured Lucene query.
QUESTIONS = (
    # NCSU lists both leaf types for some plants that keep their leaves only in mild winters.
    ("K1-1", "AND, NOT, range", "frost-hardy evergreen trees under 10 m for clay soil",
     "leaf:evergreen AND NOT leaf:deciduous AND plant_type:tree AND height_max_cm:[* TO 1000] AND soil:clay "
     "AND zone_min:[* TO 6]"),
    ("K1-2", "phrase, AND, open range", "Quercus robur wood density and Janka hardness",
     'name:"quercus robur" AND density:[* TO *]'),
    ("K1-3", "AND, range", "trees described by Linnaeus in 1753 that tolerate clay soil, hardy to zone 5",
     "authority:L AND year:[1753 TO 1753] AND soil:clay AND zone_min:[* TO 5] AND plant_type:tree"),
    ("K1-4", "OR, AND, range", "IUCN endangered European trees hardy to zone 6",
     "iucn:(vu OR en OR cr) AND origin:europe AND zone_min:[* TO 6] AND plant_type:tree"),
    ("K1-5", "AND, open range", "which trees have wood denser than 700 kg/m3 and are hardy to zone 6",
     "density:[700 TO *] AND zone_min:[* TO 6]"),
    ("K1-6", "AND, phrase", "drought tolerant shrubs full sun low maintenance",
     'tolerates:drought AND plant_type:shrub AND light:"full sun" AND maintenance:low'),
)
# Characters with a meaning in the Lucene query syntax: "kg/m3" would open a regular expression and
# "denser > 700" would make "denser" a field.
SYNTAX_CHARACTERS = frozenset('\\+-!():^[]"{}~*?|&/<>=@')


def free_text(text):
    """text with the query syntax characters escaped, so that the parser reads it as plain words."""
    return "".join("\\" + char if char in SYNTAX_CHARACTERS else char for char in text)


QUERIES = QUESTIONS + tuple(
    (label + " free", "free text", question, free_text(question)) for label, _kinds, question, _query in QUESTIONS
) + (
    ("free-1", "free text", "drought tolerant shrubs full sun", "drought tolerant shrubs full sun"),
    ("free-2", "free text", "mountain laurel", "mountain laurel"),
    ("free-3", "free text", "japanese maple", "japanese maple"),
    ("free-4", "free text", "quercus robur", "quercus robur"),
    ("not", "NOT", "quercus NOT robur", "quercus NOT robur"),
    ("or", "OR", "oak OR maple", "oak OR maple"),
    ("fuzzy-1", "fuzzy", "quercsu~", "quercsu~"),
    ("fuzzy-2", "fuzzy", "rhododendorn~", "rhododendorn~"),
    ("phrase", "phrase", '"mountain laurel"', '"mountain laurel"'),
)

# A range, or a plain number of a number field (an IntPoint query is a range of one value).
RANGE_CLAUSE_RE = re.compile(r"(\w+):(?:[\[{][^\]}]*[\]}]|(-?\d+))$")


def range_only(query_string):
    """True if the query only joins ranges with AND (NOT): such clauses give every hit the same score."""
    for clause in re.split(r"\s+AND\s+(?:NOT\s+)?", query_string.strip()):
        match = RANGE_CLAUSE_RE.match(clause)
        if not match or (match.group(2) is not None and match.group(1) not in documents.NUMBER_FIELDS):
            return False
    return True


def entity_ids_by_url(entities_dir):
    """{page URL: entity id} of all entities."""
    found = {}
    for entity in documents.read_json_lines(entities_dir):
        for url in documents.entity_urls(entity):
            found[url] = str(entity["entity_id"])
    return found


def timings(tasks, warmup, rounds, clock=time.perf_counter):
    """({key: ms of the first call}, {key: median ms of the timed rounds}) of tasks {key: function}.

    Every round calls every task once; the first warmup rounds are not counted. Interleaving the tasks
    spreads a slow moment of the machine over all of them instead of one query.
    """
    first, times = {}, {key: [] for key in tasks}
    for round_number in range(warmup + rounds):
        for key, function in tasks.items():
            started = clock()
            function()
            elapsed = (clock() - started) * 1000
            first.setdefault(key, elapsed)
            if round_number >= warmup:
                times[key].append(elapsed)
    return first, {key: statistics.median(values) for key, values in times.items()}


def old_run(index, query):
    """Records with score > 0, best first, as (doc_id, score)."""
    return [(doc_id, score) for doc_id, score in index.rank(query) if score > 0]


def lucene_run(searcher, query_string):
    """(total hits, TopDocs of the best TOP): what Searcher.search ranks, without reading stored fields."""
    query = searcher.parse(query_string)
    return searcher.searcher.count(query), searcher.searcher.search(query, TOP)


def measure(old_index, searcher, warmup, rounds):
    """timings() of the old and the Lucene ranking of every distinct query string."""
    tasks = {}
    for _label, _kinds, old_query, new_query in QUERIES:
        tasks.setdefault(("old", old_query), functools.partial(old_run, old_index, old_query))
        tasks.setdefault(("lucene", new_query), functools.partial(lucene_run, searcher, new_query))
    return timings(tasks, warmup, rounds)


def old_entities(index, ranking, url_to_entity):
    """Distinct entity ids of a record ranking, in rank order."""
    found, seen = [], set()
    for doc_id, _score in ranking:
        entity_id = url_to_entity.get(index.docs[doc_id]["url"])
        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            found.append(entity_id)
    return found


def overlap(first, second):
    """'k/n': shared ids of two top lists, n the longer list; '-' when both are empty."""
    first, second = first[:TOP], second[:TOP]
    if not first and not second:
        return "-"
    return "{}/{}".format(len(set(first) & set(second)), max(len(first), len(second)))


def lucene_name(hit):
    name = hit["name"][0] if hit["name"] else hit["key"]
    return "{} ({})".format(name, hit["common_name"][0]) if hit["common_name"] else name


def compare(old_index, searcher, other, all_words, url_to_entity, medians):
    """Report rows of QUERIES; medians from measure(). The result lists are read outside the timing."""
    rows = []
    for label, kinds, old_query, new_query in QUERIES:
        ranking = old_run(old_index, old_query)
        parsed, total, hits = searcher.search(new_query, TOP)
        other_hits = other.search(new_query, TOP)[2]
        _parsed, and_total, and_hits = all_words.search(new_query, TOP)
        old_ids = old_entities(old_index, ranking, url_to_entity)
        new_ids = [hit["id"] for hit in hits]
        rows.append({
            "label": label, "kinds": kinds, "old_query": old_query, "new_query": new_query, "parsed": str(parsed),
            "old_hits": len(ranking), "old_entities": len(old_ids), "new_hits": total,
            "old_ms": medians["old", old_query], "new_ms": medians["lucene", new_query],
            "overlap": overlap(old_ids, new_ids),
            "other_overlap": overlap(new_ids, [hit["id"] for hit in other_hits]),
            "filter_only": range_only(new_query),
            "and_hits": and_total, "and_top": [lucene_name(hit) for hit in and_hits[:SHOWN]],
            "and_overlap": overlap(old_ids, [hit["id"] for hit in and_hits]),
            "old_top": ["{} ({})".format(old_index.docs[doc_id]["scientific_name"], old_index.docs[doc_id]["source"])
                        for doc_id, _score in ranking[:SHOWN]],
            "new_top": [lucene_name(hit) for hit in hits[:SHOWN]],
        })
    return rows


def cell(text):
    return str(text).replace("|", "\\|")


def code(text):
    return "`{}`".format(cell(text)) if text else ""


def short_name(similarity_class):
    """'BM25' for 'BM25Similarity'."""
    return re.sub("Similarity$", "", similarity_class)


def marked(row, value):
    return value + " (ties)" if row["filter_only"] else value


def markdown(rows, meta):
    first, last = QUESTIONS[0][0], QUESTIONS[-1][0]
    escaped = "with {} escaped by a backslash; ".format(meta["escaped"]) if meta["escaped"] else ""
    lines = [
        "# Old index vs. PyLucene index",
        "",
        "Generated {} by `python -m lucene_index.compare` in {:.1f} s (loading {:.1f} s, timing {:.1f} s, "
        "result lists {:.1f} s).".format(meta["generated"], meta["total_s"], meta["load_s"], meta["timing_s"],
                                         meta["results_s"]),
        "",
        "- Old index: `indexer/`, own tf-idf (1 + log10 tf, cosine, classic idf), {} records, "
        "loaded in {:.1f} s.".format(meta["old_n"], meta["old_load_s"]),
        "- PyLucene {}: {} entity documents, {} (the default of `lucene_index.search`), StandardQueryParser "
        "with the default operator {} over {}.".format(meta["lucene"], meta["new_n"], meta["similarity"],
                                                       meta["operator"].upper(), meta["fields"]),
        "- {} to {} are the six questions of the project. In these rows the old index receives the question as "
        "written and Lucene the hand-written structured query of the column Lucene query, so their overlap "
        "shows the query language as much as the index. The rows {} free to {} free give Lucene the same "
        "question as free text ({}the second table runs it with the operator {}), which separates the effect "
        "of the index from that of the structured query. All other rows send the same string to both "
        "indexes.".format(first, last, first, last, escaped, meta["all_words"].upper()),
        "- Free text (words without a field name): the old index matches it in the whole text of a record: "
        "scientific name, common names and synonyms (counted {} times), family, genus, description and the "
        "values of all attributes. Lucene searches it only in the fields listed above, the names, the "
        "descriptions (text) and the Wikipedia lead (wiki); the attribute fields (plant_type, soil, light, "
        "tolerates, ...) and the numbers match only when a query names them.".format(meta["name_boost"]),
        "- The old index has no query operators: its tokenizer drops AND, OR and NOT as stop words and "
        "ignores quotes and `~`, so on the NOT, OR, phrase and fuzzy rows it searches the plain words.",
        "- Hits: old = records with score > 0 (distinct entities in brackets); Lucene = matching entities.",
        "- Overlap: shared entities of the two top {} lists (old records mapped to entities by URL; {} of the "
        "{} old records belong to no entity). {} vs {}: the same Lucene query scored with {}. Lucene lists "
        "hits with equal scores in index order, which is the alphabetical order of the plant keys (the old "
        "index in record order). (ties): the Lucene query has only range clauses, so every hit has the same "
        "score under both similarities and the top {} are the alphabetically first matches; such an overlap "
        "says nothing about the ranking.".format(TOP, meta["unmapped"], meta["old_n"],
                                                 short_name(meta["similarity"]), short_name(meta["other"]),
                                                 meta["other"], TOP),
        "- Time: median of {} timed rounds after {} warm-up rounds, in ms, each round running every query "
        "once on both indexes, so the times are for a warm JVM; the first query of a fresh process is slower "
        "({}: {:.1f} ms in Lucene, {:.1f} ms in the old index). Both sides are timed for the ranking only, "
        "without result rows: the old index tokenizes the query and scores and sorts the records, Lucene "
        "parses the query, counts the hits and collects the top {} doc ids and scores.".format(
            meta["repeats"], meta["warmup"], meta["first_label"], meta["first_new_ms"], meta["first_old_ms"], TOP),
        "",
        "| # | type | old index query | Lucene query | old hits | Lucene hits | old ms | Lucene ms "
        "| top-10 overlap | {} vs {} |".format(short_name(meta["similarity"]), short_name(meta["other"])),
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append("| {} | {} | {} | {} | {} ({}) | {} | {:.2f} | {:.2f} | {} | {} |".format(
            row["label"], row["kinds"], code(row["old_query"]), code(row["new_query"]), row["old_hits"],
            row["old_entities"], row["new_hits"], row["old_ms"], row["new_ms"], marked(row, row["overlap"]),
            marked(row, row["other_overlap"])))
    operator, all_words = meta["operator"].upper(), meta["all_words"].upper()
    lines += ["", "## Free text with the default operator {} (`--operator {}`)".format(all_words, meta["all_words"]),
              "",
              "| # | query | Lucene hits, {} | Lucene hits, {} | top {} with {} | top-10 overlap with old, {} |".format(
                  operator, all_words, SHOWN, all_words, all_words),
              "|---|---|---:|---:|---|---:|"]
    for row in rows:
        if row["kinds"] == "free text":
            lines.append("| {} | {} | {} | {} | {} | {} |".format(
                row["label"], code(row["new_query"]), row["new_hits"], row["and_hits"],
                "; ".join(cell(name) for name in row["and_top"]) or "-", row["and_overlap"]))
    for row in rows:
        lines += ["", "## {}: {}".format(row["label"], cell(row["old_query"])), "",
                  "Lucene: {}  ".format(code(row["new_query"])),
                  "parsed: {}".format(code(row["parsed"])), "",
                  "| rank | old index (record) | Lucene (entity) |", "|---:|---|---|"]
        for rank in range(max(len(row["old_top"]), len(row["new_top"]), 1)):
            old = row["old_top"][rank] if rank < len(row["old_top"]) else ""
            new = row["new_top"][rank] if rank < len(row["new_top"]) else ""
            lines.append("| {} | {} | {} |".format(rank + 1, cell(old) or "-", cell(new) or "-"))
    return "\n".join(lines) + "\n"


def missing_input(args):
    """One line naming the first missing input and the command that creates it; None if all are there."""
    # indexer.build writes meta.json last, so it marks a complete index.
    if not os.path.exists(os.path.join(args.old_index, "meta.json")):
        return "no old index in {}; create it with: python -m indexer.build".format(args.old_index)
    if not glob.glob(os.path.join(args.entities, "part-*")):
        return "no entities in {}; create them with: ./spark_docker.sh sparkjobs.join_wiki".format(args.entities)
    if lucene is None:
        return "PyLucene is not installed here; run the comparison with: ./lucene_docker.sh lucene_index.compare"
    if not glob.glob(os.path.join(args.index, "segments_*")):
        return "no Lucene index in {}; create it with: ./lucene_docker.sh lucene_index.build".format(args.index)
    return None


def fail(message):
    print("lucene_index.compare: " + message, file=sys.stderr)
    return 2


def free_text_fields(searcher):
    """'name^0.4, common_name^0.3, ...': the fields and boosts the parser gives a word without a field."""
    parsed = str(searcher.parse("oak"))
    fields = re.findall(r"(\w+):oak\)?(?:\^([\d.]+))?", parsed)
    return ", ".join(field + ("^" + boost if boost else "") for field, boost in fields) or parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare the old tf-idf index with the PyLucene index")
    parser.add_argument("--old-index", default=OLD_INDEX_DIR)
    parser.add_argument("--index", default=INDEX_DIR)
    parser.add_argument("--entities", default=documents.ENTITIES_DIR)
    parser.add_argument("--out", default=OUT_PATH)
    parser.add_argument("--repeats", type=int, default=REPEATS, help="timed rounds of every query (median)")
    parser.add_argument("--warmup", type=int, default=WARMUP, help="untimed rounds of every query before timing")
    args = parser.parse_args(argv)
    message = missing_input(args)
    if message:
        return fail(message)

    started = time.perf_counter()
    old_index = old_search.Index(args.old_index)
    old_load_s = time.perf_counter() - started
    other = sorted(name for name in SIMILARITIES if name != DEFAULT_SIMILARITY)[0]
    try:
        searchers = (Searcher(args.index, DEFAULT_SIMILARITY, DEFAULT_OPERATOR),
                     Searcher(args.index, other, DEFAULT_OPERATOR),
                     Searcher(args.index, DEFAULT_SIMILARITY, ALL_WORDS))
    except lucene.JavaError as error:
        java_error = error.getJavaException()
        return fail("cannot open the Lucene index in {} ({}); rebuild it with: ./lucene_docker.sh "
                    "lucene_index.build".format(args.index, (java_error.getMessage() or java_error.toString()).strip()))
    url_to_entity = entity_ids_by_url(args.entities)
    unmapped = sum(1 for doc in old_index.docs if doc["url"] not in url_to_entity)
    if unmapped:
        print("warning: {} old index records have no entity".format(unmapped))
    loaded = time.perf_counter()

    warmup, repeats = max(args.warmup, 0), max(args.repeats, 1)
    first_ms, medians = measure(old_index, searchers[0], warmup, repeats)
    timed = time.perf_counter()
    rows = compare(old_index, *searchers, url_to_entity, medians)
    finished = time.perf_counter()

    first_label, _kinds, first_old, first_new = QUERIES[0]
    escaped = sorted({char for _label, _kinds, question, _query in QUESTIONS for char in question
                      if char in SYNTAX_CHARACTERS})
    meta = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "total_s": finished - started, "load_s": loaded - started, "timing_s": timed - loaded,
            "results_s": finished - timed, "old_n": old_index.n, "old_load_s": old_load_s,
            "name_boost": old_index.meta["options"]["name_boost"], "unmapped": unmapped,
            "lucene": lucene.VERSION, "new_n": searchers[0].searcher.getIndexReader().numDocs(),
            "similarity": SIMILARITIES[DEFAULT_SIMILARITY].__name__, "other": SIMILARITIES[other].__name__,
            "operator": DEFAULT_OPERATOR, "all_words": ALL_WORDS, "fields": free_text_fields(searchers[0]),
            "escaped": " and ".join("`{}`".format(char) for char in escaped), "warmup": warmup, "repeats": repeats,
            "first_label": first_label, "first_new_ms": first_ms["lucene", first_new],
            "first_old_ms": first_ms["old", first_old]}
    report = markdown(rows, meta)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(report)
    for searcher in searchers:
        searcher.close()
    print(report)


if __name__ == "__main__":
    sys.exit(main())
