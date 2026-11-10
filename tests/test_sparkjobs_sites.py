import contextlib
import io
import json
import os
import random
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict

from crawler import config
from crawler.storage import LOG_COLUMNS
from extractor import run as extract
from extractor.normalize import family_mapping
from sparkjobs import compare, extract_sites
from sparkjobs import merge_entities as spark_merge
from tools import merge_entities
from tools.merge_entities import build_entity, entity_member, entity_profile, merge, merge_stats, record_key

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PFAF = "https://pfaf.org/user/Plant.aspx?LatinName="
TSO = "https://www.treesandshrubsonline.org/articles/"


def log_line(url, file="", status="200", final_url=""):
    row = {"url": url, "final_url": final_url or url, "status": status, "file": file}
    return "\t".join(row.get(column, "") for column in LOG_COLUMNS) + "\n"


PFAF_LOG = [
    "\t".join(LOG_COLUMNS) + "\n",
    log_line("https://pfaf.org/sitemap.xml", "sitemap.xml__1.html"),
    log_line(PFAF + "Abronia+latifolia", "abronia_latifolia.html"),
    log_line(PFAF + "Ulmus+parvifolia", "ulmus_parvifolia.html"),
    # Redirected to a page that is saved under its own URL (in another letter case).
    log_line(PFAF + "Ulmus+chinensis", "ulmus_chinensis.html",
             final_url="https://pfaf.org/user/plant.aspx?latinname=Ulmus+parvifolia"),
    # Redirected to a page that was not saved: kept (a soft 404 without a plant).
    log_line(PFAF + "Crataegus+schraderiana", "crataegus_schraderiana.html", final_url=PFAF + "Crataegus+x"),
    log_line(PFAF + "harishtest", "harishtest.html"),
    log_line(PFAF + "Acer+rubrum", "", status="404"),
    log_line(PFAF + "Acer+campestre", ""),
]


def spark_available():
    if not os.environ.get("JAVA_HOME"):
        return False
    try:
        import pyspark  # noqa: F401
    except ImportError:
        return False
    return True


def skip_unless_spark_starts():
    """JAVA_HOME may point to a Java that Spark cannot run on (e.g. the runtime bundled with an IDE)."""
    from sparkjobs.session import get_spark

    try:
        get_spark("vinf-test-probe", "local[2]").stop()
    except Exception as error:
        if "Java gateway" in str(error) or "JAVA_GATEWAY_EXITED" in str(error):
            raise unittest.SkipTest("Spark cannot start with JAVA_HOME={}".format(os.environ["JAVA_HOME"]))
        raise


class SelectPagesTest(unittest.TestCase):
    def test_saved_relevant_pages_without_redirect_duplicates(self):
        pages, skipped = extract.select_pages(config.SITES["pfaf"], PFAF_LOG)
        self.assertEqual(pages, [(PFAF + "Abronia+latifolia", "abronia_latifolia.html"),
                                 (PFAF + "Ulmus+parvifolia", "ulmus_parvifolia.html"),
                                 (PFAF + "Crataegus+schraderiana", "crataegus_schraderiana.html")])
        self.assertEqual(skipped, 1)

    def test_lines_without_newline_give_the_same_pages(self):
        # sc.textFile returns the lines without "\n", a file handle with it.
        self.assertEqual(extract.select_pages(config.SITES["pfaf"], [line.rstrip("\n") for line in PFAF_LOG]),
                         extract.select_pages(config.SITES["pfaf"], PFAF_LOG))

    def test_saved_pages_joins_the_raw_folder(self):
        data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, data_dir)
        os.makedirs(os.path.join(data_dir, "state", "pfaf"))
        with open(os.path.join(data_dir, "state", "pfaf", "crawl_log.tsv"), "w", encoding="utf-8") as handle:
            handle.writelines(PFAF_LOG)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            pages = list(extract.saved_pages(data_dir, config.SITES["pfaf"]))
        self.assertEqual(pages[1], (PFAF + "Ulmus+parvifolia", os.path.join(data_dir, "raw", "pfaf", "ulmus_parvifolia.html")))
        self.assertEqual(len(pages), 3)
        self.assertEqual(output.getvalue(), "pfaf: 1 redirect duplicates skipped\n")


class ExtractSitesTest(unittest.TestCase):
    def test_files_by_name_keeps_the_log_position_of_every_url(self):
        selected = extract_sites.files_by_name([("u1", "a.html"), ("u2", "b.html"), ("u3", "a.html")])
        self.assertEqual(selected, {"a.html": [(0, "u1"), (2, "u3")], "b.html": [(1, "u2")]})

    def test_page_text_is_what_open_reads(self):
        content = b"<p>caf\xc3\xa9\r\nline\rtwo \xff end</p>\n"
        path = os.path.join(tempfile.mkdtemp(), "page.html")
        self.addCleanup(shutil.rmtree, os.path.dirname(path))
        with open(path, "wb") as handle:
            handle.write(content)
        with open(path, encoding="utf-8", errors="replace") as handle:
            expected = handle.read()
        self.assertEqual(extract_sites.page_text(content), expected)
        self.assertNotIn("\r", expected)

    def test_page_records_of_selected_files_only(self):
        def page(name):
            # input_file_name() gives the URI of the file, with the folder URL-encoded.
            with open(os.path.join(FIXTURES, "pfaf", name), "rb") as handle:
                return "file:///home/FIIT%20-%20STU/data/raw/pfaf/" + name, bytearray(handle.read())

        selected = {"ulmus_parvifolia.html": [(4, PFAF + "Ulmus+parvifolia")],
                    "crataegus_schraderiana.html": [(7, PFAF + "Crataegus+schraderiana")]}
        pages = [page("ulmus_parvifolia.html"), page("crataegus_schraderiana.html"), page("viola_obtusa.html")]
        records = list(extract_sites.page_records(pages, "extractor.pfaf", "pfaf", selected))
        self.assertEqual([position for position, _record in records], [4, 7])
        self.assertIsNone(records[1][1])
        record = records[0][1]
        self.assertEqual(list(record)[:2], ["url", "source"])
        self.assertEqual((record["url"], record["source"], record["scientific_name"]),
                         (PFAF + "Ulmus+parvifolia", "pfaf", "Ulmus parvifolia"))

    def test_families_in_order_gives_the_mapping_of_the_records(self):
        # "Roseacae" looks like a typo of two names that are equally frequent, so the name that
        # comes first in the records decides: the mapping depends on the order, not only the counts.
        for families in (["Rosaceae"] * 5 + ["Rosaaceae"] * 5 + ["Roseacae", ""],
                         ["", "Rosaaceae"] * 5 + ["Roseacae"] + ["Rosaceae"] * 5):
            firsts = {}
            for position, raw in enumerate(families):
                firsts.setdefault(raw, position)
            counts = [(raw, (count, firsts[raw])) for raw, count in Counter(families).items()]
            random.Random(7).shuffle(counts)
            with self.subTest(first=families[0]):
                self.assertEqual(family_mapping(extract_sites.families_in_order(counts)), family_mapping(families))
        self.assertNotEqual(family_mapping(["Rosaceae"] * 5 + ["Rosaaceae"] * 5 + ["Roseacae"])["Roseacae"],
                            family_mapping(["Rosaaceae"] * 5 + ["Rosaceae"] * 5 + ["Roseacae"])["Roseacae"])

    def test_with_family_keeps_the_raw_spelling(self):
        mapping = {"Roseaceae": "Rosaceae", "": None}
        _position, record = extract_sites.with_family((3, {"url": "u", "family": "Roseaceae"}), mapping)
        self.assertEqual(record, {"url": "u", "family": "Rosaceae", "family_raw": "Roseaceae"})
        _position, record = extract_sites.with_family((4, {"url": "u", "family": None}), mapping)
        self.assertEqual(record, {"url": "u", "family": None, "family_raw": None})


def plant(source, name, synonyms=(), url=None):
    return {"source": source, "scientific_name": name, "synonyms": list(synonyms),
            "url": url or "https://{}/{}".format(source, name.replace(" ", "-"))}


RECORDS = [
    plant("ncsu", "Acer rubrum", synonyms=["Acer drummondii", "Acer sanguineum"]),
    plant("pfaf", "Acer drummondii"),
    # Lists the same synonym as Acer rubrum: only the first of the two NCSU pages gets it.
    plant("ncsu", "Acer saccharinum", synonyms=["Acer drummondii"]),
    plant("tso", "Ranunculus ficaria", synonyms=["Ficaria verna"]),
    plant("pfaf", "Ficaria verna", synonyms=["Ranunculus ficaria"]),
    plant("tso", "Acer rubrum"),
    plant("wooddb", "", url="https://wooddb/unknown/"),
]


def merge_like_spark(records):
    """The steps of sparkjobs.merge_entities.merge without Spark, records handled in shuffled order."""
    keyed = [((number,), record_key(record), record) for number, record in enumerate(records)]
    random.Random(3).shuffle(keyed)
    key_sources = defaultdict(set)
    for _position, key, record in keyed:
        key_sources[key].add(record["source"])
    edges = []
    for item in keyed:
        for alias, (position, key) in spark_merge.keyed_edges(*item):
            if alias in key_sources:
                edges.append((position, alias, key_sources[alias], key, key_sources[key]))
    roots, merges = spark_merge.resolve_synonyms(edges)
    members = defaultdict(list)
    for _position, key, record in keyed:
        members[roots.get(key, key)].append(entity_member(record, key))
    entities = [build_entity(number, root, members[root]) for number, root in enumerate(sorted(members), 1)]
    documents = Counter(record["source"] for record in records)
    return entities, merge_stats(documents, Counter(entity_profile(entity) for entity in entities), merges)


def copies(records):
    return json.loads(json.dumps(records))


class SparkMergeStepsTest(unittest.TestCase):
    def test_numbered_record_of_a_part_file_line(self):
        row = ("file:///out/extracted/pfaf/part-00003", 1, json.dumps({"url": "b"}))
        self.assertEqual(spark_merge.numbered_record(row), (("pfaf", "part-00003", 1), {"url": "b"}))

    def test_keyed_edges_skip_synonyms_without_a_key(self):
        record = plant("ncsu", "Ranunculus ficaria", synonyms=["Ficaria verna", "?", "Ficaria grandiflora"])
        self.assertEqual(spark_merge.keyed_edges(("ncsu", "part-00000", 5), "ranunculus ficaria", record),
                         [("ficaria verna", (("ncsu", "part-00000", 5, 0), "ranunculus ficaria")),
                          ("ficaria grandiflora", (("ncsu", "part-00000", 5, 2), "ranunculus ficaria"))])

    def test_resolve_synonyms_follows_the_record_order_not_the_edge_order(self):
        edges = [((2, 0), "acer drummondii", {"pfaf"}, "acer saccharinum", {"ncsu"}),
                 ((0, 0), "acer drummondii", {"pfaf"}, "acer rubrum", {"ncsu", "tso"})]
        self.assertEqual(spark_merge.resolve_synonyms(edges), ({"acer drummondii": "acer rubrum"}, 1))

    def test_same_entities_and_statistics_as_the_single_process_merge(self):
        for order in (RECORDS, list(reversed(RECORDS))):
            with self.subTest(first=order[0]["scientific_name"]):
                self.assertEqual(merge_like_spark(copies(order)), merge(copies(order)))
        # The order matters: Acer drummondii joins whichever NCSU page comes first.
        forward, _stats = merge(copies(RECORDS))
        backward, _stats = merge(copies(list(reversed(RECORDS))))
        self.assertNotEqual(forward, backward)

    def test_merge_stats_from_profiles(self):
        profiles = Counter({(("ncsu", "pfaf"), False): 2, (("pfaf",), False): 3, (("tso",), True): 1})
        stats = merge_stats({"ncsu": 2, "pfaf": 6, "tso": 1}, profiles, 4)
        self.assertEqual(stats["entities"], 6)
        self.assertEqual(stats["entities_per_source"], {"ncsu": 2, "pfaf": 5, "tso": 1})
        self.assertEqual(stats["by_n_sources"], {1: 4, 2: 2})
        self.assertEqual(stats["pairs"], {"ncsu & pfaf": 2, "ncsu & tso": 0, "pfaf & tso": 0})
        self.assertEqual((stats["unparsed_names"], stats["synonym_merges"]), (1, 4))


def text_of(folder, name=None):
    """Text of one file, or of all part files of a folder one after another."""
    if name:
        paths = [os.path.join(folder, name)]
    else:
        paths = [os.path.join(folder, part) for part in sorted(os.listdir(folder)) if part.startswith("part-")]
    text = ""
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            text += handle.read()
    return text


@unittest.skipUnless(spark_available(), "needs pyspark and the JAVA_HOME of a Java that Spark supports")
class SparkJobsEndToEndTest(unittest.TestCase):
    """Both Spark jobs on a few fixture pages give exactly the files of the single-process run."""

    @classmethod
    def setUpClass(cls):
        skip_unless_spark_starts()
        cls.tmp = tempfile.mkdtemp(prefix="vinf-spark-test-")
        data = os.path.join(cls.tmp, "data")
        pages = {
            "pfaf": {"abronia_latifolia.html": "abronia_latifolia.html", "ulmus_parvifolia.html": "ulmus_parvifolia.html",
                     "ulmus_chinensis.html": "ulmus_parvifolia.html", "harishtest.html": "harishtest.html",
                     "crataegus_schraderiana.html": "crataegus_schraderiana.html"},
            "tso": {"alnus_cordata.html": "articles_alnus_alnus-cordata__1d58244e1d.html",
                    "rosa_persica.html": "articles_rosa_rosa-persica__02c011a8f3.html"},
        }
        logs = {"pfaf": PFAF_LOG,
                "tso": ["\t".join(LOG_COLUMNS) + "\n", log_line(TSO + "alnus/alnus-cordata/", "alnus_cordata.html"),
                        log_line(TSO + "rosa/rosa-persica/", "rosa_persica.html")]}
        for site, files in pages.items():
            os.makedirs(os.path.join(data, "raw", site))
            os.makedirs(os.path.join(data, "state", site))
            for name, fixture in files.items():
                shutil.copy(os.path.join(FIXTURES, site, fixture), os.path.join(data, "raw", site, name))
            with open(os.path.join(data, "state", site, "crawl_log.tsv"), "w", encoding="utf-8") as handle:
                handle.writelines(logs[site])
        # Malformed UTF-8 in a common name: an encoded surrogate, an invalid byte, a cut sequence.
        # Python replaces the surrogate with three U+FFFD, Java's decoder with one.
        page_path = os.path.join(data, "raw", "pfaf", "abronia_latifolia.html")
        with open(page_path, "rb") as handle:
            content = handle.read().replace(b"Coastal sand verbena", b"Coastal sand verbena \xed\xa0\x80\xff\xe2\x82")
        with open(page_path, "wb") as handle:
            handle.write(content)

        cls.reference = os.path.join(data, "extracted")
        cls.spark_dir = os.path.join(cls.tmp, "spark")
        with contextlib.redirect_stdout(io.StringIO()):
            extract.main(["--site", "all", "--data-dir", data])
            merge_entities.main(["--data-dir", data])
            extract_sites.main(["--data-dir", data, "--out", cls.spark_dir, "--master", "local[2]"])
            spark_merge.main(["--input", os.path.join(cls.spark_dir, "extracted"),
                              "--out", os.path.join(cls.spark_dir, "entities"), "--master", "local[2]"])
            cls.compare_status = compare.main(["--spark-dir", cls.spark_dir, "--reference", cls.reference,
                                               "--site", "pfaf", "--site", "tso", "--master", "local[2]"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_records_are_the_single_process_records_in_the_same_order(self):
        # PFAF: the redirect duplicate, the soft 404 and the test entry give no record.
        for site, count in (("pfaf", 2), ("tso", 2)):
            with self.subTest(site=site):
                text = text_of(os.path.join(self.spark_dir, "extracted", site))
                self.assertEqual(text, text_of(self.reference, site + "_plants.jsonl"))
                self.assertEqual(text.count("\n"), count)

    def test_malformed_bytes_are_replaced_as_open_does(self):
        self.assertIn("Coastal sand verbena �����",
                      text_of(os.path.join(self.spark_dir, "extracted", "pfaf")))

    def test_entities_and_report_are_the_single_process_ones(self):
        self.assertEqual(text_of(os.path.join(self.spark_dir, "entities")), text_of(self.reference, "entities.jsonl"))
        self.assertEqual(text_of(self.spark_dir, "entities_stats.md"), text_of(self.reference, "entities_stats.md"))

    def test_compare_finds_no_difference(self):
        self.assertEqual(self.compare_status, 0)


if __name__ == "__main__":
    unittest.main()
