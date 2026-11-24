"""Tests of the comparison of the old index with the PyLucene index.

The pure functions run everywhere; the end-to-end run on a tiny old index and a tiny Lucene index needs
PyLucene: ./lucene_docker.sh unittest tests.test_lucene_compare
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import types
import unittest

from indexer import build as old_build
from lucene_index import compare, documents

try:
    import lucene
except ImportError:
    lucene = None

if lucene:
    from lucene_index import build, search


def lucene_doc(entity_id, **fields):
    """A lucene_index.documents dict with only the given fields filled in."""
    result = {field: None if field in documents.NUMBER_FIELDS else [] for field in documents.FIELDS}
    result.update(id=[str(entity_id)], key=[fields["name"][0].lower()], n_sources=len(fields.get("source", [])))
    result.update(fields)
    return result


# Old records of four pages: two pages of Quercus robur (one entity), one of Quercus alba and one of
# Kalmia latifolia; the Malus page belongs to no entity.
OLD_RECORDS = {
    "ncsu": [
        {"url": "https://ncsu.example/quercus-robur", "scientific_name": "Quercus robur",
         "common_names": ["English Oak"], "description": "A large deciduous tree for clay soil.",
         "attributes": {"Plant Type": ["Tree"], "Soil Texture": ["Clay"]}},
        {"url": "https://ncsu.example/quercus-alba", "scientific_name": "Quercus alba",
         "common_names": ["White Oak"], "description": "A long-lived tree of dry soil.",
         "attributes": {"Plant Type": ["Tree"]}},
        {"url": "https://ncsu.example/kalmia-latifolia", "scientific_name": "Kalmia latifolia",
         "common_names": ["Mountain Laurel"], "description": "An evergreen shrub for shade.",
         "attributes": {"Plant Type": ["Shrub"], "Light": ["Partial Shade"]}},
    ],
    "pfaf": [
        {"url": "https://pfaf.example/quercus-robur", "scientific_name": "Quercus robur",
         "common_names": ["Pedunculate Oak"], "description": "Oak wood is hard and dense.", "attributes": {}},
    ],
    "tso": [
        {"url": "https://tso.example/malus-domestica", "scientific_name": "Malus domestica",
         "common_names": ["Apple"], "description": "A fruit tree.", "attributes": {}},
    ],
}
ENTITIES = [
    {"entity_id": 1, "key": "quercus robur",
     "sources": {"ncsu": ["https://ncsu.example/quercus-robur"], "pfaf": ["https://pfaf.example/quercus-robur"]}},
    {"entity_id": 2, "key": "quercus alba", "sources": {"ncsu": ["https://ncsu.example/quercus-alba"]}},
    {"entity_id": 3, "key": "kalmia latifolia", "sources": {"ncsu": ["https://ncsu.example/kalmia-latifolia"]}},
]
LUCENE_DOCS = [
    lucene_doc(1, name=["Quercus robur"], common_name=["English oak", "Pedunculate oak"], authority=["L."],
               plant_type=["Tree"], leaf=["Deciduous"], soil=["Clay"], origin=["Europe"],
               text=["A large deciduous tree that tolerates clay."], source=["ncsu", "pfaf"], year=1753,
               zone_min=4, zone_max=8, height_max_cm=3500, density=675),
    lucene_doc(2, name=["Quercus alba"], common_name=["White oak"], authority=["L."], plant_type=["Tree"],
               text=["A long-lived tree."], source=["ncsu"], year=1753, zone_min=3, zone_max=9, density=755),
    lucene_doc(3, name=["Kalmia latifolia"], common_name=["Mountain laurel"], authority=["L."],
               plant_type=["Shrub"], leaf=["Broadleaf Evergreen"], text=["An evergreen shrub."], source=["ncsu"],
               year=1753, zone_min=4, zone_max=9),
    lucene_doc(4, name=["Acer saccharum"], common_name=["Sugar maple"], plant_type=["Tree"], source=["tso"],
               zone_min=3, zone_max=8, density=720),
]


def write_old_index(folder):
    """Builds the old index of OLD_RECORDS in folder/index; returns that folder."""
    extracted = os.path.join(folder, "extracted")
    os.makedirs(extracted)
    for site, records in OLD_RECORDS.items():
        with open(os.path.join(extracted, site + "_plants.jsonl"), "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(dict(record, source=site)) + "\n")
    with contextlib.redirect_stdout(io.StringIO()):
        old_build.main(["--data-dir", folder])
    return os.path.join(folder, "index")


def write_entities(folder):
    os.makedirs(folder)
    with open(os.path.join(folder, "part-00000"), "w", encoding="utf-8") as handle:
        for entity in ENTITIES:
            handle.write(json.dumps(entity) + "\n")
    return folder


def run_main(argv):
    """(exit code, stdout, stderr) of compare.main."""
    out, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errors):
        code = compare.main(argv)
    return code, out.getvalue(), errors.getvalue()


class OverlapTest(unittest.TestCase):
    def test_shared_ids_of_the_longer_list(self):
        self.assertEqual(compare.overlap(["a", "b", "c"], ["c", "x"]), "1/3")
        self.assertEqual(compare.overlap([], ["a"]), "0/1")
        self.assertEqual(compare.overlap([], []), "-")

    def test_only_the_top_lists_count(self):
        first, second = list("abcdefghijk"), list("kabcdefghij")
        self.assertEqual(compare.overlap(first, second), "9/{}".format(compare.TOP))


class OldEntitiesTest(unittest.TestCase):
    def test_records_map_to_distinct_entities_in_rank_order(self):
        index = types.SimpleNamespace(docs=[{"url": "u1"}, {"url": "u2"}, {"url": "u3"}, {"url": "u4"}])
        ranking = [(2, 0.9), (0, 0.8), (3, 0.7), (1, 0.6)]
        # u4 has no entity, u2 is the second page of entity 7.
        self.assertEqual(compare.old_entities(index, ranking, {"u1": "7", "u2": "7", "u3": "5"}), ["5", "7"])

    def test_many_records_stay_fast(self):
        index = types.SimpleNamespace(docs=[{"url": str(number)} for number in range(40000)])
        ranking = [(number, 1.0) for number in range(40000)]
        url_to_entity = {str(number): str(number // 2) for number in range(40000)}
        self.assertEqual(len(compare.old_entities(index, ranking, url_to_entity)), 20000)


class TimingsTest(unittest.TestCase):
    def fake_clock(self, durations):
        """A clock whose successive start/stop readings are durations (in seconds) apart."""
        readings, now = [], 0.0
        for duration in durations:
            readings += [now, now + duration]
            now += duration + 1.0
        return iter(readings).__next__

    def test_warmup_rounds_are_not_timed_and_the_median_is_reported(self):
        calls = []
        tasks = {"a": lambda: calls.append("a"), "b": lambda: calls.append("b")}
        # Rounds run every task once: a, b, a, b, ...; the first two rounds are the warm-up.
        durations = [0.050, 0.700, 0.004, 0.006, 0.001, 0.010, 0.003, 0.030, 0.002, 0.020]
        first, medians = compare.timings(tasks, 2, 3, self.fake_clock(durations))
        self.assertEqual(calls, ["a", "b"] * 5)
        self.assertAlmostEqual(first["a"], 50.0)
        self.assertAlmostEqual(first["b"], 700.0)
        self.assertAlmostEqual(medians["a"], 2.0)
        self.assertAlmostEqual(medians["b"], 20.0)

    def test_median_of_an_even_number_of_rounds(self):
        first, medians = compare.timings({"a": lambda: None}, 0, 4, self.fake_clock([0.001, 0.002, 0.003, 0.010]))
        self.assertAlmostEqual(first["a"], 1.0)
        self.assertAlmostEqual(medians["a"], 2.5)


class MarkdownCellTest(unittest.TestCase):
    def test_pipe_is_escaped(self):
        self.assertEqual(compare.cell("a|b"), "a\\|b")
        self.assertEqual(compare.cell(3), "3")
        self.assertEqual(compare.code("x | y"), "`x \\| y`")
        self.assertEqual(compare.code(""), "")


class RangeOnlyTest(unittest.TestCase):
    def test_only_ranges_joined_by_and(self):
        for query in ("density:[700 TO *] AND zone_min:[* TO 6]", "year:[1754 TO 1800]", "density:{675 TO *]",
                      "density:[700 TO *] AND NOT zone_min:[* TO 6]", "year:1753 AND zone_min:[* TO 5]"):
            self.assertTrue(compare.range_only(query), query)

    def test_scored_clauses_are_not_ranges(self):
        for query in ("quercus", "soil:clay AND zone_min:[* TO 5]", 'name:"quercus robur" AND density:[* TO *]',
                      "density:[700 TO *] OR zone_min:[* TO 6]", "soil:5", ""):
            self.assertFalse(compare.range_only(query), query)

    def test_k1_5_is_the_only_filter_row(self):
        self.assertEqual([label for label, _kinds, _old, new in compare.QUERIES if compare.range_only(new)],
                         ["K1-5"])


class QueriesTest(unittest.TestCase):
    def test_every_question_also_runs_as_free_text_on_lucene(self):
        rows = {label: (kinds, old, new) for label, kinds, old, new in compare.QUERIES}
        self.assertEqual(len(rows), len(compare.QUERIES))
        for label, _kinds, question, structured in compare.QUESTIONS:
            self.assertNotEqual(question, structured)
            self.assertEqual(rows[label + " free"], ("free text", question, compare.free_text(question)))

    def test_other_rows_send_the_same_string(self):
        questions = {label for label, _kinds, _old, _new in compare.QUESTIONS}
        for label, _kinds, old, new in compare.QUERIES:
            if label not in questions and not label.endswith(" free"):
                self.assertEqual(old, new, label)

    def test_free_text_escapes_the_query_syntax(self):
        self.assertEqual(compare.free_text("700 kg/m3"), "700 kg\\/m3")
        self.assertEqual(compare.free_text("frost-hardy (evergreen)"), "frost\\-hardy \\(evergreen\\)")
        self.assertEqual(compare.free_text("plain words, hardy to zone 5"), "plain words, hardy to zone 5")


def report_row(label, kinds="free text", **values):
    row = {"label": label, "kinds": kinds, "old_query": "a|b", "new_query": "a|b", "parsed": "x", "old_hits": 3,
           "old_entities": 2, "new_hits": 4, "old_ms": 1.234, "new_ms": 0.5, "overlap": "1/2", "other_overlap": "2/2",
           "filter_only": False, "and_hits": 1, "and_top": ["Quercus robur"], "and_overlap": "1/1",
           "old_top": ["Quercus robur (ncsu)"], "new_top": ["Quercus robur (English oak)"]}
    row.update(values)
    return row


def report_meta(**values):
    meta = {"generated": "2026-11-22 20:00 UTC", "total_s": 12.0, "load_s": 3.0, "timing_s": 8.0, "results_s": 1.0,
            "old_n": 5, "old_load_s": 0.1, "name_boost": 3, "unmapped": 1, "lucene": "10.0.0", "new_n": 4,
            "similarity": "BM25Similarity", "other": "ClassicSimilarity", "operator": "or", "all_words": "and",
            "fields": "name^0.4, text^0.2", "escaped": "`/`", "warmup": 100, "repeats": 30,
            "first_label": "K1-1", "first_new_ms": 25.0, "first_old_ms": 40.0}
    meta.update(values)
    return meta


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        self.report = compare.markdown([
            report_row("K1-5", "AND, open range", old_query="question", new_query="density:[700 TO *]",
                       filter_only=True, overlap="0/10", other_overlap="10/10"),
            report_row("K1-5 free", old_query="question", new_query="question"),
            report_row("not", "NOT"),
        ], report_meta())

    def test_header_states_the_method(self):
        for text in ("median of 30 timed rounds after 100 warm-up rounds", "warm JVM", "first query of a fresh process",
                     "K1-1: 25.0 ms in Lucene, 40.0 ms in the old index", "ranking only", "BM25Similarity",
                     "six questions of the project", "with `/` escaped by a backslash; the second table runs it with "
                     "the operator AND", "All other rows send the same string to both indexes", "name^0.4, text^0.2",
                     "searches it only in the fields listed above", "1 of the 5 old records",
                     "alphabetical order of the plant keys", "in 12.0 s"):
            self.assertIn(text, self.report)

    def test_tables(self):
        lines = self.report.splitlines()
        self.assertIn("| # | type | old index query | Lucene query | old hits | Lucene hits | old ms | Lucene ms "
                      "| top-10 overlap | BM25 vs Classic |", lines)
        self.assertIn("| K1-5 | AND, open range | `question` | `density:[700 TO *]` | 3 (2) | 4 | 1.23 | 0.50 "
                      "| 0/10 (ties) | 10/10 (ties) |", lines)
        self.assertIn("| not | NOT | `a\\|b` | `a\\|b` | 3 (2) | 4 | 1.23 | 0.50 | 1/2 | 2/2 |", lines)
        self.assertIn("## Free text with the default operator AND (`--operator and`)", lines)
        self.assertIn("| K1-5 free | `question` | 4 | 1 | Quercus robur | 1/1 |", lines)
        self.assertNotIn("| not | `a\\|b` | 4 | 1 |", "\n".join(lines))
        self.assertIn("## K1-5 free: question", lines)


class MissingInputTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="vinf-compare-")
        self.out = os.path.join(self.folder, "compare.md")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def assertOneLineError(self, argv, *texts):
        code, out, errors = run_main(argv + ["--out", self.out])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(len(errors.strip().splitlines()), 1, errors)
        self.assertNotIn("Traceback", errors)
        for text in texts:
            self.assertIn(text, errors)
        self.assertFalse(os.path.exists(self.out))

    def test_no_old_index(self):
        self.assertOneLineError(["--old-index", os.path.join(self.folder, "none")],
                                "old index", "python -m indexer.build")

    def test_no_entities(self):
        old_index = write_old_index(os.path.join(self.folder, "old"))
        self.assertOneLineError(["--old-index", old_index, "--entities", os.path.join(self.folder, "none")],
                                "entities", "sparkjobs.join_wiki")

    @unittest.skipIf(lucene, "PyLucene is installed")
    def test_no_pylucene(self):
        old_index = write_old_index(os.path.join(self.folder, "old"))
        entities = write_entities(os.path.join(self.folder, "entities"))
        self.assertOneLineError(["--old-index", old_index, "--entities", entities],
                                "PyLucene", "./lucene_docker.sh lucene_index.compare")

    @unittest.skipUnless(lucene, "PyLucene is not installed")
    def test_no_lucene_index(self):
        old_index = write_old_index(os.path.join(self.folder, "old"))
        entities = write_entities(os.path.join(self.folder, "entities"))
        self.assertOneLineError(["--old-index", old_index, "--entities", entities,
                                 "--index", os.path.join(self.folder, "none")],
                                "Lucene index", "./lucene_docker.sh lucene_index.build")


@unittest.skipUnless(lucene, "PyLucene is not installed (run ./lucene_docker.sh unittest tests.test_lucene_compare)")
class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build.start_vm()
        cls.folder = tempfile.mkdtemp(prefix="vinf-compare-")
        cls.lucene_index = os.path.join(cls.folder, "lucene")
        build.build_index(LUCENE_DOCS, cls.lucene_index)
        cls.out = os.path.join(cls.folder, "compare.md")
        cls.code, cls.stdout, cls.stderr = run_main([
            "--old-index", write_old_index(os.path.join(cls.folder, "old")),
            "--entities", write_entities(os.path.join(cls.folder, "entities")),
            "--index", cls.lucene_index, "--out", cls.out, "--warmup", "2", "--repeats", "3"])
        with open(cls.out, encoding="utf-8") as handle:
            cls.report = handle.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def row(self, label):
        found = [line for line in self.report.splitlines() if line.startswith("| {} |".format(label))]
        self.assertTrue(found, label)
        return [value.strip() for value in found[0].strip("|").split("|")]

    def test_report_is_written_and_printed(self):
        self.assertIn(self.code, (None, 0))
        self.assertIn("# Old index vs. PyLucene index", self.report)
        self.assertIn(self.report, self.stdout)
        self.assertIn("warning: 1 old index records have no entity", self.stdout)

    def test_every_query_has_a_row(self):
        for label, _kinds, _old, _new in compare.QUERIES:
            self.assertEqual(len(self.row(label)), 10, label)

    def test_header_uses_the_default_similarity(self):
        default = search.SIMILARITIES[search.DEFAULT_SIMILARITY].__name__
        self.assertIn("{}: {} entity documents, {}".format(lucene.VERSION, len(LUCENE_DOCS), default), self.report)
        self.assertIn("median of 3 timed rounds after 2 warm-up rounds", self.report)

    def test_hits_and_overlap_of_a_free_text_row(self):
        # quercus robur: three old records (two pages of Quercus robur, Quercus alba) of two entities.
        row = self.row("free-4")
        self.assertEqual(row[4:6], ["3 (2)", "2"])
        self.assertEqual(row[8], "2/2")

    def test_filter_row_is_marked(self):
        row = self.row("K1-5")
        self.assertEqual(row[5], "2")
        self.assertTrue(row[9].endswith("(ties)"), row)

    def test_free_text_questions_are_in_the_and_table(self):
        self.assertIn("| K1-1 free | `{}` |".format(compare.free_text(compare.QUESTIONS[0][2])), self.report)

    def test_range_only_queries_give_every_hit_the_same_score(self):
        for similarity in search.SIMILARITIES:
            searcher = search.Searcher(self.lucene_index, similarity)
            try:
                for label, _kinds, _old, new in compare.QUERIES:
                    if compare.range_only(new):
                        hits = searcher.search(new, 20)[2]
                        self.assertGreater(len(hits), 1, label)
                        self.assertEqual(len({hit["score"] for hit in hits}), 1, (label, similarity))
            finally:
                searcher.close()

    def test_timed_lucene_work_ranks_like_the_search(self):
        searcher = search.Searcher(self.lucene_index)
        try:
            total, top_docs = compare.lucene_run(searcher, "quercus")
            _parsed, expected_total, hits = searcher.search("quercus", compare.TOP)
            self.assertEqual(total, expected_total)
            self.assertEqual([score_doc.doc for score_doc in top_docs.scoreDocs], [hit["doc"] for hit in hits])
        finally:
            searcher.close()


if __name__ == "__main__":
    unittest.main()
