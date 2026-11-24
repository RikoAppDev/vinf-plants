"""Tests of the PyLucene index on a tiny hand-made index; skipped where PyLucene is not installed.

Run them in the PyLucene image: ./lucene_docker.sh unittest tests.test_lucene_index
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from lucene_index import documents
from tests.test_lucene_querycheck import search_docstring_examples

try:
    import lucene
except ImportError:
    lucene = None

if lucene:
    from lucene_index import build, search


def doc(entity_id, **fields):
    """A lucene_index.documents dict with only the given fields filled in."""
    result = {field: None if field in documents.NUMBER_FIELDS else [] for field in documents.FIELDS}
    result.update(id=[str(entity_id)], key=[fields["name"][0].lower()], n_sources=len(fields.get("source", [])))
    result.update(fields)
    return result


DOCS = [
    doc(1, name=["Quercus robur"], common_name=["English oak", "Pedunculate oak"], synonym=["Quercus pedunculata"],
        family=["Fagaceae"], genus=["Quercus"], authority=["L. (1753)"], plant_type=["Tree"], leaf=["Deciduous"],
        soil=["Clay", "Loam"], light=["Full sun"], origin=["Europe"],
        text=["A large deciduous tree that tolerates clay."], wiki=["Quercus robur is a species of oak."],
        source=["ncsu", "pfaf", "tso", "wooddb"], iucn=["lc"], year=1753, zone_min=4, zone_max=8,
        height_max_cm=3500, density=675, janka=4980, url=["https://pfaf.org/x"], wiki_title=["Quercus robur"]),
    doc(2, name=["Quercus alba"], common_name=["White oak"], authority=["L."], plant_type=["Tree"], soil=["Sand"],
        origin=["Eastern North America"], text=["A long-lived tree."], source=["ncsu", "wooddb"], iucn=["lc"],
        year=1753, zone_min=3, zone_max=9, density=755),
    doc(3, name=["Kalmia latifolia"], common_name=["Mountain laurel", "Calico bush"], authority=["L."],
        plant_type=["Shrub"], leaf=["Broadleaf Evergreen"], light=["Partial Shade"],
        text=["An evergreen shrub that is tolerant of shade."], source=["ncsu", "tso"], year=1753, zone_min=4,
        zone_max=9),
    doc(4, name=["Abies nebrodensis"], common_name=["Sicilian fir"], authority=["(Lojac.) Mattei"],
        plant_type=["tree"], origin=["Sicily"], source=["tso"], iucn=["cr"], year=1908, zone_min=7, zone_max=9),
    doc(5, name=["Acer palmatum"], common_name=["Japanese maple"], authority=["Thunb."], plant_type=["Tree", "Shrub"],
        text=["It grows in mountain shade; laurel hedges nearby."], source=["pfaf"], year=1784, zone_min=5,
        zone_max=8),
    # Without a position gap the two names would read "rocky mountain laurel sumac".
    doc(6, name=["Rhus copallinum"], common_name=["Rocky Mountain", "Laurel sumac"], source=["pfaf"]),
    doc(7, name=["Rhododendron ponticum"], common_name=["Common rhododendron"], source=["pfaf", "tso"],
        iucn=["en"], zone_min=6, zone_max=9),
    doc(8, name=["Fagus sylvatica"], common_name=["Beech"], authority=["L.f."], source=["ncsu"]),
    doc(9, name=["Nothofagus antarctica"], wiki=["Beech"], source=["tso"]),
    doc(10, name=["Abelia × grandiflora"], common_name=["Lady of the Lake"], leaf=["Semi-evergreen"],
        source=["ncsu"]),
    doc(11, name=["Cornus sericea"], common_name=["Red osier dogwood"], authority=["L."], plant_type=["Shrub"],
        soil=["Clay"], landscape=["Garden for the Blind"], source=["ncsu"], year=1771, zone_min=2, zone_max=7),
]


# The species, two of its subspecies and cultivars whose synonyms repeat its name, as in the real index.
KEY_DOCS = [
    doc(1, name=["Acer palmatum"], key=["acer palmatum"], common_name=["Japanese maple"], source=["pfaf"]),
    doc(2, name=["Acer palmatum subsp. matsumurae"], key=["acer palmatum subsp matsumurae"],
        synonym=["Acer palmatum var. matsumurae", "Acer matsumurae"], source=["tso"]),
    doc(3, name=["Acer palmatum 'Seiryu'"], key=["acer palmatum seiryu"],
        synonym=["Acer palmatum Dissectum Group 'Seiryu'"], source=["ncsu"]),
    doc(4, name=["Acer campestre"], key=["acer campestre"], common_name=["Field maple"], source=["pfaf"]),
    doc(5, name=["Kalmia latifolia"], key=["kalmia latifolia"], common_name=["Mountain laurel"], source=["ncsu"]),
]


def tokens(analyzer, text):
    from org.apache.lucene.analysis.tokenattributes import CharTermAttribute
    stream = analyzer.tokenStream("field", text)
    term = stream.addAttribute(CharTermAttribute.class_)
    stream.reset()
    found = []
    while stream.incrementToken():
        found.append(term.toString())
    stream.end()
    stream.close()
    return found


def index_ids(folder):
    """Sorted ids of all documents of the index in folder."""
    from java.nio.file import Paths
    from org.apache.lucene.index import DirectoryReader
    from org.apache.lucene.store import FSDirectory
    directory = FSDirectory.open(Paths.get(folder))
    reader = DirectoryReader.open(directory)
    try:
        stored = reader.storedFields()
        return sorted(int(stored.document(doc_id).get("id")) for doc_id in range(reader.maxDoc()))
    finally:
        reader.close()
        directory.close()


def norms(folder):
    """{(field, doc): norm} of the text fields of the index in folder."""
    from java.nio.file import Paths
    from org.apache.lucene.index import DirectoryReader, LeafReaderContext
    from org.apache.lucene.store import FSDirectory
    directory = FSDirectory.open(Paths.get(folder))
    reader = DirectoryReader.open(directory)
    try:
        leaf = LeafReaderContext.cast_(reader.leaves().get(0)).reader()
        found = {}
        for field in documents.TEXT_FIELDS:
            values = leaf.getNormValues(field)
            for doc_id in range(leaf.maxDoc()):
                if values is not None and values.advanceExact(doc_id):
                    found[field, doc_id] = values.longValue()
        return found
    finally:
        reader.close()
        directory.close()


def spark_output(root):
    """(entities folder, records folder) of a one-plant Spark output under root."""
    entities, records = os.path.join(root, "entities"), os.path.join(root, "records")
    os.makedirs(entities)
    with open(os.path.join(entities, "part-00000"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"entity_id": 1, "key": "quercus robur", "scientific_names": ["Quercus robur"],
                                 "sources": {"pfaf": ["https://pfaf.org/x"]}}) + "\n")
    for site in documents.SITES:
        os.makedirs(os.path.join(records, site))
        with open(os.path.join(records, site, "part-00000"), "w", encoding="utf-8") as handle:
            if site == "pfaf":
                handle.write(json.dumps({"url": "https://pfaf.org/x", "source": "pfaf",
                                         "scientific_name": "Quercus robur", "common_names": ["English oak"]}) + "\n")
    return entities, records


def run_main(main, argv):
    """(return code, stdout, stderr) of a command line main; SystemExit gives its code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(lucene, "PyLucene is not installed (run ./lucene_docker.sh unittest tests.test_lucene_index)")
class LuceneIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build.start_vm()
        cls.folder = tempfile.mkdtemp(prefix="vinf-lucene-")
        cls.counts = build.build_index(DOCS, cls.folder)
        cls.searcher = search.Searcher(cls.folder)

    @classmethod
    def tearDownClass(cls):
        cls.searcher.close()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="vinf-lucene-test-")
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def ids(self, query_string, searcher=None):
        _query, total, hits = (searcher or self.searcher).search(query_string, top=20)
        self.assertEqual(total, len(hits))
        return [int(hit["id"]) for hit in hits]

    def assertMatches(self, query_string, expected):
        self.assertEqual(sorted(self.ids(query_string)), sorted(expected), query_string)

    def test_every_document_and_value_is_indexed(self):
        self.assertEqual(self.searcher.reader.numDocs(), len(DOCS))
        # Documents with a value and number of values, counted while indexing.
        self.assertEqual((self.counts["common_name", "documents"], self.counts["common_name", "values"]), (10, 13))
        self.assertEqual((self.counts["year", "documents"], self.counts["year", "values"]), (6, 6))
        self.assertEqual((self.counts["url", "documents"], self.counts["origin", "values"]), (1, 3))
        terms, segments = build.term_stats(self.folder)
        self.assertEqual(segments, 1)
        self.assertEqual(terms["source"][0], 4)
        self.assertEqual(terms["soil"], (3, 4))

    def test_boolean_and_or_not(self):
        self.assertMatches("soil:clay AND plant_type:tree", [1])
        self.assertMatches("name:alba OR name:palmatum", [2, 5])
        self.assertMatches("quercus NOT robur", [2])
        self.assertMatches("+quercus -robur", [2])
        self.assertMatches("plant_type:tree AND NOT source:wooddb", [4, 5])
        self.assertMatches("(name:alba OR name:robur) AND soil:sand", [2])

    def test_phrase_does_not_cross_two_values(self):
        self.assertMatches('"mountain laurel"', [3])
        self.assertMatches('light:"full sun"', [1])
        self.assertMatches("mountain laurel", [3, 5, 6])

    def test_fuzzy(self):
        self.assertMatches("quercsu~", [1, 2])
        self.assertMatches("rhododendorn~", [7])
        self.assertMatches("quercsu", [])

    def test_wildcard(self):
        self.assertMatches("querc*", [1, 2])
        self.assertMatches("name:RHODO*", [7])

    def test_numeric_ranges_with_open_bounds(self):
        self.assertMatches("year:[1754 TO 1800]", [5, 11])
        self.assertMatches("year:1753", [1, 2, 3])
        self.assertMatches("year>1800", [4])
        self.assertMatches("zone_min:[* TO 4]", [1, 2, 3, 11])
        self.assertMatches("density:[700 TO *]", [2])
        self.assertMatches("density:{675 TO *]", [2])
        self.assertMatches("density:[* TO *]", [1, 2])
        self.assertMatches("plant_type:tree AND zone_min:[* TO 5] AND authority:L", [1, 2])
        # A negative number is escaped or written in a range.
        self.assertMatches("zone_min:[\\-5 TO 4]", [1, 2, 3, 11])
        self.assertMatches("zone_min:[-5 TO 2]", [11])
        self.assertMatches("zone_min<=\\-1", [])

    def test_authority_l_is_linnaeus_not_his_son(self):
        self.assertMatches("authority:L", [1, 2, 3, 11])

    def test_string_fields_match_exactly(self):
        self.assertMatches("iucn:en", [7])
        self.assertMatches("iucn:EN", [7])
        self.assertMatches("iucn:(vu OR en OR cr)", [4, 7])
        self.assertMatches("source:tso", [1, 3, 4, 7, 9])
        self.assertMatches('key:"quercus robur"', [1])

    def test_semi_evergreen_is_one_word_in_the_index_and_in_a_query(self):
        self.assertMatches("leaf:evergreen", [3])
        self.assertMatches("leaf:semi-evergreen", [10])
        self.assertMatches('leaf:"Semi-evergreen"', [10])
        self.assertMatches("leaf:semievergreen", [10])
        hit = self.searcher.search("id:10")[2][0]
        stored = self.searcher.searcher.storedFields().document(hit["doc"])
        self.assertEqual(list(stored.getValues("leaf")), ["Semi-evergreen"])

    def test_tag_fields_are_no_default_fields_and_keep_their_stop_words(self):
        self.assertFalse({field for field, _boost in search.DEFAULT_FIELDS} & set(documents.TAG_FIELDS))
        self.assertMatches('landscape:"garden for the blind"', [11])
        self.assertMatches("landscape:the", [11])
        all_words = search.Searcher(self.folder, operator="and")
        try:
            self.assertEqual(self.ids("landscape:(garden for the blind)", all_words), [11])
        finally:
            all_words.close()

    def test_field_boosts_scale_the_scores(self):
        from java.util import HashMap
        unboosted = search.query_parser()
        unboosted.setFieldsBoost(HashMap())

        def scores(query):
            stored = self.searcher.searcher.storedFields()
            return {stored.document(hit.doc).get("id"): hit.score
                    for hit in self.searcher.searcher.search(query, 10).scoreDocs}

        boosted, plain = scores(self.searcher.parse("beech")), scores(unboosted.parse("beech", None))
        self.assertEqual(sorted(boosted), ["8", "9"])
        self.assertAlmostEqual(boosted["8"] / plain["8"], 0.3, places=5)
        self.assertAlmostEqual(boosted["9"] / plain["9"], 0.1, places=5)
        self.assertEqual(self.ids("common_name:beech OR wiki:beech^10"), [9, 8])

    def test_stored_values(self):
        _query, _total, hits = self.searcher.search("id:1")
        hit = hits[0]
        self.assertEqual(hit["name"], ["Quercus robur"])
        self.assertEqual(hit["source"], ["ncsu", "pfaf", "tso", "wooddb"])
        self.assertEqual((hit["year"], hit["zone_min"], hit["density"], hit["janka"]), (1753, 4, 675, 4980))
        self.assertIsNone(hit["edibility"])
        self.assertEqual(hit["url"], ["https://pfaf.org/x"])
        self.assertEqual(hit["wiki_title"], "Quercus robur")
        self.assertEqual((hit["synonym"], hit["genus"]), (["Quercus pedunculata"], ["Quercus"]))
        self.assertEqual((hit["soil"], hit["light"], hit["leaf"]), (["Clay", "Loam"], ["Full sun"], ["Deciduous"]))
        self.assertEqual(hit["origin"], ["Europe"])
        stored = self.searcher.searcher.storedFields().document(hit["doc"])
        self.assertIsNone(stored.get("text"))
        self.assertEqual(list(stored.getValues("origin")), ["Europe"])

    def test_operator_and_requires_every_word(self):
        self.assertMatches("english oak", [1, 2])
        all_words = search.Searcher(self.folder, operator="and")
        try:
            self.assertEqual(self.ids("english oak", all_words), [1])
            self.assertEqual(sorted(self.ids("english OR sicilian", all_words)), [1, 4])
            # A stop word is no required word, also not in the name fields.
            self.assertEqual(self.ids("oak for clay", all_words), [1])
            self.assertEqual(self.ids("lady of the lake", all_words), [10])
            self.assertEqual(self.ids('"lady of the lake"', all_words), [10])
        finally:
            all_words.close()

    def test_bm25_is_the_default_at_index_and_search_time(self):
        self.assertEqual(search.DEFAULT_SIMILARITY, "bm25")
        self.assertEqual(self.searcher.searcher.getSimilarity().getClass().getSimpleName(), "BM25Similarity")
        query, _total, hits = self.searcher.search("oak")
        self.assertIn("[BM25Similarity]", self.searcher.explain(query, hits[0]["doc"]))
        classic = search.Searcher(self.folder, "classic")
        try:
            query, _total, hits = classic.search("oak")
            self.assertIn("[ClassicSimilarity]", classic.explain(query, hits[0]["doc"]))
        finally:
            classic.close()

    def test_both_similarities_write_the_same_norms(self):
        build.build_index(DOCS, self.scratch, similarity="classic")
        found = norms(self.scratch)
        self.assertGreater(len(found), 20)
        self.assertEqual(found, norms(self.folder))

    def test_bm25_counts_many_matches_in_a_long_text_where_classic_does_not(self):
        # Classic divides by sqrt(field length), so 20 matches in a text of 300 words weigh less than one
        # match in a two-word common name; BM25 saturates tf and compares the length with the average.
        ranking_docs = [
            doc(1, name=["Quercus robur"], text=["Oak woodland. " * 20 + "Bark " * 260]),
            doc(2, name=["Quercus rubra"], common_name=["Red oak"]),
            doc(3, name=["Acer campestre"], common_name=["Field maple"], text=["A small tree."]),
            doc(4, name=["Fagus sylvatica"], common_name=["Beech"], text=["A large tree."]),
        ]
        build.build_index(ranking_docs, self.scratch)
        bm25, classic = search.Searcher(self.scratch), search.Searcher(self.scratch, "classic")
        try:
            self.assertEqual(self.ids("oak", bm25), [1, 2])
            self.assertEqual(self.ids("oak", classic), [2, 1])
        finally:
            bm25.close()
            classic.close()

    def test_a_failed_rebuild_keeps_the_previous_index(self):
        build.build_index(DOCS, self.scratch)
        broken = dict(DOCS[2])
        del broken["text"]
        with self.assertRaises(KeyError):
            build.build_index([DOCS[0], DOCS[1], broken], self.scratch)
        self.assertEqual(index_ids(self.scratch), list(range(1, len(DOCS) + 1)))

        def interrupted():
            yield DOCS[0]
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            build.build_index(interrupted(), self.scratch)
        with self.assertRaises(ValueError):
            build.build_index([], self.scratch)
        self.assertEqual(index_ids(self.scratch), list(range(1, len(DOCS) + 1)))

    def test_build_command_line_writes_the_index_and_its_statistics(self):
        entities, records = spark_output(self.scratch)
        out, stats_path = os.path.join(self.scratch, "index"), os.path.join(self.scratch, "stats.json")
        code, output, errors = run_main(build.main, ["--entities", entities, "--records", records, "--out", out,
                                                     "--stats", stats_path])
        self.assertIn(code, (None, 0), errors)
        self.assertEqual(index_ids(out), [1])
        with open(stats_path, encoding="utf-8") as handle:
            stats = json.load(handle)
        self.assertEqual((stats["documents"], stats["similarity"]), (1, "BM25Similarity"))
        self.assertLessEqual(stats["build_seconds"] + stats["read_seconds"], 60)
        self.assertIn("1 documents", output)

    def test_build_stops_on_missing_input_before_it_touches_the_index(self):
        entities, records = spark_output(self.scratch)
        empty = os.path.join(self.scratch, "empty")
        os.makedirs(empty)
        no_tso = os.path.join(self.scratch, "no_tso")
        shutil.copytree(records, no_tso)
        shutil.rmtree(os.path.join(no_tso, "tso"))
        missing = os.path.join(self.scratch, "missing")
        out, stats_path = os.path.join(self.scratch, "index"), os.path.join(self.scratch, "stats.json")
        for entities_dir, records_dir, named in ((missing, records, missing), (empty, records, empty),
                                                 (entities, missing, os.path.join(missing, "ncsu")),
                                                 (entities, no_tso, os.path.join(no_tso, "tso"))):
            code, _output, errors = run_main(build.main, ["--entities", entities_dir, "--records", records_dir,
                                                          "--out", out, "--stats", stats_path])
            self.assertEqual(code, 2)
            self.assertEqual(len(errors.strip().splitlines()), 1, errors)
            self.assertIn(named, errors)
            self.assertIn("MANUAL.md", errors)
            self.assertIn("./lucene_docker.sh lucene_index.build", errors)
            self.assertFalse(os.path.exists(out))
            self.assertFalse(os.path.exists(stats_path))
        with open(os.path.join(entities, "part-00000"), "w", encoding="utf-8"):
            pass
        code, _output, errors = run_main(build.main, ["--entities", entities, "--records", records, "--out", out,
                                                      "--stats", stats_path])
        self.assertEqual(code, 2)
        self.assertIn("no documents", errors)
        self.assertFalse(os.path.exists(out))

    def test_query_errors_are_plain_text(self):
        cases = {
            "color:red": "unknown field color; did you mean flower_color?",
            "year:17abc": "year takes whole numbers",
            "year:[1754 TO": "a range is not closed",
            '"mountain laurel': 'a quote " is not closed',
            "(quercus OR robur": "a parenthesis ( is not closed",
            "*oak": "leading wildcard",
            "year:[1754 1800]": "[low TO high]",
            "name:robur^" + "9" * 41: "boost must be a positive float",
            "text:/[a/": "expected ']'",
            " ".join("w{}".format(number) for number in range(300)): "more than 1024",
            "text:/[ab]*a[ab]{30}/": "too complex",
            # The flexible parser fails on these with a ClassCastException.
            "*<o": "* is no field name",
            "oak AND *<o": "* is no field name",
            "*:{* TO *}": "* is no field name",
        }
        for query_string, part in cases.items():
            with self.assertRaises(search.QueryError) as caught:
                self.searcher.search(query_string)
            self.assertIsInstance(caught.exception, ValueError)
            self.assertIn(part, str(caught.exception), query_string)
            self.assertLessEqual(len(str(caught.exception).splitlines()), 2)
            with self.assertRaises(search.QueryError):
                search.search(query_string, index_dir=self.folder)
        with self.assertRaises(search.QueryError) as caught:
            self.searcher.parse("year:[1754 TO")
        self.assertEqual(caught.exception.lucene_message, "Syntax Error, cannot parse year:[1754 TO:")
        self.assertIn("a range is not closed", caught.exception.explanation)

    def test_a_wildcard_interval_with_too_many_words_is_a_query_error(self):
        build.build_index([doc(1, name=["Quercus robur"], text=[" ".join("q{}".format(n) for n in range(200))])],
                          self.scratch)
        searcher = search.Searcher(self.scratch)
        try:
            self.assertEqual(searcher.search("fn:wildcard(q1*)")[1], 1)
            for query_string in ("fn:wildcard(q*)", "fn:or(robur fn:wildcard(q*))"):
                with self.assertRaises(search.QueryError) as caught:
                    searcher.search(query_string)
                self.assertIn("more than 128 words", caught.exception.explanation)
                self.assertIn("longer prefix", caught.exception.explanation)
                self.assertIn("expanded to too many terms", caught.exception.lucene_message)
        finally:
            searcher.close()

    def test_stop_word_fields_of_querycheck_are_the_ones_of_the_analyzers(self):
        from lucene_index import querycheck
        self.assertEqual(set(querycheck.STOP_WORD_FIELDS), set(build.ENGLISH_FIELDS + build.STOP_NAME_FIELDS))
        self.assertLessEqual({field for field, _boost in search.DEFAULT_FIELDS}, set(querycheck.STOP_WORD_FIELDS))

    def test_unexpected_java_errors_still_propagate(self):
        closed = search.Searcher(self.folder)
        closed.close()
        with self.assertRaises(lucene.JavaError) as caught:
            closed.search("oak")
        self.assertNotIsInstance(caught.exception, search.QueryError)
        with self.assertRaises(lucene.JavaError):
            closed.directory.listAll()

    def test_search_rewrites_the_query_once_and_returns_it_parsed(self):
        class Recorder:
            def __init__(self, searcher):
                self.searcher, self.queries = searcher, []

            def __getattr__(self, name):
                return getattr(self.searcher, name)

            def count(self, query):
                self.queries.append(query.toString())
                return self.searcher.count(query)

            def search(self, query, top):
                self.queries.append(query.toString())
                return self.searcher.search(query, top)

        recorded = search.Searcher(self.folder)
        try:
            for query_string in ("quercsu~", "querc*", "quercus NOT robur", "mountain OR laurel"):
                parsed = recorded.parse(query_string)
                total = recorded.searcher.count(parsed)
                top = [(score_doc.doc, score_doc.score) for score_doc in recorded.searcher.search(parsed, 10).scoreDocs]
                rewritten = recorded.searcher.rewrite(parsed).toString()
                recorded.searcher = Recorder(recorded.searcher)
                query, found, hits = recorded.search(query_string)
                self.assertEqual(recorded.searcher.queries, [rewritten, rewritten], query_string)
                recorded.searcher = recorded.searcher.searcher
                self.assertEqual(query.toString(), parsed.toString())
                self.assertEqual(found, total)
                self.assertEqual([(hit["doc"], hit["score"]) for hit in hits], top)
            self.assertIn("quercsu~2", recorded.search("quercsu~")[0].toString())
        finally:
            recorded.close()

    def test_name_key_is_the_entity_key_of_the_query(self):
        self.assertEqual(search.name_key("acer palmatum"), "acer palmatum")
        self.assertEqual(search.name_key("Acer palmatum 'Seiryu'"), "acer palmatum seiryu")
        self.assertEqual(search.name_key("acer palmatum subsp. matsumurae"), "acer palmatum subsp matsumurae")
        self.assertEqual(search.name_key("olearia × scilloniensis"), "olearia × scilloniensis")
        self.assertEqual(search.name_key("hyacinthoides non\\-scripta"), "hyacinthoides non-scripta")
        self.assertEqual(search.name_key("QUERCUS"), "quercus")
        self.assertEqual(search.name_key("12 34"), "")

    def test_a_plant_name_puts_the_plant_with_that_key_first(self):
        build.build_index(KEY_DOCS, self.scratch)

        def ranking(searcher, query):
            return [(score_doc.doc, score_doc.score) for score_doc in searcher.searcher.search(query, 10).scoreDocs]

        for similarity in sorted(search.SIMILARITIES):
            for operator in search.OPERATORS:
                searcher = search.Searcher(self.scratch, similarity, operator)
                try:
                    parser = search.query_parser(operator)
                    for query_string, key_id in (("acer palmatum", 1), ("Acer palmatum 'Seiryu'", 3)):
                        plain = parser.parse(query_string, None)
                        before = [doc_id for doc_id, _score in ranking(searcher, plain)]
                        query, total, hits = searcher.search(query_string)
                        label = "{} {} {}".format(similarity, operator, query_string)
                        self.assertEqual(int(hits[0]["id"]), key_id, label)
                        self.assertEqual(total, searcher.searcher.count(plain), label)
                        self.assertEqual(sorted(hit["doc"] for hit in hits), sorted(before), label)
                        self.assertIn("key:" + search.name_key(query_string), query.toString())
                        self.assertEqual(searcher.parse(query_string).toString(), query.toString())
                    # Without the clause the species is behind its subspecies and cultivars.
                    self.assertNotEqual(ranking(searcher, parser.parse("acer palmatum", None))[0][0], 0)
                    for query_string in ("mountain laurel", "maple", "acer AND palmatum", '"acer palmatum"',
                                         "name:(acer palmatum)", "acer palmatum^2"):
                        query = searcher.parse(query_string)
                        self.assertNotIn("key:", query.toString(), query_string)
                        self.assertEqual(ranking(searcher, query), ranking(searcher, parser.parse(query_string, None)))
                finally:
                    searcher.close()

    def test_every_docstring_example_returns_hits(self):
        examples = search_docstring_examples()
        self.assertGreaterEqual(len(examples), 20)
        for example in examples:
            self.assertGreater(self.searcher.search(example)[1], 0, example)

    def test_index_exists(self):
        self.assertTrue(search.index_exists(self.folder))
        self.assertFalse(search.index_exists(self.scratch))
        self.assertFalse(search.index_exists(os.path.join(self.scratch, "missing")))

    def test_cli_names_the_build_command_for_a_folder_without_an_index(self):
        code, output, errors = run_main(search.main, ["oak", "--index", self.scratch])
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertEqual(len(errors.strip().splitlines()), 1, errors)
        self.assertIn("./lucene_docker.sh lucene_index.build", errors)
        self.assertNotIn("python -m", errors)

    def test_cli_prints_a_query_error_on_one_or_two_lines(self):
        code, output, errors = run_main(search.main, ["year:[1754 TO", "--index", self.folder])
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertEqual(errors.splitlines(), ["error: a range is not closed: write it as [low TO high], for example "
                                               "year:[1754 TO 1800]",
                                               "Lucene: Syntax Error, cannot parse year:[1754 TO:"])
        code, output, errors = run_main(search.main, ["color:red", "--index", self.folder])
        self.assertEqual((code, output), (2, ""))
        self.assertEqual(errors, "error: unknown field color; did you mean flower_color?\n")

    def test_cli_prints_notes_to_stderr(self):
        code, output, errors = run_main(search.main, ["quercus not robur", "--index", self.folder])
        self.assertIn(code, (None, 0))
        self.assertIn("note: ", errors)
        self.assertIn("AND, OR, NOT", errors)
        self.assertIn("Quercus robur", output)

    def test_cli_shows_why_a_filter_matched_and_labels_the_time(self):
        code, output, errors = run_main(search.main, ["soil:clay AND origin:europe", "--index", self.folder])
        self.assertIn(code, (None, 0), errors)
        self.assertIn("soil: Clay, Loam | origin: Europe", output)
        self.assertIn("ms (first query in a fresh JVM), BM25 similarity", output)
        code, output, errors = run_main(search.main, ["oak", "--similarity", "classic", "--index", self.folder])
        self.assertIn("classic tf-idf similarity", output)

    def test_cli_cuts_long_values(self):
        line = search.matched_text({"origin": ["x" * 200], "soil": ["Clay"], "year": 1753, "text": []},
                                   ["origin", "year", "text", "soil"])
        self.assertLessEqual(len(line), 120)
        self.assertTrue(line.startswith("origin: xxx"))
        self.assertIn("... | year: 1753 | soil: Clay", line)

    def test_cli_prints_a_single_zone(self):
        hit = {field: None for field in documents.NUMBER_FIELDS}
        hit.update(iucn=[], zone_min=8)
        self.assertEqual(search.numbers_text(hit), "zone 8")
        hit.update(zone_max=9, year=1753)
        self.assertEqual(search.numbers_text(hit), "zone 8-9, year 1753")

    def test_cli_options(self):
        code, _output, errors = run_main(search.main, ["oak", "--top", "0", "--index", self.folder])
        self.assertEqual(code, 2)
        self.assertIn("--top", errors)
        code, output, _errors = run_main(search.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn('-- "-robur quercus"', output)
        code, output, _errors = run_main(search.main, ["--index", self.folder, "--", "-robur quercus"])
        self.assertIn(code, (None, 0))
        self.assertIn("Quercus alba", output)

    def test_a_jvm_crash_log_goes_to_tmp(self):
        with mock.patch.object(build.lucene, "getVMEnv", return_value=None), \
                mock.patch.object(build.lucene, "initVM") as init_vm:
            build.start_vm()
        self.assertIn("-XX:ErrorFile=/tmp/hs_err_pid%p.log", init_vm.call_args[1]["vmargs"])

    def test_analyzers_match_the_lucene_ones_and_keep_values_apart(self):
        from org.apache.lucene.analysis.en import EnglishAnalyzer
        from org.apache.lucene.analysis.standard import StandardAnalyzer
        text = "The Tree's leaves tolerate drought; semi-evergreen, L. (1753), Hook.f. running quickly"
        self.assertEqual(tokens(build.standard_analyzer(), text), tokens(StandardAnalyzer(), text))
        self.assertEqual(tokens(build.english_analyzer(), text), tokens(EnglishAnalyzer(), text))
        self.assertEqual(tokens(build.name_analyzer(), "Lady of the Lake"), ["lady", "lake"])
        self.assertEqual(build.analyzer().getPositionIncrementGap("common_name"), build.POSITION_GAP)


if __name__ == "__main__":
    unittest.main()
