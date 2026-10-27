"""Tests of the Trees and Shrubs Online extractor on 25 saved pages.

tests/fixtures/tso/ holds 13 pages drawn with a fixed seed (random.Random(42), one page from each
of 13 alphabetical slices of the crawl) and 7 edge cases: Abies alba (long revised article),
Berberis concinna (Bean's text, "Hook. f."), a cultivar, a cultivar group, the "for-deletion"
page, a New Trees text with inline labels and Acer palmatum (two <h1>, abbreviated synonym).
Five more pages show rare cases of the full crawl: labels in <strong> (acacia-spectabilis), a
synonym equal to the accepted name (alnus-cordata), junk synonyms (daphne-oleoides), a "... Group"
synonym (hydrangea-villosa) and hybrid formulas with authors (brachyglottis-dunedin-hybrids).
Expected values were checked by hand against the raw HTML.
"""

import os
import re
import unittest

from extractor import tso

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "tso")

CONTRACT_FIELDS = (
    "scientific_name", "authority", "family", "genus", "common_names", "synonyms", "zone_min", "zone_max",
    "height_min_cm", "height_max_cm", "description", "attributes", "article_type", "rhs_hardiness",
    "conservation_status", "conservation_code", "distribution", "habitat", "awards", "zone_text",
)


def load(slug):
    """Page whose saved file name contains '_<slug>__'."""
    name = next(name for name in os.listdir(FIXTURES) if "_" + slug + "__" in name)
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def extract(slug):
    return tso.extract_plant(load(slug))


class AbiesAlbaTest(unittest.TestCase):
    """Revised article: all header fields, long prose, captions and a hidden glossary on the page."""

    @classmethod
    def setUpClass(cls):
        cls.plant = extract("abies-alba")

    def test_names(self):
        self.assertEqual(self.plant["scientific_name"], "Abies alba")
        self.assertEqual(self.plant["authority"], "Mill.")
        self.assertEqual(self.plant["article_type"], "species")
        self.assertEqual(self.plant["common_names"][:2], ["Silver Fir", "European Silver Fir"])
        self.assertIn("Weisstanne", self.plant["common_names"])

    def test_taxonomy(self):
        self.assertEqual(self.plant["family"], "Pinaceae")
        self.assertEqual(self.plant["genus"], "Abies")

    def test_synonyms_without_and_with_authority(self):
        self.assertEqual(self.plant["synonyms"], ["Abies alba subsp. apennina", "Abies pectinata"])
        self.assertIn("Abies pectinata DC.", self.plant["attributes"]["Synonyms"])

    def test_header_fields(self):
        self.assertEqual((self.plant["zone_min"], self.plant["zone_max"]), (4, 7))
        self.assertEqual(self.plant["zone_text"], "4-7")
        self.assertEqual(self.plant["rhs_hardiness"], "H7")
        self.assertEqual(self.plant["conservation_status"], "Least concern")
        self.assertEqual(self.plant["conservation_code"], "LC")
        self.assertTrue(self.plant["distribution"].startswith("Albania; Andorra; Austria; Bosnia and Herzegovina"))
        self.assertTrue(self.plant["habitat"].startswith("On well-drained soils from 300 (in Bavaria)"))
        self.assertEqual(self.plant["attributes"]["Credits"], ["Tom Christian (2021)"])

    def test_height(self):
        self.assertEqual((self.plant["height_min_cm"], self.plant["height_max_cm"]), (None, 6000))

    def test_description_is_the_article(self):
        description = self.plant["description"]
        # The sidebar and the genus link list are about 400 words; the article itself has about 3 000.
        self.assertGreater(len(description.split()), 2500)
        self.assertTrue(description.startswith("Tree to 60 m tall, 2–2.5 m dbh"))
        self.assertIn("the only European fir with an extensive natural range", description)
        self.assertIn("Green Spiral", description)  # cultivar sections belong to the article

    def test_no_captions_glossary_or_labels_in_description(self):
        description = self.plant["description"]
        self.assertNotIn("Monster Silver Fir", description)  # only in image captions
        self.assertNotIn("Diameter (of trunk) at breast height", description)  # hidden glossary
        self.assertNotIn("Recommended citation", description)
        self.assertNotIn("USDA Hardiness Zone", description)
        self.assertIsNone(re.search(r"<[a-zA-Z/]", description))  # "<3 m" (decoded &lt;) is text, not a tag
        self.assertIn("remaining <3 m in ten years", description)


class AlnusFormosanaTest(unittest.TestCase):
    """The prose mentions 'Critically Endangered' (for a synonym); the labelled status is LC."""

    @classmethod
    def setUpClass(cls):
        cls.plant = extract("alnus-formosana")

    def test_conservation_comes_from_the_label(self):
        self.assertIn("Critically Endangered", self.plant["description"])
        self.assertEqual(self.plant["conservation_status"], "Least concern")
        self.assertEqual(self.plant["conservation_code"], "LC")

    def test_fields(self):
        self.assertEqual(self.plant["authority"], "(Burkill) Makino")
        self.assertEqual(self.plant["genus"], "Alnus")
        self.assertEqual(self.plant["attributes"]["Genus"], ["Alnus", "Subgen. Clethropsis"])
        self.assertEqual(self.plant["common_names"], ["Taiwan Alder"])
        self.assertEqual(self.plant["synonyms"], ["Alnus maritima var. formosana", "Alnus japonica", "Alnus henryi"])
        self.assertEqual((self.plant["zone_min"], self.plant["zone_max"], self.plant["zone_text"]), (8, 11, "8a-11"))
        self.assertEqual(self.plant["rhs_hardiness"], "H5")
        self.assertEqual(self.plant["distribution"], "Taiwan")
        self.assertEqual(self.plant["height_max_cm"], 2000)


class BeanTextTest(unittest.TestCase):
    """Unrevised Bean text without header fields."""

    @classmethod
    def setUpClass(cls):
        cls.plant = extract("berberis-concinna")

    def test_authority_ending_in_f_is_not_a_forma(self):
        self.assertEqual(self.plant["scientific_name"], "Berberis concinna")
        self.assertEqual(self.plant["authority"], "Hook. f.")
        self.assertEqual(self.plant["article_type"], "species")

    def test_missing_fields_stay_empty(self):
        for field in ("zone_min", "zone_max", "zone_text", "rhs_hardiness", "conservation_status",
                      "conservation_code", "distribution", "habitat"):
            self.assertIsNone(self.plant[field], field)
        self.assertEqual(self.plant["common_names"], [])
        self.assertEqual(self.plant["synonyms"], [])
        self.assertEqual(self.plant["awards"], [])

    def test_height_and_text(self):
        self.assertEqual((self.plant["height_min_cm"], self.plant["height_max_cm"]), (None, 91))  # "3 ft high"
        self.assertTrue(self.plant["description"].startswith("A low, deciduous bush 3 ft high"))
        self.assertIn("From the Supplement (Vol. V)", self.plant["description"])
        self.assertEqual(self.plant["attributes"]["Credits"],
                         ["Article from Bean's Trees and Shrubs Hardy in the British Isles"])


class InlineLabelsTest(unittest.TestCase):
    """Texts from New Trees print the labels inline: '<b>Habitat</b> ... <b>USDA Hardiness Zone</b> 9.'"""

    def test_banksia_integrifolia(self):
        plant = extract("banksia-integrifolia")
        self.assertEqual(plant["authority"], "L. f.")
        self.assertEqual(plant["distribution"], "AUSTRALIA: from Proserpine, Queensland to Port Phillip Bay, Victoria")
        self.assertTrue(plant["habitat"].startswith("Coastal dunes and headland at sea-level"))
        # The page zone is 9; "8–9" belongs to the subsp. monticola section further down.
        self.assertEqual((plant["zone_min"], plant["zone_max"], plant["zone_text"]), (9, 9, "9"))
        self.assertEqual((plant["conservation_status"], plant["conservation_code"]), ("Not evaluated", "NE"))
        self.assertEqual(plant["attributes"]["Illustration"], ["Rosser 1993, George 1996"])
        self.assertEqual(plant["attributes"]["Cross-reference"], ["K188"])
        self.assertEqual(plant["common_names"], ["Coast Banksia", "White Honeysuckle"])
        self.assertIsNone(plant["rhs_hardiness"])
        self.assertEqual(plant["height_max_cm"], 2500)

    def test_eucalyptus_neglecta(self):
        plant = extract("eucalyptus-neglecta")
        self.assertEqual(plant["distribution"], "AUSTRALIA: Victoria (southeast)")
        self.assertEqual(plant["habitat"], "Along watercourses in high-altitude forest")
        self.assertEqual((plant["zone_min"], plant["zone_max"], plant["zone_text"]), (7, 7, "7"))
        self.assertEqual(plant["conservation_code"], "NE")
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (None, 600))  # "Tree or mallee to 6 m"
        self.assertTrue(plant["description"].startswith("Tree or mallee to 6 m."))
        self.assertNotIn("Illustration", plant["description"])


class AcerPalmatumTest(unittest.TestCase):
    """A second <h1> ('From New Trees') sits in the text; the synonym abbreviates the genus."""

    @classmethod
    def setUpClass(cls):
        cls.plant = extract("acer-palmatum")

    def test_title_comes_from_the_first_heading(self):
        self.assertEqual(self.plant["scientific_name"], "Acer palmatum")
        self.assertEqual(self.plant["authority"], "Thunb.")
        self.assertIn("From New Trees", self.plant["description"])

    def test_abbreviated_genus_is_expanded(self):
        self.assertEqual(self.plant["synonyms"], ["Acer polymorphum"])
        self.assertEqual(self.plant["attributes"]["Synonyms"], ["A. polymorphum Sieb. & Zucc."])

    def test_long_description(self):
        self.assertGreater(len(self.plant["description"].split()), 4000)


class ArticleTypeTest(unittest.TestCase):

    def test_cultivar(self):
        plant = extract("abelia-maurice-foster")
        self.assertEqual(plant["scientific_name"], "Abelia 'Maurice Foster'")
        self.assertIsNone(plant["authority"])
        self.assertEqual(plant["article_type"], "cultivar")
        self.assertEqual((plant["zone_min"], plant["zone_max"], plant["zone_text"]), (6, 6, "6b"))
        self.assertEqual(plant["rhs_hardiness"], "H5")
        self.assertEqual(plant["distribution"], "China Collected in Sichuan")
        self.assertEqual(plant["habitat"], "Mountain forests")
        self.assertEqual(plant["height_max_cm"], 200)  # "making a shrub to 2 m"

    def test_cultivar_group(self):
        plant = extract("abelia-edward-goucher-cultivars")
        self.assertEqual(plant["scientific_name"], "Abelia 'Edward Goucher' Cultivars")
        self.assertEqual(plant["article_type"], "group")
        self.assertEqual(plant["zone_text"], "6")
        # Each cultivar section prints its own "RHS Hardiness Rating:" line; only the header counts.
        self.assertEqual(plant["attributes"]["RHS Hardiness Rating"], ["H5"])

    def test_page_marked_for_deletion(self):
        plant = extract("pendula-for-deletion")
        self.assertEqual(plant["article_type"], "other")
        self.assertEqual(plant["scientific_name"], "Betula pendula")
        self.assertEqual(plant["authority"], "Roth")
        self.assertEqual(plant["attributes"]["Genus"], ["Betula", "subgen. Betula sect. Betula"])
        # Three printed synonyms, two distinct names once the authorities are removed.
        self.assertEqual(plant["synonyms"], ["Betula alba var. pendula", "Betula alba lusus pendula"])
        self.assertEqual(len(plant["attributes"]["Synonyms"]), 3)

    def test_heading_types(self):
        self.assertEqual(tso.article_type("Abies × arnoldiana", "", ""), "species")
        self.assertEqual(tso.article_type("×Mahoberberis miethkeana", "", ""), "species")
        self.assertEqual(tso.article_type("Betula utilis subsp. jacquemontii", "", ""), "species")
        self.assertEqual(tso.article_type("Magnolia Cultivars A", "", ""), "group")
        self.assertEqual(tso.article_type("Paulownia ARCTIC®", "<span class=trade>ARCTIC</span>", ""), "cultivar")
        self.assertEqual(tso.article_type("Acer miyabei × campestre", "", ""), "other")
        self.assertEqual(tso.article_type("Abies in the Sino-Himalaya", "", ""), "other")


class RandomPagesTest(unittest.TestCase):
    """Pages drawn with the fixed seed; values checked against the HTML."""

    def test_castanea_henryi(self):
        plant = extract("castanea-henryi")
        self.assertEqual(plant["authority"], "(Skan) Rehd. & Wils.")
        self.assertEqual(plant["synonyms"], ["Castanopsis henryi"])
        # "A deciduous tree 60 to 80 ft high, its trunk 6 to 9 ft in girth": the girth is ignored.
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (1829, 2438))

    def test_ephedra_distachya(self):
        plant = extract("ephedra-distachya")
        # "up to 3 or 4 ft": "to" before a printed range keeps the range minimum.
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (91, 122))
        # Description only in the header; a bold variety name there is not a label.
        self.assertTrue(plant["description"].endswith("Var. monostachya (L.) Stapf has solitary female flowers."))
        self.assertEqual(set(plant["attributes"]), {"Family", "Genus", "Credits"})

    def test_fontanesia_fortunei(self):
        plant = extract("fontanesia-fortunei")
        # "10 to 15 ft high in gardens, but said to become a tree 30 to 40 ft high in China"
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (305, 1219))
        self.assertEqual(plant["synonyms"][0], "Fontanesia philliraeoides var. sinensis")

    def test_hypericum_kouytchense(self):
        plant = extract("hypericum-kouytchense")
        self.assertEqual(plant["synonyms"], ["Hypericum patulum var. grandiflorum", "Hypericum × penduliflorum",
                                             "Hypericum patulum var. forrestii", "Hypericum patulum 'Sungold'"])
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (61, 122))

    def test_maclura_pomifera(self):
        plant = extract("maclura-pomifera")
        self.assertEqual(plant["common_names"], ["Osage Orange"])
        self.assertEqual(plant["synonyms"], ["loxylon pomiferum", "Maclura aurantiaca"])  # typo as printed
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (None, 1219))  # "40 ft or more high"

    def test_ostryopsis_davidiana(self):
        plant = extract("ostryopsis-davidiana")
        self.assertEqual(plant["common_names"], ["Hazel-hornbeam"])
        self.assertEqual(plant["synonyms"], ["Corylus davidiana"])
        self.assertEqual(plant["distribution"], "China Gansu, Hebei, Liaoning, Nei Mongol, Ningxia, Shaanxi, Shanxi, W Sichuan")
        self.assertEqual((plant["zone_min"], plant["zone_max"]), (3, 3))
        self.assertEqual(plant["rhs_hardiness"], "H7")
        self.assertEqual(plant["attributes"]["Credits"], ["Owen Johnson (2022)"])

    def test_quercus_palustris(self):
        plant = extract("quercus-palustris")
        self.assertEqual(len(plant["common_names"]), 7)
        self.assertEqual(plant["common_names"][0], "Pin Oak")
        self.assertTrue(plant["distribution"].startswith("Canada Ontario; United States Alabama, Arkansas"))
        self.assertEqual(plant["synonyms"], ["Quercus rubra var. palustris", "Quercus rubra var. dissecta"])
        self.assertEqual(plant["height_max_cm"], 2500)  # "Trees, deciduous, to 25 m"

    def test_rhamnus_fallax(self):
        plant = extract("rhamnus-fallax")
        self.assertEqual(plant["synonyms"], ["Rhamnus alpina subsp. fallax", "Rhamnus alpinus var. grandifolius",
                                             "Rhamnus carniolicus"])
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (122, 305))

    def test_rosa_persica(self):
        plant = extract("rosa-persica")
        # "H. persica" follows "Hulthemia berberifolia": H. is Hulthemia, not the page genus Rosa.
        self.assertEqual(plant["synonyms"], ["Rosa berberifolia", "Hulthemia berberifolia", "Hulthemia persica",
                                             "Lowea berberifolia"])

    def test_syringa_pinetorum(self):
        plant = extract("syringa-pinetorum")
        self.assertEqual(plant["authority"], "W.W.Sm.")
        self.assertEqual((plant["height_min_cm"], plant["height_max_cm"]), (122, 244))

    def test_viburnum_opulus(self):
        plant = extract("viburnum-opulus")
        # "Snowball Tree" and "Award of Merit 1962" belong to cultivar sections, not to the species.
        self.assertEqual(plant["common_names"], ["Guelder Rose"])
        self.assertEqual(plant["awards"], [])
        self.assertIn("Snowball Tree", plant["description"])


class AllFixturesTest(unittest.TestCase):
    """Contract checks on every saved page."""

    @classmethod
    def setUpClass(cls):
        cls.records = {}
        for name in sorted(os.listdir(FIXTURES)):
            with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
                cls.records[name] = tso.extract_plant(handle.read())

    def test_fixture_count(self):
        self.assertEqual(len(self.records), 25)  # 13 seeded + 7 edge cases + 5 rare cases

    def test_contract(self):
        for name, plant in self.records.items():
            with self.subTest(page=name):
                self.assertIsNotNone(plant)
                self.assertEqual(set(CONTRACT_FIELDS) - set(plant), set())
                self.assertTrue(plant["scientific_name"])
                self.assertTrue(plant["family"])
                self.assertIsInstance(plant["common_names"], list)
                self.assertIsInstance(plant["synonyms"], list)
                self.assertIsInstance(plant["awards"], list)
                self.assertTrue(all(isinstance(values, list) for values in plant["attributes"].values()))
                self.assertIn(plant["article_type"], ("species", "cultivar", "group", "other"))

    def test_ranges_are_ordered(self):
        for name, plant in self.records.items():
            with self.subTest(page=name):
                if plant["zone_min"] is not None:
                    self.assertLessEqual(plant["zone_min"], plant["zone_max"])
                if plant["height_min_cm"] is not None and plant["height_max_cm"] is not None:
                    self.assertLessEqual(plant["height_min_cm"], plant["height_max_cm"])

    def test_clean_text_everywhere(self):
        for name, plant in self.records.items():
            with self.subTest(page=name):
                self.assertIsNone(re.search(r"<[a-zA-Z/]|&[a-z]+;|data-caption", plant["description"]))
                self.assertNotIn("Glossary", plant["description"])


class NonArticleTest(unittest.TestCase):

    def test_pages_without_an_article_give_none(self):
        self.assertIsNone(tso.extract_plant(""))
        self.assertIsNone(tso.extract_plant("<html><body><h1>Search results</h1></body></html>"))


class HelperTest(unittest.TestCase):

    def test_zone_range(self):
        self.assertEqual(tso.zone_range("8b-9a"), (8, 9))
        self.assertEqual(tso.zone_range("(9–)10"), (9, 10))
        self.assertEqual(tso.zone_range("7a/8b"), (7, 8))
        self.assertEqual(tso.zone_range(""), (None, None))

    def test_conservation(self):
        self.assertEqual(tso.conservation("Endangered (EN)"), ("Endangered", "EN"))
        self.assertEqual(tso.conservation("Not evaluated (IUCN), but considered to be rare"), ("Not evaluated", "NE"))
        self.assertEqual(tso.conservation("Lower Risk"), ("Lower risk", "LR"))
        self.assertEqual(tso.conservation("Probably threatened"), (None, None))

    def test_awards(self):
        self.assertEqual(tso.awards("AM 1973 (foliage); FCC 1979; AM 1986 (flower)"), ["AM 1973", "FCC 1979", "AM 1986"])
        self.assertEqual(tso.awards("RHS AGM"), ["AGM"])
        self.assertEqual(tso.awards("AM 1926 (G.W.E. Loder, Wakehurst Place); flowers rose-pink"), ["AM 1926"])
        self.assertEqual(tso.awards(""), [])

    def test_height_range(self):
        self.assertEqual(tso.height_range_cm("Tree to 25–35 m × <1.5 m dbh. Crown conical."), (2500, 3500))
        self.assertEqual(tso.height_range_cm("A deciduous tree reaching 30 to 40 ft in height."), (914, 1219))
        self.assertEqual(tso.height_range_cm("Tree to 20 m, bark grey."), (None, 2000))
        self.assertEqual(tso.height_range_cm("Tree 50(–70) m, 2–2.5 m dbh."), (None, 7000))
        self.assertEqual(tso.height_range_cm("Shrub or tree 6–15 m × 0.5–0.8 m dbh."), (600, 1500))
        self.assertEqual(tso.height_range_cm("Large tree to 35 m × 2 m, with fissured bark."), (None, 3500))
        self.assertEqual(tso.height_range_cm("An evergreen shrub 1 1/2 to 4 ft high."), (46, 122))
        self.assertEqual(tso.height_range_cm("A shrub 3–5(–8) m, branches hairy."), (300, 800))
        self.assertEqual(tso.height_range_cm("A shrub with joints 1/2 to 2 in. apart."), (None, None))
        self.assertEqual(tso.height_range_cm("A shrub up to 10 ft high, ascending to 4,500 ft."), (None, 305))
        self.assertEqual(tso.height_range_cm("Native of Japan; introduced in 1845."), (None, None))

    def test_clean_text(self):
        self.assertEqual(tso.clean_text('<a href=x data-caption="<p>A caption</p>">link</a> text'), "link text")
        self.assertEqual(tso.clean_text("1<span class=fnum>1</span>⁄<span class=fden>2</span> in."), "1 1/2 in.")
        self.assertEqual(tso.clean_text("<i>Magnolia</i> × <i>f</i><i>oggii</i>"), "Magnolia × foggii")

    def test_heading(self):
        self.assertEqual(tso.parse_heading("<i>A wilsonii</i> <span class=authors>Rehd</span>", "Aesculus"),
                         ("Aesculus wilsonii", "Rehd"))
        self.assertEqual(tso.parse_heading("<i>Hedera sinensis</i> <span class=authors>Hedera sinensis (Tobler) "
                                           "Hand.-Mazz.</span>", "Hedera"), ("Hedera sinensis", "(Tobler) Hand.-Mazz."))

    def test_synonym_names(self):
        items = ["<i>A. polymorphum</i> Sieb. &amp; Zucc.", "<i>Fraxinus longicuspis sensu</i> Lingelsh.",
                 "<i>Salix spaethii Koopmann</i>", "(Ronniger) Ronniger"]
        self.assertEqual(tso.synonym_names(items, "Acer"), ["Acer polymorphum", "Fraxinus longicuspis", "Salix spaethii"])

    def test_synonym_junk_and_nothospecies(self):
        self.assertEqual(tso.synonym_names(["<i>Gard. Chron</i> ., Vol. 85 (1929), p. 285"], "Viburnum"), [])
        self.assertEqual(tso.synonym_names(["<i>S. Cantab</i> Lynch"], "Smilax"), [])
        self.assertEqual(tso.synonym_names(["<i>B</i>. × <i>irwinii</i> Byhouwer"], "Berberis"), ["Berberis × irwinii"])


class RareCaseTest(unittest.TestCase):
    """Rare layouts of the full crawl, one real page each."""

    def test_labels_printed_in_strong(self):
        plant = extract("acacia-spectabilis")  # "<strong>Distribution</strong> AUSTRALIA: ..."
        self.assertEqual((plant["zone_min"], plant["zone_max"], plant["zone_text"]), (9, 10, "9–10"))
        self.assertEqual(plant["distribution"], "AUSTRALIA: New South Wales, Queensland")
        self.assertEqual(plant["habitat"], "Open forest, scrub or heath with well-drained soils. Often associated with "
                                           "Callitris spp")
        self.assertEqual((plant["conservation_status"], plant["conservation_code"]), ("Not evaluated", "NE"))
        self.assertEqual(plant["attributes"]["Illustration"], ["NT62, NT68"])
        self.assertNotIn("USDA Hardiness Zone", plant["description"])
        self.assertEqual(plant["height_max_cm"], 600)

    def test_synonym_equal_to_accepted_name_is_dropped(self):
        plant = extract("alnus-cordata")  # "<i>Alnus cordata </i> Desf. [Invalid]" is a homonym
        self.assertEqual(plant["synonyms"], ["Alnus cordifolia", "Alnus macrocarpa", "Alnus neopolitana",
                                             "Alnus nervosus", "Betula cordata"])
        self.assertIn("Alnus cordata Desf. [Invalid]", plant["attributes"]["Synonyms"])

    def test_junk_synonyms_are_dropped(self):
        plant = extract("daphne-oleoides")  # "<i>D. 0</i>, var. <i>buxifolia</i>" (digitisation error)
        self.assertEqual(plant["synonyms"], ["Daphne glandulosa", "Daphne buxifolia", "Daphne oleoides var. glandulosa",
                                             "Daphne jasminea"])
        self.assertEqual(len(plant["attributes"]["Synonyms"]), 7)

    def test_group_synonym_is_kept(self):
        plant = extract("hydrangea-villosa")  # "<i>Hydrangea aspera</i> Villosa Group"
        self.assertEqual(plant["synonyms"], ["Hydrangea aspera Villosa Group"])

    def test_hybrid_formulas_lose_their_authors(self):
        plant = extract("brachyglottis-dunedin-hybrids")
        self.assertEqual(plant["synonyms"], [
            "Senecio × crustii", "Senecio laxifolius", "Senecio greyi", "Senecio laxifolius × Senecio compactus",
            "Senecio greyi × Senecio compactus", "Senecio (compactus × greyi) × Senecio greyi",
            "Senecio (compactus × laxifolius) × Senecio greyi"])
        for author in ("Kirk", "Hook.f.", "Buchanan", "Hort."):
            self.assertFalse(any(author in name for name in plant["synonyms"]), author)


if __name__ == "__main__":
    unittest.main()
