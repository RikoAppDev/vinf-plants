import contextlib
import io
import json
import math
import os
import tempfile
import unittest

from indexer import build, compare, search, tokenize, weighting

# Four tiny records in two sources. With name boost 1 the term counts are:
#   doc 0 quercus 2, oak 2, robur, english, fagaceae, large, deciduous, plant, tree, clay, soil
#   doc 1 ilex 2, glabra, inkberry, aquifoliaceae, evergreen, plant, wet, soil, shrub, clay, sand
#   doc 2 malus 3, fruit 2, domestica, apple, pyrus, rosaceae, edible, tree, plant, eaten, fresh
#   doc 3 quercus 2, oak 2, alba, white, fagaceae, hard, wood, tree, plant, dry, soil, 1360, lbf
ALPHA = [
    {"url": "https://example.org/quercus-robur", "source": "alpha", "scientific_name": "Quercus robur",
     "common_names": ["English Oak"], "synonyms": [], "family": "Fagaceae", "genus": "Quercus",
     "species": "robur", "description": None,
     "attributes": {"Description": ["Large deciduous plant. Oak tree for clay soil."],
                    "Genus": ["Quercus"], "Phonetic Spelling": ["KWER-kus ROH-bur"]}},
    {"url": "https://example.org/ilex-glabra", "scientific_name": "Ilex glabra", "common_names": ["Inkberry"],
     "synonyms": [], "family": "Aquifoliaceae", "genus": "Ilex", "description": "Evergreen plant for wet soil.",
     "attributes": {"Plant Type": ["Shrub"], "Soil Texture": ["Clay", "Sand"],
                    "Description": ["Evergreen plant for wet soil."]}},
    {"url": "https://example.org/malus-domestica", "scientific_name": "Malus domestica", "common_names": ["Apple"],
     "synonyms": ["Pyrus malus"], "family": "Rosaceae", "genus": "Malus", "height_min_cm": 300,
     "description": "Edible fruit tree plant. Fruit is eaten fresh.", "attributes": {}},
]
BETA = [
    {"url": "https://example.org/quercus-alba", "scientific_name": "Quercus alba", "common_names": ["White Oak"],
     "synonyms": [], "family": "Fagaceae", "genus": "Quercus", "description": "Hard oak wood; a tree plant of dry soil.",
     "attributes": {"Janka Hardness": ["1,360 lbf"]}},
]


def write_corpus(data_dir):
    extracted = os.path.join(data_dir, "extracted")
    os.makedirs(extracted)
    for name, records in (("alpha", ALPHA), ("beta", BETA)):
        with open(os.path.join(extracted, name + "_plants.jsonl"), "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        # a blank line at the end must not become a document
        with open(os.path.join(extracted, name + "_plants.jsonl"), "a", encoding="utf-8") as handle:
            handle.write("\n")
    return extracted


class TokenizeTest(unittest.TestCase):
    def test_hyphenated_words_and_decimals_stay_whole(self):
        self.assertEqual(tokenize.tokenize("Arctostaphylos uva-ursi is semi-evergreen, 1.5 ft. tall"),
                         ["arctostaphylos", "uva-ursi", "semi-evergreen", "1.5", "ft", "tall"])

    def test_number_ranges_split_into_numbers(self):
        self.assertEqual(tokenize.tokenize("Soil pH 6.0-8.0, height 5-8 ft"),
                         ["soil", "ph", "6.0", "8.0", "height", "5", "8", "ft"])

    def test_thousands_separator_and_zone_suffix(self):
        self.assertEqual(tokenize.tokenize("Janka 1,360 lbf; zones 7a, 7b"),
                         ["janka", "1360", "lbf", "zones", "7a", "7b"])

    def test_stop_words_and_one_letter_tokens_are_dropped(self):
        self.assertEqual(tokenize.tokenize("The tree is in a Children's Garden, e.g. Abelia x grandiflora"),
                         ["tree", "children", "garden", "abelia", "grandiflora"])

    def test_unicode_letters_kept_and_symbols_split(self):
        self.assertEqual(tokenize.tokenize("Père David's MAPLE ×hybrid"), ["père", "david", "maple", "hybrid"])

    def test_plural_folding_is_off_by_default(self):
        text = "trees shrubs leaves berries grasses quercus species"
        self.assertEqual(tokenize.tokenize(text), text.split())
        self.assertEqual(tokenize.tokenize(text, fold_plurals=True),
                         ["tree", "shrub", "leaf", "berry", "grass", "quercus", "species"])

    def test_stopword_file(self):
        self.assertIn("the", tokenize.STOPWORDS)
        self.assertGreater(len(tokenize.STOPWORDS), 100)
        self.assertFalse([word for word in tokenize.STOPWORDS if len(word) < 2 or word.startswith("#")])
        # domain words are left to idf
        self.assertFalse({"plant", "leaf", "soil", "tree", "full", "sun"} & tokenize.STOPWORDS)


class WeightingTest(unittest.TestCase):
    def test_idf_values_by_hand(self):
        self.assertAlmostEqual(weighting.idf("classic", 1, 4), 0.6020599913)  # log10(4)
        self.assertAlmostEqual(weighting.idf("smooth", 1, 4), 0.6989700043)   # log10(5)
        self.assertEqual(weighting.idf("none", 1, 4), 1.0)
        self.assertAlmostEqual(weighting.idf("classic", 2, 4), 0.3010299957)  # log10(2)
        self.assertAlmostEqual(weighting.idf("smooth", 2, 4), 0.4771212547)   # log10(3)

    def test_term_in_every_document(self):
        self.assertEqual(weighting.idf("classic", 4, 4), 0.0)
        self.assertAlmostEqual(weighting.idf("smooth", 4, 4), math.log10(2))
        self.assertGreater(weighting.idf("smooth", 4, 4), 0)

    def test_tf_variants(self):
        self.assertEqual(weighting.tf_weight("raw", 3, 5), 3.0)
        self.assertEqual(weighting.tf_weight("log", 1, 5), 1.0)
        self.assertAlmostEqual(weighting.tf_weight("log", 10, 10), 2.0)
        self.assertEqual(weighting.tf_weight("maxnorm", 1, 2), 0.75)
        self.assertEqual(weighting.tf_weight("maxnorm", 2, 2), 1.0)
        self.assertEqual(weighting.tf_weight("log", 0, 2), 0.0)

    def test_unknown_method(self):
        with self.assertRaises(ValueError):
            weighting.idf("probabilistic", 1, 4)
        with self.assertRaises(ValueError):
            weighting.tf_weight("boolean", 1, 4)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.extracted = write_corpus(self.folder.name)
        self.docs, self.postings, self.stats = build.build_index(self.extracted, name_boost=1)

    def tearDown(self):
        self.folder.cleanup()

    def test_documents_sources_lengths(self):
        self.assertEqual([doc["source"] for doc in self.docs], ["alpha", "alpha", "alpha", "beta"])
        self.assertEqual([doc["length"] for doc in self.docs], [13, 12, 14, 15])
        self.assertEqual([doc["max_tf"] for doc in self.docs], [2, 2, 3, 2])

    def test_postings_hold_tf_in_doc_order(self):
        self.assertEqual(list(build.pairs(self.postings["quercus"])), [(0, 2), (3, 2)])
        self.assertEqual(list(build.pairs(self.postings["fruit"])), [(2, 2)])
        self.assertEqual(list(build.pairs(self.postings["malus"])), [(2, 3)])
        self.assertEqual(list(build.pairs(self.postings["plant"])), [(0, 1), (1, 1), (2, 1), (3, 1)])
        self.assertEqual(list(build.pairs(self.postings["1360"])), [(3, 1)])
        self.assertEqual(len(self.postings["soil"]) // 2, 3)  # df

    def test_metadata_and_duplicate_fields_are_not_indexed(self):
        for term in ("https", "example.org", "alpha", "kwer-kus", "300", "genus", "description"):
            self.assertNotIn(term, self.postings)
        # robur: only the scientific name, not the species field
        self.assertEqual(list(build.pairs(self.postings["robur"])), [(0, 1)])
        # Ilex: description indexed once although it is also an attribute
        self.assertEqual(list(build.pairs(self.postings["evergreen"])), [(1, 1)])

    def test_name_boost(self):
        docs, postings, _ = build.build_index(self.extracted, name_boost=3)
        self.assertEqual(list(build.pairs(postings["quercus"]))[0], (0, 4))  # 3x name + genus
        self.assertEqual(list(build.pairs(postings["oak"]))[0], (0, 4))      # 3x common name + description
        self.assertEqual(list(build.pairs(postings["robur"])), [(0, 3)])
        self.assertEqual(docs[0]["length"], 21)

    def test_vector_lengths_by_hand(self):
        # doc 0: quercus and oak twice, 9 other terms once; max_tf 2; no idf in document vectors
        norms = self.docs[0]["norms"]
        self.assertEqual(set(norms), set(weighting.TF_METHODS))
        self.assertAlmostEqual(norms["raw"], math.sqrt(2 * 2 ** 2 + 9))
        self.assertAlmostEqual(norms["log"], math.sqrt(2 * (1 + math.log10(2)) ** 2 + 9))
        self.assertAlmostEqual(norms["maxnorm"], math.sqrt(2 * 1.0 ** 2 + 9 * 0.75 ** 2))


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.extracted = write_corpus(self.folder.name)
        with contextlib.redirect_stdout(io.StringIO()):
            build.main(["--data-dir", self.folder.name, "--name-boost", "1"])
        self.index = search.Index(os.path.join(self.folder.name, "index"))

    def tearDown(self):
        self.folder.cleanup()

    def test_index_files_round_trip(self):
        docs, postings, _ = build.build_index(self.extracted, name_boost=1)
        self.assertEqual(self.index.n, 4)
        self.assertEqual(self.index.meta["options"], {"name_boost": 1, "fold_plurals": False})
        self.assertEqual(self.index.meta["documents_per_source"], {"alpha": 3, "beta": 1})
        self.assertEqual([doc["url"] for doc in self.index.docs], [doc["url"] for doc in docs])
        self.assertEqual(self.index.max_tf, [doc["max_tf"] for doc in docs])
        self.assertEqual(self.index.df, {term: len(values) // 2 for term, values in postings.items()})
        for term, values in postings.items():
            self.assertEqual(self.index.postings(term), list(build.pairs(values)))
        self.assertEqual(set(self.index.norms), set(weighting.TF_METHODS))
        for method in weighting.TF_METHODS:
            for loaded, doc in zip(self.index.norms[method], docs):
                self.assertAlmostEqual(loaded, doc["norms"][method])

    def test_missing_meta_means_no_index(self):
        os.remove(os.path.join(self.folder.name, "index", "meta.json"))
        with self.assertRaises(FileNotFoundError):
            search.Index(os.path.join(self.folder.name, "index"))

    def test_ranking_order(self):
        # docs 0 and 3 have oak twice and tree once, doc 0 is the shorter vector
        ranking = self.index.rank("oak tree", "classic", "log", "cosine")
        self.assertEqual([doc_id for doc_id, _ in ranking], [0, 3, 2])
        self.assertTrue(ranking[0][1] > ranking[1][1] > ranking[2][1] > 0)

    def test_unnormalised_score_by_hand(self):
        scores = dict(self.index.rank("oak tree", "classic", "log", "none"))
        idf_oak, idf_tree = math.log10(4 / 2), math.log10(4 / 3)
        # query weight 1 * idf, document weight 1 + log10(tf): oak tf 2, tree tf 1
        self.assertAlmostEqual(scores[0], idf_oak * (1 + math.log10(2)) + idf_tree * 1)

    def test_cosine_score_by_hand(self):
        scores = dict(self.index.rank("robur", "smooth", "raw", "cosine"))
        # query weight 1 * log10(4/1 + 1); document weight tf 1 / length sqrt(17)
        self.assertAlmostEqual(scores[0], math.log10(5) * 1 / math.sqrt(17))

    def test_idf_method_does_not_change_document_vectors(self):
        # one query term: every idf method scales all scores by the same factor
        orders = {method: [doc_id for doc_id, _ in self.index.rank("soil", method)]
                  for method in weighting.IDF_METHODS}
        self.assertEqual(orders["classic"], orders["smooth"])
        self.assertEqual(orders["classic"], orders["none"])

    def test_term_in_every_document_needs_smooth_idf(self):
        self.assertEqual(search.search(self.index, "plant", "classic"), [])
        self.assertEqual(len(search.search(self.index, "plant", "smooth")), 4)
        # classic still ranks all candidates, with score 0
        self.assertEqual([score for _, score in self.index.rank("plant", "classic")], [0.0] * 4)

    def test_none_gives_frequent_terms_full_weight(self):
        def matching(idf_method):
            return {doc_id for doc_id, score in self.index.rank("plant clay", idf_method) if score > 0}
        self.assertEqual(matching("classic"), {0, 1})  # plant is in every document: idf 0
        self.assertEqual(matching("none"), {0, 1, 2, 3})

    def test_unknown_and_stop_words_are_ignored(self):
        self.assertEqual(self.index.rank("the oak zzzz"), self.index.rank("oak"))

    def test_source_filter_and_top(self):
        results = search.search(self.index, "oak", source="beta")
        self.assertEqual([(rank, doc["scientific_name"]) for rank, _, doc in results], [(1, "Quercus alba")])
        self.assertEqual(len(search.search(self.index, "tree soil", top=2)), 2)


class LectureExampleTest(unittest.TestCase):
    def test_slide_51_scores(self):
        """Expected numbers are from the worked tf-idf example of lecture 06."""
        texts = (["skúška znalosť znalosť predmet predmet predmet",  # document 1: tf 1, 0, 2, 3
                  "skúška skúška znalosť predmet predmet predmet"]    # document 2: tf 2, 0, 1, 3
                 + ["skúška"] * 48 + ["získať"] * 500 + ["znalosť"] * 998 + ["predmet"] * 98)
        texts += ["iný"] * (10000 - len(texts))
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "extracted"))
            with open(os.path.join(folder, "extracted", "lecture_plants.jsonl"), "w", encoding="utf-8") as handle:
                for number, text in enumerate(texts):
                    handle.write(json.dumps({"url": str(number), "description": text}) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                build.main(["--data-dir", folder])
            index = search.Index(os.path.join(folder, "index"))
            self.assertEqual(index.n, 10000)
            self.assertEqual([index.df[term] for term in ("skúška", "získať", "znalosť", "predmet")],
                             [50, 500, 1000, 100])
            self.assertAlmostEqual(index.norms["log"][0], 2.207841, places=5)  # length of document 1
            scores = dict(index.rank("skúška získať znalosť", "classic", "log", "cosine"))
            self.assertAlmostEqual(scores[0], 1.631485, places=5)
            self.assertAlmostEqual(scores[1], 1.808874, places=5)


class CompareTest(unittest.TestCase):
    def test_overlap(self):
        self.assertAlmostEqual(compare.overlap(["a", "b", "c"], ["c", "b", "x"], depth=3), 2 / 3)

    def test_spearman(self):
        ranking = ["a", "b", "c", "d"]
        self.assertEqual(compare.spearman(ranking, ranking, depth=4), 1.0)
        self.assertEqual(compare.spearman(ranking, ranking[::-1], depth=4), -1.0)
        # union of the top 2 = {a, b, c}; positions in the full rankings decide the order
        self.assertEqual(compare.spearman(["a", "b", "c"], ["c", "a", "b"], depth=2), -0.5)

    def test_compare_query_on_small_index(self):
        with tempfile.TemporaryDirectory() as folder:
            write_corpus(folder)
            with contextlib.redirect_stdout(io.StringIO()):
                build.main(["--data-dir", folder])
                compare.main(["--data-dir", folder, "--query", "oak tree"])
            index = search.Index(os.path.join(folder, "index"))
            tables, agreement = compare.compare_query(index, "oak tree")
            self.assertEqual(set(agreement), {("classic", "smooth"), ("classic", "none"), ("smooth", "none")})
            self.assertEqual([row[0] for row in tables[0][2]], ["oak", "tree"])
            with open(os.path.join(folder, "index", "idf_comparison.md"), encoding="utf-8") as handle:
                self.assertIn("## oak tree", handle.read())


class DuplicateTextTest(unittest.TestCase):
    def test_attribute_copied_into_description_or_names_counts_once(self):
        # Wood Database style record: prose sections are joined into description
        # and "Common Name(s)" is split into common_names.
        record = {
            "scientific_name": "Quercus robur", "common_names": ["English Oak", "European Oak"],
            "description": "Has a tell-tale smell. Cabinetry, barrels.",
            "attributes": {"Odor": ["Has a tell-tale smell."], "Common Name(s)": ["English Oak, European Oak"],
                           "Janka Hardness": ["1,120 lbf (4,980 N)"]},
        }
        tf, _, _ = build.document_terms(record, name_boost=1)
        self.assertEqual(tf["smell"], 1)
        self.assertEqual(tf["english"], 1)
        self.assertEqual(tf["lbf"], 1)  # a value that is not repeated elsewhere is indexed


if __name__ == "__main__":
    unittest.main()
