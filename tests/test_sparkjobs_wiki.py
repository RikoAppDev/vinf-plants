import unittest

from sparkjobs import join_wiki, wiki_pages

ENTITIES = [
    {"key": "prunus dulcis", "aliases": ["amygdalus communis"], "scientific_names": ["Prunus dulcis"]},
    {"key": "acer palmatum bloodgood", "aliases": [], "scientific_names": ["Acer palmatum 'Bloodgood'"]},
    {"key": "hosta", "aliases": [], "scientific_names": ["Hosta"]},
    {"key": "unparsed:https://example.org/x", "aliases": [], "scientific_names": ["???"]},
]
KEYS, GENERA = wiki_pages.our_names(ENTITIES)

ALMOND = {"page_id": 603, "title": "Almond", "redirect": None, "box": "speciesbox", "genus": "Prunus",
          "species": "amygdalus", "binomial": "Prunus amygdalus", "rank": "species",
          "synonyms": ["Amygdalus communis", "Prunus dulcis", "Prunus communis"]}
MAPLE = {"page_id": 52, "title": "Maple", "redirect": None, "box": "automatic taxobox", "genus": "Acer",
         "taxon": "Acer", "binomial": None, "rank": "genus", "synonyms": ["Negundo"]}


class NamesTest(unittest.TestCase):
    def test_keys_aliases_and_species_of_our_entities(self):
        self.assertEqual(KEYS, {"prunus dulcis", "amygdalus communis", "acer palmatum bloodgood",
                                "acer palmatum", "hosta"})
        self.assertEqual(GENERA, {"prunus", "amygdalus", "acer", "hosta"})

    def test_title_key_drops_the_disambiguator(self):
        self.assertEqual(wiki_pages.name_key("Aucuba (plant)"), "aucuba")
        self.assertEqual(wiki_pages.name_key("Quercus robur"), "quercus robur")
        self.assertEqual(wiki_pages.name_key(""), "")


class WantedPageTest(unittest.TestCase):
    def test_box_article_of_one_of_our_genera(self):
        self.assertTrue(wiki_pages.is_wanted(ALMOND, KEYS, GENERA))
        self.assertTrue(wiki_pages.is_wanted(MAPLE, KEYS, GENERA))

    def test_synonym_alone_is_enough(self):
        page = dict(ALMOND, genus="Amygdalopsis", binomial="Amygdalopsis lindleyi", title="Amygdalopsis lindleyi",
                    synonyms=["Prunus dulcis"])
        self.assertTrue(wiki_pages.is_wanted(page, KEYS, {"acer"}))

    def test_other_pages_are_dropped(self):
        panda = {"page_id": 1, "title": "Giant panda", "redirect": None, "box": "speciesbox",
                 "genus": "Ailuropoda", "binomial": "Ailuropoda melanoleuca", "synonyms": []}
        self.assertFalse(wiki_pages.is_wanted(panda, KEYS, GENERA))
        self.assertFalse(wiki_pages.is_wanted({"page_id": 2, "title": "Anarchism", "redirect": None, "box": None},
                                              KEYS, GENERA))

    def test_redirect_from_one_of_our_names(self):
        self.assertTrue(wiki_pages.is_wanted({"page_id": 3, "title": "Prunus dulcis", "redirect": "Almond"},
                                             KEYS, GENERA))
        self.assertFalse(wiki_pages.is_wanted({"page_id": 4, "title": "AccessibleComputing",
                                               "redirect": "Computer accessibility"}, KEYS, GENERA))

    def test_partition_counts_follow_the_pages(self):
        parsed = {"a": ALMOND, "b": {"page_id": 2, "title": "Anarchism", "redirect": None, "box": None},
                  "c": {"page_id": 3, "title": "Prunus dulcis", "redirect": "Almond"}, "d": None}
        items = list(wiki_pages.keep_pages(["a", "b", "c", "d"], KEYS, GENERA, parsed.get))
        self.assertEqual([item.get("page_id") for item in items[:-1]], [603, 3])
        self.assertEqual(items[-1]["_stats"], {"records": 4, "articles": 2, "redirects": 1, "box_articles": 1,
                                                "kept_articles": 1, "kept_redirects": 1})
        self.assertEqual(items[-1]["_first"], [wiki_pages.record_id("a"), ["records", "articles", "box_articles",
                                                                         "kept_articles"]])
        self.assertEqual(items[-1]["_last"], [wiki_pages.record_id("d"), ["records"]])

    def test_other_plant_articles_are_held_back_for_redirects(self):
        mustard = {"page_id": 9, "title": "Rhamphospermum arvense", "redirect": None, "box": "speciesbox",
                   "genus": "Rhamphospermum", "binomial": "Rhamphospermum arvense", "plant_hint": True}
        panda = {"page_id": 1, "title": "Giant panda", "redirect": None, "box": "speciesbox",
                 "genus": "Ailuropoda", "binomial": "Ailuropoda melanoleuca"}
        parsed = {"m": mustard, "p": panda}
        items = list(wiki_pages.keep_pages(["m", "p"], KEYS, GENERA, parsed.get))
        self.assertEqual(items[:-1], [{"_candidate": "Rhamphospermum arvense", "page": mustard}])
        self.assertEqual(items[-1]["_stats"]["kept_articles"], 0)

    def test_a_record_read_twice_at_a_split_boundary_is_counted_once(self):
        def partition(first_id, last_id, redirects):
            counts = dict.fromkeys(wiki_pages.COUNT_NAMES, 0)
            counts.update(records=5, redirects=redirects)
            return {"_stats": counts, "_first": [first_id, ["records"]],
                    "_last": [last_id, ["records", "redirects"] if redirects else ["records"]]}

        # The redirect that ends the first split is read again as the first record of the second.
        left, right = partition([10, 1], [20, 2], 1), partition([20, 2], [30, 3], 0)
        right["_first"][1] = ["records", "redirects"]
        right["_stats"]["redirects"] = 1
        totals = wiki_pages.page_counts([left, right])
        self.assertEqual((totals["records"], totals["redirects"], totals["seam_duplicates"]), (9, 1, 1))
        other = partition([40, 4], [50, 5], 0)
        self.assertEqual(wiki_pages.page_counts([left, other])["records"], 10)


class JoinKeysTest(unittest.TestCase):
    def test_cultivar_falls_back_to_species_then_genus(self):
        own, species = join_wiki.OWN_NAME, join_wiki.SPECIES
        self.assertEqual(join_wiki.entity_keys(ENTITIES[1]),
                         [("=acer palmat", species), ("=acer palmat bloodgood", own), ("acer", join_wiki.GENUS),
                          ("acer palmatum", species), ("acer palmatum bloodgood", own),
                          ("~acer palmatum", species), ("~acer palmatum bloodgood", own)])

    def test_species_entity_keeps_its_aliases(self):
        own = join_wiki.OWN_NAME
        self.assertEqual(join_wiki.entity_keys(ENTITIES[0]),
                         [("=amygdalus commun", own), ("=prunus dulc", own), ("amygdalus communis", own),
                          ("prunus", join_wiki.GENUS), ("prunus dulcis", own),
                          ("~amygdalus communis", own), ("~prunus dulcis", own)])
        self.assertFalse(join_wiki.is_alias("~prunus dulcis", ENTITIES[0]))
        self.assertTrue(join_wiki.is_alias("=amygdalus commun", ENTITIES[0]))

    def test_genus_page_and_unparsed_entity(self):
        self.assertEqual(join_wiki.entity_keys(ENTITIES[2]), [("hosta", join_wiki.OWN_NAME)])
        self.assertEqual(join_wiki.entity_keys(ENTITIES[3]), [])

    def test_article_keys_keep_only_synonyms_of_the_own_genus(self):
        self.assertEqual(join_wiki.article_keys(ALMOND), [("prunus amygdalus", "box"), ("almond", "title"),
                                                           ("~prunus amygdalus", "hybrid"),
                                                           ("=prunus amygdal", "variant"),
                                                           ("prunus dulcis", "synonym"),
                                                           ("prunus communis", "synonym")])
        self.assertEqual(join_wiki.article_keys(MAPLE), [("acer", "genus"), ("maple", "title")])

    def test_hybrid_sign_and_epithet_endings_meet_through_fallback_keys(self):
        page = {"page_id": 5, "title": "Quercus × hispanica", "binomial": "Quercus × hispanica", "rank": "species",
                "genus": "Quercus"}
        self.assertIn(("~quercus hispanica", "hybrid"), join_wiki.article_keys(page))
        self.assertIn(("~quercus hispanica", join_wiki.OWN_NAME),
                      join_wiki.entity_keys({"key": "quercus hispanica", "aliases": [], "scientific_names": []}))
        self.assertEqual(join_wiki.epithet_variant("styrax japonica"), join_wiki.epithet_variant("styrax japonicus"))
        self.assertEqual(join_wiki.epithet_variant("clematis armandi"), join_wiki.epithet_variant("clematis armandii"))
        self.assertEqual(join_wiki.epithet_variant("acer"), "")

    def test_nothogenus_and_genus_titled_species_article(self):
        sorbaronia = {"page_id": 6, "title": "× Sorbaronia", "taxon": "× Sorbaronia", "rank": "genus"}
        self.assertEqual(join_wiki.article_keys(sorbaronia)[0], ("sorbaronia", "genus"))
        kalopanax = {"page_id": 7, "title": "Kalopanax", "binomial": "Kalopanax septemlobus", "rank": "species",
                     "genus": "Kalopanax"}
        self.assertIn(("kalopanax", "genus_title"), join_wiki.article_keys(kalopanax))
        self.assertTrue(join_wiki.allowed(join_wiki.GENUS, "genus_title"))
        self.assertFalse(join_wiki.allowed(join_wiki.OWN_NAME, "genus_title"))

    def test_which_level_may_meet_which_key(self):
        own, species, genus = join_wiki.OWN_NAME, join_wiki.SPECIES, join_wiki.GENUS
        self.assertTrue(join_wiki.allowed(own, "synonym"))
        self.assertFalse(join_wiki.allowed(species, "synonym"))
        self.assertTrue(join_wiki.allowed(species, "redirect"))
        self.assertFalse(join_wiki.allowed(genus, "box"))
        self.assertTrue(join_wiki.allowed(genus, "genus"))
        self.assertTrue(join_wiki.allowed(own, "genus"))
        self.assertFalse(join_wiki.allowed(species, "genus"))

    def test_genus_article_must_be_about_plants(self):
        # Dracaena (lizard), Wheatear (genus Oenanthe) in the full dump
        self.assertFalse(join_wiki.allowed(join_wiki.GENUS, "genus", plant=False))
        self.assertFalse(join_wiki.allowed(join_wiki.OWN_NAME, "genus", plant=False))
        self.assertTrue(join_wiki.allowed(join_wiki.OWN_NAME, "box", plant=False))

    def best_page(self, *pairs):
        candidates = [item for pair in pairs for item in join_wiki.candidate(pair)]
        winner = candidates[0][1]
        for _entity, item in candidates[1:]:
            winner = join_wiki.better(winner, item)
        return winner[2][0]

    def test_own_key_beats_an_alias_with_its_own_article(self):
        own_name = join_wiki.OWN_NAME
        self.assertEqual(self.best_page(("campanula takesimana", ((7, own_name, True), (100, "box", True))),
                                        ("campanula punctata", ((7, own_name, False), (900, "box", True)))), 900)

    def test_plant_page_beats_an_animal_page_with_the_same_key(self):
        own_name = join_wiki.OWN_NAME
        self.assertEqual(self.best_page(("dracaena", ((8, own_name, False), (346919, "title", False))),
                                        ("dracaena", ((8, own_name, False), (549468, "title", True)))), 549468)

    def test_lower_score_wins_and_ties_keep_both_pages(self):
        own = ((0, 0), frozenset([603]), (603, "box", 0))
        synonym = ((0, 2), frozenset([700]), (700, "synonym", 0))
        self.assertEqual(join_wiki.better(own, synonym), own)
        self.assertEqual(join_wiki.better(synonym, own), own)
        tie = ((0, 0), frozenset([500]), (500, "title", 0))
        self.assertEqual(join_wiki.better(own, tie), ((0, 0), frozenset([500, 603]), (500, "title", 0)))
        same_page = ((0, 0), frozenset([603]), (603, "title", 0))
        self.assertEqual(join_wiki.better(same_page, own)[2], (603, "box", 0))

    def test_species_name_leading_to_a_genus_article_is_the_genus_fallback(self):
        own, genus = join_wiki.OWN_NAME, join_wiki.GENUS
        # "Hosta nigrescens" redirects to the article Hosta.
        [(_entity, (_score, _pages, detail))] = join_wiki.candidate(
            ("hosta nigrescens", ((1, own, False), (10, "redirect", True, "genus", "hosta", None))))
        self.assertEqual(detail, (10, "redirect", genus))
        # Hypochoeris redirects to the plant genus Hypochaeris; a redirect to a species article is no fallback.
        self.assertTrue(join_wiki.candidate(("hypochoeris", ((2, genus, True), (20, "redirect", True, "genus",
                                                                                 "hypochaeris", None)))))
        self.assertFalse(join_wiki.candidate(("lavatera", ((2, genus, True), (21, "redirect", True, "species",
                                                                              "malva arborea", None)))))
        # A redirect to a section page is no species match either, and no genus article.
        self.assertFalse(join_wiki.candidate(("populus candicans", ((3, own, False), (22, "redirect", True, None,
                                                                                      "populus sect tacamahaca", None)))))

    def test_genus_article_beats_a_redirect_and_a_section_page(self):
        genus = join_wiki.GENUS
        self.assertEqual(self.best_page(
            ("nasturtium", ((3, genus, True), (30, "redirect", True, "genus", "tropaeolum", None))),
            ("nasturtium", ((3, genus, True), (31, "genus", True, "genus", "nasturtium", None)))), 31)
        # Rowan has the taxobox of the genus Sorbus but is not its article.
        self.assertEqual(self.best_page(
            ("sorbus", ((4, genus, True), (40, "genus", True, "genus", "rowan", None))),
            ("sorbus", ((4, genus, True), (41, "genus", True, "genus", "sorbus", None)))), 41)

    def test_synonym_by_another_author_is_another_plant(self):
        pair = ("berberis sieboldii", ((5, join_wiki.OWN_NAME, False),
                                       (50, "synonym", True, "species", "berberis vulgaris", "Dippel")))
        authorities = {"berberis sieboldii": ["Miq."]}
        self.assertEqual(join_wiki.candidate(pair, authorities), [])
        self.assertTrue(join_wiki.candidate(pair, {"berberis sieboldii": ["Dippel"]}))
        self.assertTrue(join_wiki.candidate(pair, {}))

    def test_authors_compare_by_surname(self):
        self.assertTrue(join_wiki.same_author("(L.) Mill.", "Mill."))
        self.assertTrue(join_wiki.same_author("Hook. ex Benth.", "Benth."))
        self.assertTrue(join_wiki.same_author("Rehder", "Rehder 1905"))
        self.assertFalse(join_wiki.same_author("L.", "Lam."))
        self.assertFalse(join_wiki.same_author("Rehder", "Greene"))
        self.assertTrue(join_wiki.same_author("", "Greene"))

    def test_match_classes(self):
        self.assertEqual(join_wiki.match_class("quercus robur", {"match": {"level": 0}}), "species")
        self.assertEqual(join_wiki.match_class("hosta", {"match": {"level": 0}}), "genus entity")
        self.assertEqual(join_wiki.match_class("acer x", {"match": {"level": 2}}), "genus")
        self.assertIsNone(join_wiki.match_class("acer x", None))


if __name__ == "__main__":
    unittest.main()
