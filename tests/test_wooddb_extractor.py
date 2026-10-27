import json
import os
import unittest

from extractor import wooddb

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wooddb")
# The pages are "All Rights Reserved" and are not in the public repo.
needs_pages = unittest.skipUnless(os.path.isdir(FIXTURES), "saved Wood Database pages are not distributed")


def load(slug):
    with open(os.path.join(FIXTURES, slug + ".html"), encoding="utf-8") as handle:
        return handle.read()


def extract(slug):
    return wooddb.extract_plant(load(slug))


# Expected values checked by hand against the saved pages. The first 11 pages
# were drawn with a fixed seed across the alphabet; the rest are edge cases.
# slug: values in FIELDS order
EXPECTED = {
    "african-walnut": ("Lovoa trichilioides", "African Walnut", 3000, 4600, 540.0, 4180, 84.5, 9.24, 46.2, "Least Concern", False, None, None),
    "black-sheoak": ("Allocasuarina littoralis", "Black Sheoak", None, None, 770.0, 6650, None, None, None, None, None, None, "Casuarinaceae"),
    "chestnut-oak": ("Quercus montana", "Chestnut Oak", 1800, 2200, 750.0, 5030, 91.7, 11.0, 47.1, None, False, None, None),
    "english-walnut": ("Juglans regia", "English Walnut", 2400, 3500, 640.0, 5410, 111.5, 10.81, 50.2, "Near Threatened", False, None, None),
    "iroko": ("Milicia excelsa", "Iroko", 3000, 4000, 660.0, 5310, 97.1, 10.9, 53.5, "Near Threatened", False, None, "Moraceae"),
    "keyaki": ("Zelkova serrata", "Keyaki", 2000, 3000, 620.0, 4640, 96.7, 10.73, 51.1, "Near Threatened", False, None, "Ulmaceae"),
    "monterey-cypress": ("Cupressus macrocarpa", "Monterey Cypress", 1500, 2500, 515.0, 2750, 81.2, 7.81, 39.4, "Vulnerable", False, None, None),
    "pond-pine": ("Pinus serotina", "Pond Pine", 1500, 2000, 610.0, 3290, 80.0, 12.07, 52.0, "Least Concern", False, None, None),
    "sassafras": ("Sassafras albidum", "Sassafras", 1500, 2000, 495.0, 2800, 62.1, 7.72, 45.5, "Least Concern", False, None, "Lauraceae"),
    "sweet-chestnut": ("Castanea sativa", "Sweet Chestnut", 3000, 3700, 590.0, 3010, 71.4, 8.61, 43.8, None, False, None, None),
    "western-white-pine": ("Pinus monticola", "Western White Pine", 3000, 4600, 435.0, 1870, 66.9, 10.07, 34.8, "Least Concern", False, None, None),
    "african-mahogany": ("Khaya spp.", "African Mahogany", 3000, 6000, 545.0, 3800, 80.9, 9.72, 45.3, "Vulnerable", True, "Appendix II", "Meliaceae"),
    "bendee": ("Acacia catenulata", "Bendee", None, None, 1200.0, None, None, None, None, None, None, None, "Fabaceae"),
    "black-cherry": ("Prunus serotina", "Black Cherry", 1500, 3000, 560.0, 4230, 84.8, 10.3, 49.0, "Least Concern", False, None, "Rosaceae"),
    "dutch-elm": ("Ulmus × hollandica", "Dutch Elm", 2500, 3500, 575.0, 3790, 68.7, 7.52, 32.0, None, False, None, None),
    "pink-lapacho": ("Handroanthus impetiginosus", "Pink Lapacho", 2000, 3000, 960.0, 11850, 160.1, 19.13, 73.1, "Near Threatened", True, "Appendix II", "Bignoniaceae"),
    "waddywood": ("Acacia peuce", "Waddywood", 1500, 1800, 1430.0, 20600, 150.0, 21.5, 80.0, None, False, None, "Fabaceae"),
}
FIELDS = ("scientific_name", "wood_name", "height_min_cm", "height_max_cm", "density_kg_m3", "janka_hardness_n",
          "modulus_of_rupture_mpa", "elastic_modulus_gpa", "crushing_strength_mpa", "iucn_status", "cites_listed",
          "cites", "family")
NOT_SPECIES = ("birdseye-maple", "bog-oak", "bamboo")
CONTRACT_KEYS = ("scientific_name", "authority", "family", "genus", "common_names", "synonyms", "zone_min",
                 "zone_max", "height_min_cm", "height_max_cm", "description", "attributes")


@needs_pages
class AllFixturesTest(unittest.TestCase):
    """Key fields of all 20 saved pages."""

    @classmethod
    def setUpClass(cls):
        cls.records = {slug: extract(slug) for slug in list(EXPECTED) + list(NOT_SPECIES)}

    def test_there_are_twenty_fixtures(self):
        self.assertEqual(len(os.listdir(FIXTURES)), 20)
        self.assertEqual(len(self.records), 20)

    def test_expected_values(self):
        for slug, expected in EXPECTED.items():
            record = self.records[slug]
            for field, value in zip(FIELDS, expected):
                with self.subTest(page=slug, field=field):
                    self.assertEqual(record[field], value)

    def test_non_species_pages_give_none(self):
        for slug in NOT_SPECIES:
            with self.subTest(page=slug):
                self.assertIsNone(self.records[slug])

    def test_record_contract(self):
        for slug in EXPECTED:
            record = self.records[slug]
            with self.subTest(page=slug):
                for key in CONTRACT_KEYS:
                    self.assertIn(key, record)
                self.assertIsInstance(record["scientific_name"], str)
                self.assertEqual(record["genus"], record["scientific_name"].split()[0])
                # The only "USDA" on this site is the Janka footnote, never a hardiness zone.
                self.assertIsNone(record["zone_min"])
                self.assertIsNone(record["zone_max"])
                self.assertTrue(record["common_names"])
                self.assertTrue(record["description"])
                json.dumps(record)

    def test_values_are_clean_text(self):
        leftovers = ("<", "&nbsp;", "&amp;", "Continue reading", "Click on the link", "TIERS", "jQuery",
                     "Drag the slider", "More images", "(Authority)")
        for slug in EXPECTED:
            record = self.records[slug]
            texts = [record["description"]] + [value for values in record["attributes"].values() for value in values]
            for text in texts:
                for leftover in leftovers:
                    with self.subTest(page=slug, leftover=leftover):
                        self.assertNotIn(leftover, text)


@needs_pages
class OldLayoutTest(unittest.TestCase):
    """African walnut: the classic profile with a table and prose blockquotes."""

    @classmethod
    def setUpClass(cls):
        cls.wood = extract("african-walnut")

    def test_names(self):
        self.assertEqual(self.wood["scientific_names"], ["Lovoa trichilioides"])
        self.assertEqual(self.wood["common_names"], ["African Walnut"])
        self.assertEqual(self.wood["synonyms"], [])
        self.assertIsNone(self.wood["authority"])
        self.assertEqual(self.wood["wood_type"], "Hardwood")

    def test_tree_size_from_metric_part(self):
        # "100-150 ft (30-46 m) tall, 2-4 ft (.6-1.2 m) trunk diameter"
        self.assertEqual((self.wood["trunk_diameter_min_cm"], self.wood["trunk_diameter_max_cm"]), (60, 120))

    def test_raw_strings_stay_in_attributes(self):
        attributes = self.wood["attributes"]
        self.assertEqual(attributes["Average Dried Weight"], ["34 lbs/ft3 (540 kg/m3)"])
        self.assertEqual(attributes["Janka Hardness"], ["940 lbf (4,180 N)"])
        self.assertEqual(self.wood["specific_gravity"], ".45, .54")
        self.assertEqual(self.wood["distribution"], "West tropical Africa")

    def test_shrinkage(self):
        self.assertEqual(
            (self.wood["shrinkage_radial_pct"], self.wood["shrinkage_tangential_pct"],
             self.wood["shrinkage_volumetric_pct"], self.wood["shrinkage_tr_ratio"]),
            (3.7, 5.9, 10.8, 1.6))

    def test_common_uses_list(self):
        self.assertEqual(self.wood["common_uses"], ["Veneer", "plywood", "flooring", "furniture", "cabinetry", "turned objects"])

    def test_description_starts_with_comments_and_skips_media_sections(self):
        self.assertTrue(self.wood["description"].startswith("Although Lovoa trichilioides is commonly called"))
        self.assertIn("ribbon-stripe figuring", self.wood["description"])
        self.assertNotIn("Scans below were taken", self.wood["description"])
        self.assertNotIn("Scans/Pictures", self.wood["attributes"])
        self.assertNotIn("Related Species", self.wood["attributes"])


@needs_pages
class NewestLayoutTest(unittest.TestCase):
    """Black cherry: hover tooltips, IUCN/CITES status fields and a taxonomy box."""

    @classmethod
    def setUpClass(cls):
        cls.wood = extract("black-cherry")

    def test_tooltips_are_not_part_of_values(self):
        self.assertEqual(self.wood["specific_gravity"], "0.47, 0.56")
        self.assertEqual(self.wood["attributes"]["Average Dried Weight"], ["35.0 lbs/ft3 (560 kg/m3) Low"])

    def test_taxonomy_box(self):
        self.assertEqual(self.wood["authority"], "Ehrh.")
        self.assertEqual(self.wood["family"], "Rosaceae")
        self.assertEqual(self.wood["genus"], "Prunus")

    def test_status_fields(self):
        self.assertEqual(self.wood["attributes"]["IUCN Status"], ["Least Concern"])
        self.assertEqual(self.wood["attributes"]["CITES Status"], ["Unlisted"])
        self.assertFalse(self.wood["cites_listed"])

    def test_shrinkage_wrapped_around_a_tier_label(self):
        # "Radial: 3.7%, Tangential: 7.1% High <tooltip> Volumetric: 11.5%, T/R Ratio: 1.9"
        self.assertEqual(self.wood["shrinkage_volumetric_pct"], 11.5)
        self.assertEqual(self.wood["shrinkage_tr_ratio"], 1.9)

    def test_anatomy_fields(self):
        self.assertEqual(self.wood["attributes"]["Porosity"], ["semi-ring-porous to diffuse-porous"])
        self.assertIn("Porosity: semi-ring-porous to diffuse-porous", self.wood["description"])
        # "Identification:" only links to the anatomy article, so it stays out of the description.
        self.assertIn("Identification", self.wood["attributes"])
        self.assertNotIn("See the article on Hardwood Anatomy", self.wood["description"])


@needs_pages
class IrokoTest(unittest.TestCase):
    """Two species on one page and citation footnotes in the prose."""

    @classmethod
    def setUpClass(cls):
        cls.wood = extract("iroko")

    def test_both_species_and_no_genus_only_synonym(self):
        self.assertEqual(self.wood["scientific_names"], ["Milicia excelsa", "Milicia regia"])
        # "(formerly placed in the Chlorophora genus ...)" names no species.
        self.assertEqual(self.wood["synonyms"], [])

    def test_first_iucn_category_after_red_list_statement(self):
        # "... is on the IUCN Red List. While Milicia excelsa is only listed as near threatened, M. regia ..."
        self.assertEqual(self.wood["iucn_status"], "Near Threatened")

    def test_footnote_citations_removed(self):
        comments = self.wood["attributes"]["Comments"][0]
        self.assertTrue(comments.startswith("Although the Milicia genus was first described back in 1909, for many decades"))
        self.assertNotIn("Sim, T. R.", comments)

    def test_placeholder_none_is_dropped(self):
        # The page prints "Notes: None."
        self.assertNotIn("Notes", self.wood["attributes"])


@needs_pages
class KeyakiTest(unittest.TestCase):
    """Approximate shrinkage, a table footnote and Common Uses written as sentences."""

    @classmethod
    def setUpClass(cls):
        cls.wood = extract("keyaki")

    def test_approximate_values_and_footnote(self):
        self.assertEqual(self.wood["shrinkage_radial_pct"], 5.0)
        shrinkage = self.wood["attributes"]["Shrinkage"]
        self.assertEqual(shrinkage[0], "Radial: ~5%, Tangential: ~8%, Volumetric: ~13%, T/R Ratio: ~1.6*")
        self.assertEqual(shrinkage[1], "*Shrinkage values are for the subspecies Z. serrata var. tarokoensis")

    def test_prose_common_uses_stay_one_item(self):
        self.assertEqual(len(self.wood["common_uses"]), 1)
        self.assertTrue(self.wood["common_uses"][0].startswith("Used domestically within its natural range"))

    def test_non_latin_common_names(self):
        self.assertEqual(self.wood["common_names"], ["Keyaki", "Japanese elm", "ケヤキ", "榉树", "느티나무"])


@needs_pages
class SynonymTest(unittest.TestCase):
    def test_pink_lapacho_synonyms_with_expanded_abbreviation(self):
        wood = extract("pink-lapacho")
        self.assertEqual(wood["scientific_names"], ["Handroanthus impetiginosus"])
        self.assertEqual(wood["synonyms"], ["Tabebuia impetiginosa", "Tabebuia palmeri"])
        self.assertEqual(wood["common_names"], ["Pink lapacho", "ipe", "pink trumpet tree"])

    def test_dutch_elm_hybrid_parents_are_not_names_of_this_wood(self):
        wood = extract("dutch-elm")
        self.assertEqual(wood["scientific_names"], ["Ulmus × hollandica"])
        self.assertEqual(wood["hybrid_parents"], ["Ulmus glabra", "Ulmus minor"])
        self.assertEqual(wood["synonyms"], [])

    def test_african_mahogany_unexpandable_abbreviations_are_dropped(self):
        # "Khaya spp., (primarily A. anthotheca and A. ivorensis; ...)": the site's
        # "A." matches no genus on the line, so it is not guessed.
        wood = extract("african-mahogany")
        self.assertEqual(wood["scientific_names"], ["Khaya spp."])
        self.assertEqual(wood["genus"], "Khaya")
        # The title has no "(Hardwood)", the breadcrumb "Hardwoods" does.
        self.assertEqual(wood["wood_type"], "Hardwood")


@needs_pages
class SustainabilityTest(unittest.TestCase):
    def test_category_under_another_scheme_is_not_iucn(self):
        # "not listed ... or on the IUCN Red List ... However, it is a protected
        # species listed as vulnerable under Australia's EPBC Act."
        wood = extract("waddywood")
        self.assertIn("vulnerable under Australia", wood["attributes"]["Sustainability"][0])
        self.assertIsNone(wood["iucn_status"])
        self.assertFalse(wood["cites_listed"])

    def test_not_on_red_list(self):
        wood = extract("chestnut-oak")
        self.assertIsNone(wood["iucn_status"])
        self.assertIsNone(wood["cites"])

    def test_cites_appendix(self):
        self.assertEqual(extract("pink-lapacho")["cites"], "Appendix II")

    def test_iucn_sentences(self):
        cases = {
            "This wood species is not listed in the CITES Appendices, and is reported by the IUCN as being a species of least concern.": "Least Concern",
            "This wood species is not listed in the CITES Appendices, but is on the IUCN Red List. It is listed as vulnerable due to a population reduction.": "Vulnerable",
            "Rengas is not listed in the CITES Appendices, and several species in the Gluta genus are reported by the IUCN as being of least concern; an exception is Gluta papuana, which is reported as vulnerable.": "Least Concern",
            "Additionally, of the three bubinga species, two of them (G. pellegriniana and G. tessmannii) are on the IUCN Red List as endangered, while the third, G. demeusei, is listed as near threatened.": "Endangered",
            "Quebracho is not listed in the CITES Appendices, and the IUCN reports that Schinopsis lorentzii (listed as S. quebracho-colorado) is a species of least concern.": "Least Concern",
            "Camphor is not listed in the CITES Appendices or on the IUCN Red List of Threatened Species, although a few related species are listed as vulnerable/endangered.": None,
            "This wood species is not listed in the CITES Appendices, and the primary species, Brosimum alicastrum, is not on the IUCN Red List. Another species, B. costaricanum, is listed as being a species of least concern": None,
            "Although Amazon Rosewood is not evaluated on the IUCN Red List of Threatened Species, it is listed on CITES appendix II.": None,
            "Technically it doesn't meet the Red List criteria of a vulnerable or endangered species.": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text[:60]):
                self.assertEqual(wooddb.iucn_status({"Sustainability": [text]}), expected)

    def test_cites_sentences(self):
        cases = {
            "This wood species is not listed in the CITES Appendices or on the IUCN Red List.": (False, None),
            "Brazilian rosewood is listed in CITES Appendix I, which is the most restrictive appendix.": (True, "Appendix I"),
            "This wood species is in CITES Appendix III, but is not on the IUCN Red List.": (True, "Appendix III"),
            # The first statement is about this wood; the later one about a relative.
            "This wood species is not listed in the CITES Appendices. However, the closely related Plectrocarpa sarmientoi is CITES-listed in Appendix II.": (False, None),
            "No statement here.": (None, None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text[:60]):
                self.assertEqual(wooddb.cites_status({"Sustainability": [text]}), expected)

    def test_status_field_wins_over_text(self):
        fields = {"IUCN Status": ["Critically Endangered"], "CITES Status": ["Appendix II"],
                  "Sustainability": ["It is also listed on the IUCN Red List as vulnerable."]}
        self.assertEqual(wooddb.iucn_status(fields), "Critically Endangered")
        self.assertEqual(wooddb.cites_status(fields), (True, "Appendix II"))


@needs_pages
class StubPageTest(unittest.TestCase):
    """Truncated profiles with only a few fields."""

    def test_bendee(self):
        wood = extract("bendee")
        self.assertEqual(wood["distribution"], "Australia (Queensland)")
        self.assertIsNone(wood["height_min_cm"])
        self.assertIsNone(wood["janka_hardness_n"])
        self.assertIsNone(wood["specific_gravity"])
        self.assertEqual(wood["common_uses"], [])
        self.assertTrue(wood["attributes"]["Note"][0].startswith("This is a truncated profile page."))
        self.assertNotIn("truncated profile", wood["description"])

    def test_janka_footnote_is_a_separate_value(self):
        wood = extract("black-sheoak")
        self.assertEqual(wood["attributes"]["Janka Hardness"], ["1,490 lbf (6,650 N)*", "*Estimated hardness based on specific gravity"])


class ScientificNameParsingTest(unittest.TestCase):
    def check(self, line, main, names, synonyms, parents=()):
        result = wooddb.scientific_names(line)
        self.assertEqual(result, (main, list(names), list(synonyms), list(parents)))

    def test_lines_from_the_site(self):
        self.check("Quercus robur", "Quercus robur", ["Quercus robur"], [])
        self.check("Carapa grandiflora and C. procera", "Carapa grandiflora", ["Carapa grandiflora", "Carapa procera"], [])
        self.check("Callitris columellaris (= C. glaucophylla)", "Callitris columellaris", ["Callitris columellaris"], ["Callitris glaucophylla"])
        self.check("Maclura tinctoria (syn. Chlorophora tinctoria, Morus tinctoria)", "Maclura tinctoria", ["Maclura tinctoria"],
                   ["Chlorophora tinctoria", "Morus tinctoria"])
        self.check("Allocasuarina luehmannii (formerly Casuarina luehmannii)", "Allocasuarina luehmannii",
                   ["Allocasuarina luehmannii"], ["Casuarina luehmannii"])
        self.check("Malus spp. (Malus domestica, Malus sieversii, Malus sylvestris, etc.)", "Malus spp.",
                   ["Malus spp.", "Malus domestica", "Malus sieversii", "Malus sylvestris"], [])
        self.check("Juglans x paradox (J. hindsii x J. regia)", "Juglans x paradox", ["Juglans x paradox"], [],
                   ["Juglans hindsii", "Juglans regia"])
        self.check("Possibly Inga spp. (almost universally mislabeled as Maclura tinctoria)", "Inga spp.", ["Inga spp."], [])
        self.check("Imbralyx leucanthus, very commonly listed as Millettia genus under older synonyms M. leucantha or M. pendula",
                   "Imbralyx leucanthus", ["Imbralyx leucanthus"], ["Millettia leucantha", "Millettia pendula"])
        self.check("Zelkova serrata var. tarokoensis", "Zelkova serrata var. tarokoensis", ["Zelkova serrata var. tarokoensis"], [])
        self.check("Palaquium spp., Payena spp.", "Palaquium spp.", ["Palaquium spp.", "Payena spp."], [])

    def test_no_latin_name(self):
        self.check("Hundreds of species among dozens of genera from the Poaceae (grass) family", None, [], [])


class ValueParsingTest(unittest.TestCase):
    def test_metric_value(self):
        self.assertEqual(wooddb.metric_value("42 lbs/ft3 (675 kg/m3)", "kg/m3"), 675.0)
        self.assertEqual(wooddb.metric_value("1,120 lbf (4,980 N)", "N"), 4980.0)
        self.assertEqual(wooddb.metric_value("1,656,000 lbf/in2 ( 11.42 GPa)", "GPa"), 11.42)
        self.assertEqual(wooddb.metric_value("38 lbs/ft3(615 kg/m3)", "kg/m3"), 615.0)

    def test_metric_value_rejects_ranges_typos_and_missing_data(self):
        self.assertIsNone(wooddb.metric_value("30.2 to 38.0 lbs/ft3 (485 to 610 kg/m3) depending on species", "kg/m3"))
        self.assertIsNone(wooddb.metric_value("31 lbs/ft3 (500 kg/m3) to 53 lbs/ft3 (850 kg/m3)", "kg/m3"))
        # The site printed "MPa" for a value in GPa, so the unit does not match.
        self.assertIsNone(wooddb.metric_value("1,300,000 lbf/in2 (8.97 MPa)", "GPa"))
        self.assertIsNone(wooddb.metric_value("No data available", "MPa"))
        self.assertIsNone(wooddb.metric_value(None, "N"))

    def test_tree_size(self):
        self.assertEqual(wooddb.tree_size_cm("100-130 ft (30-40 m) tall, 3-5 ft (1-1.5 m) trunk diameter"), (3000, 4000, 100, 150))
        self.assertEqual(wooddb.tree_size_cm("50–100 ft (15–30 m) tall, 3–5 ft (1–1.5 m) trunk diameter"), (1500, 3000, 100, 150))
        self.assertEqual(wooddb.tree_size_cm("15-30 ft (5-10 m) tall, 6-8 in (15-20 cm) trunk diameter"), (500, 1000, 15, 20))
        self.assertEqual(wooddb.tree_size_cm("130 ft (40 m) tall, 3 ft (1 m) trunk diameter"), (4000, 4000, 100, 100))
        self.assertEqual(wooddb.tree_size_cm("small to medium tree"), (None, None, None, None))
        # "(..3-6 m)" is a typo on the page and is not repaired.
        self.assertEqual(wooddb.tree_size_cm("50-65 ft (15-20 m) tall, 1-2 ft (..3-6 m) trunk diameter"), (1500, 2000, None, None))

    def test_split_list(self):
        self.assertEqual(wooddb.split_list("Veneer, musical instruments (guitars, violins), and boxes."),
                         ["Veneer", "musical instruments (guitars, violins)", "boxes"])
        self.assertEqual(wooddb.split_list("Imbuia, Imbuya, and variant spellings; Brazilian Walnut"),
                         ["Imbuia", "Imbuya", "variant spellings", "Brazilian Walnut"])
        self.assertEqual(wooddb.split_list(None), [])


if __name__ == "__main__":
    unittest.main()
