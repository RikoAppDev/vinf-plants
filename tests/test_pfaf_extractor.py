import os
import unittest

from extractor import pfaf

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pfaf")

# 20 saved pages: 12 picked with random.Random(42) across the alphabet (one page
# per letter) and 8 edge cases. Expected values were checked against the raw HTML.
NOT_PLANT_PAGES = {"crataegus_schraderiana.html", "harishtest.html"}


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="replace") as handle:
        return handle.read()


def plant(name):
    return pfaf.extract_plant(load(name))


class AllFixturesTest(unittest.TestCase):
    """Record contract on every fixture page."""

    @classmethod
    def setUpClass(cls):
        cls.records = {name: plant(name) for name in sorted(os.listdir(FIXTURES)) if name.endswith(".html")}

    def test_twenty_fixture_pages(self):
        self.assertEqual(len(self.records), 20)

    def test_only_soft_404_and_test_entry_return_none(self):
        self.assertEqual({name for name, record in self.records.items() if record is None}, NOT_PLANT_PAGES)

    def test_contract_fields_and_types(self):
        for name, record in self.records.items():
            if record is None:
                continue
            with self.subTest(page=name):
                self.assertTrue(record["scientific_name"])
                self.assertIsInstance(record["common_names"], list)
                self.assertIsInstance(record["synonyms"], list)
                self.assertIsInstance(record["attributes"], dict)
                for key in ("zone_min", "zone_max", "height_min_cm", "height_max_cm", "width_min_cm",
                            "width_max_cm", "edibility_rating", "medicinal_rating", "other_uses_rating"):
                    self.assertTrue(record[key] is None or isinstance(record[key], int), key)
                for values in record["attributes"].values():
                    self.assertTrue(values and all(isinstance(value, str) and value for value in values))

    def test_text_is_clean(self):
        for name, record in self.records.items():
            if record is None:
                continue
            with self.subTest(page=name):
                self.assertNotIn("<", record["description"])
                self.assertNotIn("&nbsp;", record["description"])
                self.assertNotIn("can not take any responsibility", record["description"])
                self.assertNotIn(record["scientific_name"], record["synonyms"])


class RibesOdoratumTest(unittest.TestCase):
    """Typical page: abbreviated synonyms with authorities, all summary rows."""

    @classmethod
    def setUpClass(cls):
        cls.plant = plant("ribes_odoratum.html")

    def test_name_and_authority(self):
        self.assertEqual(self.plant["scientific_name"], "Ribes odoratum")
        self.assertEqual(self.plant["authority"], "H.L.Wendl.")
        self.assertEqual(self.plant["genus"], "Ribes")
        self.assertEqual(self.plant["family"], "Grossulariaceae")
        self.assertEqual(self.plant["common_names"], ["Buffalo Currant"])

    def test_synonyms_expand_genus_and_drop_authorities(self):
        # "R. aureum villosum. DC. R. aureum. non Pursh. R. fragrans. non Pall. R. longiflorum."
        self.assertEqual(self.plant["synonyms"],
                         ["Ribes aureum villosum", "Ribes aureum", "Ribes fragrans", "Ribes longiflorum"])

    def test_zones_and_size(self):
        self.assertEqual((self.plant["zone_min"], self.plant["zone_max"]), (4, 8))
        self.assertEqual((self.plant["height_min_cm"], self.plant["height_max_cm"]), (None, 250))
        self.assertEqual((self.plant["width_min_cm"], self.plant["width_max_cm"]), (None, 250))

    def test_physical_characteristics(self):
        self.assertEqual(self.plant["habit"], "Shrub")
        self.assertEqual(self.plant["leaf_type"], "deciduous")
        self.assertIsNone(self.plant["growth_rate"])
        self.assertEqual(self.plant["uk_hardiness_zone"], 5)
        self.assertIs(self.plant["frost_tender"], False)
        self.assertEqual(self.plant["flowering_months"], ["April"])
        self.assertEqual(self.plant["soil"], ["light (sandy)", "medium (loamy)", "heavy (clay)"])
        self.assertEqual(self.plant["ph"], ["mildly acid", "neutral", "basic (mildly alkaline)"])
        self.assertEqual(self.plant["light"], ["semi-shade (light woodland)", "no shade"])
        self.assertEqual(self.plant["moisture"], ["moist"])

    def test_ratings(self):
        self.assertEqual((self.plant["edibility_rating"], self.plant["medicinal_rating"],
                          self.plant["other_uses_rating"]), (4, 1, 0))
        self.assertEqual(self.plant["attributes"]["Other Uses Rating"], ["0 of 5"])

    def test_uses_tags_and_prose(self):
        attributes = self.plant["attributes"]
        self.assertEqual(self.plant["edible_parts"], ["Flowers", "Fruit"])
        self.assertEqual(attributes["Edible Uses"], ["Condiment", "Tea"])
        self.assertEqual(attributes["Medicinal Uses"], ["Antidote"])
        self.assertEqual(attributes["Special Uses"], ["Food Forest", "Scented Plants"])
        self.assertTrue(self.plant["edible_uses"].startswith("Fruit - raw or cooked[2, 62, 85, 257]."))
        self.assertEqual(self.plant["medicinal_uses"], "a poultice of the plant has been applied to snakebites[257].")
        self.assertEqual(self.plant["other_uses"], "None known")

    def test_labelled_rows(self):
        attributes = self.plant["attributes"]
        self.assertEqual(attributes["Care"], ["Fully Hardy", "Moist Soil", "Semi-shade", "Full sun"])
        self.assertEqual(attributes["Plant Habitats"], ["Woodland Garden", "Sunny Edge", "Dappled Shade"])
        self.assertEqual(self.plant["hazards"], "None known")
        self.assertEqual(self.plant["habitat"], "Rocky bluffs and slopes, also along the sides of streams[235].")
        self.assertTrue(self.plant["range"].startswith("Central N. America - Saskatchewan"))
        self.assertTrue(self.plant["native_range"].startswith("NORTHERN AMERICA: Canada, Ontario"))
        self.assertEqual(self.plant["weed_potential"], "No")
        self.assertIsNone(self.plant["weed_potential_text"])
        self.assertIsNone(self.plant["iucn_status"])

    def test_boilerplate_is_removed_but_facts_stay(self):
        self.assertNotIn("Plant Heat Zones show", self.plant["cultivation"])
        self.assertNotIn("For polyculture design", self.plant["cultivation"])
        self.assertIn("heat tolerant in zones 8 through 5", self.plant["cultivation"])
        self.assertNotIn("None known", self.plant["description"])


class NotPlantPagesTest(unittest.TestCase):
    def test_soft_404_returns_none(self):
        self.assertIsNone(plant("crataegus_schraderiana.html"))

    def test_sitemap_test_entry_returns_none(self):
        self.assertIsNone(plant("harishtest.html"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(pfaf.extract_plant(""))


class CultivarTest(unittest.TestCase):
    """Fragaria vesca 'Semperflorens': cultivar name, soil and pH tolerances."""

    @classmethod
    def setUpClass(cls):
        cls.plant = plant("fragaria_vesca_semperflorens.html")

    def test_cultivar_name(self):
        self.assertEqual(self.plant["scientific_name"], "Fragaria vesca 'Semperflorens'")
        self.assertEqual(self.plant["genus"], "Fragaria")
        self.assertEqual(self.plant["authority"], "L.")
        self.assertEqual(self.plant["synonyms"], ["Fragaria alpina"])

    def test_statement(self):
        self.assertEqual(self.plant["flowering_months"],
                         ["May", "June", "July", "August", "September", "October", "November"])
        self.assertEqual(self.plant["tolerates"], ["heavy clay", "very alkaline"])
        self.assertEqual((self.plant["height_max_cm"], self.plant["width_max_cm"]), (30, 30))
        self.assertEqual(self.plant["edibility_rating"], 5)


class SantalumFreycinetianumTest(unittest.TestCase):
    """Heading without authority, "No synonyms are recorded", an IUCN category."""

    @classmethod
    def setUpClass(cls):
        cls.plant = plant("santalum_freycinetianum.html")

    def test_missing_authority_and_synonyms(self):
        self.assertEqual(self.plant["scientific_name"], "Santalum freycinetianum")
        self.assertIsNone(self.plant["authority"])
        self.assertEqual(self.plant["synonyms"], [])
        self.assertEqual(self.plant["attributes"]["Synonyms"], ["No synonyms are recorded for this name."])

    def test_iucn(self):
        self.assertEqual(self.plant["iucn_status"], "Status: Endangered B1ab(iii)+2ab(iii)")
        self.assertEqual(self.plant["iucn_category"], "Endangered")

    def test_statement(self):
        self.assertEqual(self.plant["growth_rate"], "slow")
        self.assertEqual(self.plant["moisture"], ["dry"])
        self.assertEqual(self.plant["tolerates"], ["nutritionally poor", "very acid", "drought", "maritime exposure"])
        self.assertEqual(self.plant["weed_potential"], "Yes")


class BracketedNameTest(unittest.TestCase):
    def test_bracketed_name_becomes_synonym(self):
        record = plant("cimicifuga_racemosa_actaea_racemosa.html")
        self.assertEqual(record["scientific_name"], "Cimicifuga racemosa")
        self.assertEqual(record["authority"], "(L.)Nutt.")
        # Also listed in the Synonyms field as "Actaea racemosa L."; kept once.
        self.assertEqual(record["synonyms"], ["Actaea racemosa"])
        self.assertEqual(record["light"], ["semi-shade (light woodland)"])


class TulipaEdulisTest(unittest.TestCase):
    def test_abbreviation_refers_to_last_spelled_out_genus(self):
        # "T. graminifolia. Amana edulis. A. graminifolia. Orithyia edulis."
        record = plant("tulipa_edulis.html")
        self.assertEqual(record["synonyms"],
                         ["Tulipa graminifolia", "Amana edulis", "Amana graminifolia", "Orithyia edulis"])

    def test_no_common_name_and_no_shade(self):
        record = plant("tulipa_edulis.html")
        self.assertEqual(record["common_names"], [])
        self.assertEqual(record["habit"], "Bulb")
        self.assertEqual(record["light"], ["no shade"])  # "It cannot grow in the shade."


class CamelliaSasanquaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plant = plant("camellia_sasanqua.html")

    def test_flowering_across_new_year(self):
        self.assertEqual(self.plant["flowering_months"],
                         ["October", "November", "December", "January", "February", "March", "April"])

    def test_repeated_tags_are_kept_once(self):
        self.assertEqual(self.plant["edible_parts"], ["Oil"])
        self.assertEqual(self.plant["attributes"]["Edible Uses"], ["Oil", "Tea"])

    def test_ph_and_tolerance(self):
        self.assertEqual(self.plant["ph"], ["mildly acid", "neutral"])
        self.assertEqual(self.plant["tolerates"], ["very acid"])
        self.assertEqual(self.plant["leaf_type"], "evergreen")


class ComingSoonTest(unittest.TestCase):
    """"Coming soon" means no value yet."""

    def test_usda_coming_soon(self):
        record = plant("debregeasia_wallichiana.html")
        self.assertEqual((record["zone_min"], record["zone_max"]), (None, None))
        self.assertNotIn("USDA hardiness", record["attributes"])
        self.assertIsNone(record["native_range"])
        self.assertEqual(record["common_names"], [])

    def test_native_range_coming_soon(self):
        record = plant("cardamine_rotundifolia.html")
        self.assertIsNone(record["native_range"])
        self.assertNotIn("Native Range", record["attributes"])
        self.assertEqual((record["zone_min"], record["zone_max"]), (5, 9))


class RandomPagesTest(unittest.TestCase):
    """Pages picked with the fixed seed."""

    def test_abronia_latifolia(self):
        record = plant("abronia_latifolia.html")
        self.assertEqual(record["authority"], "Esch.")
        self.assertEqual(record["common_names"], ["Sand Verbena", "Coastal sand verbena"])
        self.assertEqual(record["synonyms"], ["Abronia arenaria"])
        self.assertEqual((record["height_max_cm"], record["width_max_cm"]), (10, 50))
        self.assertEqual(record["soil"], ["light (sandy)"])
        self.assertEqual(record["moisture"], ["dry", "moist"])
        self.assertEqual(record["tolerates"], ["maritime exposure"])
        self.assertEqual(record["attributes"]["Plant Habitats"],
                         ["Cultivated Beds", "East Wall. By.", "South Wall. By.", "West Wall. By."])

    def test_cardamine_rotundifolia(self):
        record = plant("cardamine_rotundifolia.html")
        self.assertEqual(record["moisture"], ["moist", "wet", "water"])
        self.assertEqual(record["flowering_months"], ["April", "May", "June", "July", "August"])
        self.assertEqual(record["attributes"]["Plant Habitats"], ["Pond", "Bog Garden"])
        self.assertEqual(record["edible_uses"], "Leaves - raw or cooked[105. 161, 177]. A hot water-cress like flavour[2, K].")

    def test_debregeasia_wallichiana(self):
        record = plant("debregeasia_wallichiana.html")
        self.assertEqual(record["authority"], "(Wedd.)Wedd.")
        self.assertEqual((record["habit"], record["leaf_type"], record["height_max_cm"]), ("Tree", "evergreen", 500))
        self.assertEqual(record["attributes"]["Other Uses"], ["Fibre"])
        self.assertEqual(record["other_uses"], "A fibre is obtained from the bark. It is used for making twine and rope[146].")
        self.assertEqual(record["edible_uses"], "None known")

    def test_epilobium_hirsutum(self):
        record = plant("epilobium_hirsutum.html")
        self.assertTrue(record["hazards"].startswith("One report says that the plant might be poisonous[179]."))
        self.assertEqual(record["weed_potential"], "Yes")
        self.assertEqual(record["attributes"]["Special Uses"], ["Attracts Wildlife", "Food Forest", "Scented Plants"])
        self.assertEqual(record["attributes"]["Medicinal Uses"], ["Astringent"])
        self.assertEqual(record["light"], ["no shade"])

    def test_hibiscus_acetosella(self):
        record = plant("hibiscus_acetosella.html")
        self.assertEqual(record["authority"], "Welw. ex Hiern.")
        self.assertEqual(record["synonyms"], ["Hibiscus eetveldeanus", "Hibiscus surattensis eetveldeanus"])
        self.assertEqual((record["habit"], record["growth_rate"]), ("Annual/Perennial", "medium"))
        self.assertIs(record["frost_tender"], True)
        self.assertTrue(record["summary"].startswith("Taxonomic Note:"))
        self.assertEqual(record["attributes"]["Other Names"], ["False Roselle", "African rosemallow", "Cranberry Hibiscus"])

    def test_ipomoea_purpurea_inline_labels(self):
        record = plant("ipomoea_purpurea.html")
        self.assertEqual(record["habit"], "Annual Climber")
        attributes = record["attributes"]
        self.assertEqual(attributes["Bloom Color"], ["Blue", "Pink", "Purple", "Red", "White"])
        self.assertEqual(attributes["Main Bloom Time"], ["Early fall", "Late summer", "Mid summer"])
        self.assertEqual(attributes["Form"], ["Spreading or horizontal", "Variable spread"])
        self.assertEqual(attributes["Landscape Uses"], ["Arbor", "Container", "Specimen"])
        self.assertEqual(attributes["Medicinal Uses"], ["Anthelmintic", "Diuretic", "Hallucinogenic", "Laxative"])

    def test_nageia_wallichiana(self):
        record = plant("nageia_wallichiana.html")
        self.assertEqual(record["synonyms"], ["Decussocarpus wallichianus", "Nageia blumei", "Nageia latifolia"])
        self.assertEqual(record["iucn_category"], "Least Concern")
        self.assertEqual(record["light"], ["full shade (deep woodland)", "semi-shade (light woodland)", "no shade"])
        self.assertEqual((record["height_max_cm"], record["width_max_cm"]), (2000, 2000))
        self.assertEqual(record["attributes"]["Other Uses"], ["Fuel", "Resin", "Wood"])

    def test_rumex_graminifolius(self):
        record = plant("rumex_graminifolius.html")
        self.assertEqual(record["synonyms"], ["Acetosella graminifolia"])
        self.assertTrue(record["hazards"].startswith("Plants can contain quite high levels of oxalic acid"))
        self.assertEqual(record["edible_uses"], "Leaves - raw[177].")
        self.assertEqual(record["flowering_months"], [])

    def test_ulmus_parvifolia(self):
        record = plant("ulmus_parvifolia.html")
        self.assertEqual(record["synonyms"], ["Ulmus chinensis"])
        self.assertEqual((record["zone_min"], record["zone_max"]), (5, 10))
        self.assertEqual((record["height_max_cm"], record["width_max_cm"]), (1800, 1800))
        self.assertEqual(record["flowering_months"], ["September", "October"])
        self.assertEqual(record["attributes"]["Landscape Uses"],
                         ["Aggressive surface roots possible", "Pollard", "Specimen", "Street tree"])

    def test_viola_obtusa(self):
        record = plant("viola_obtusa.html")
        self.assertEqual(record["authority"], "(Makino.)Makino.")
        self.assertEqual(record["common_names"], [])
        self.assertEqual(record["ph"], ["mildly acid", "neutral"])
        self.assertEqual(record["edible_parts"], ["Flowers", "Leaves"])

    def test_xanthoceras_sorbifolium(self):
        record = plant("xanthoceras_sorbifolium.html")
        self.assertEqual((record["habit"], record["growth_rate"]), ("Shrub", "slow"))
        self.assertEqual((record["height_max_cm"], record["width_max_cm"]), (600, 250))
        self.assertEqual(record["attributes"]["Special Uses"], ["Carbon Farming", "Food Forest"])

    def test_yucca_recurvifolia(self):
        record = plant("yucca_recurvifolia.html")
        self.assertEqual(record["synonyms"], ["Yucca gloriosa recurvifolia", "Yucca pendula", "Yucca recurva"])
        self.assertEqual(record["tolerates"], ["nutritionally poor", "drought", "strong winds", "atmospheric pollution"])
        self.assertEqual(record["attributes"]["Other Uses"], ["Fibre", "Soap"])


class HelperTest(unittest.TestCase):
    def test_split_heading(self):
        self.assertEqual(pfaf.split_heading("Ribes odoratum - H.L.Wendl."), ("Ribes odoratum", "H.L.Wendl."))
        self.assertEqual(pfaf.split_heading("Fragaria - ."), ("Fragaria", None))
        self.assertEqual(pfaf.split_heading("Santalum freycinetianum -"), ("Santalum freycinetianum", None))
        # the site repeats the name instead of an authority on a few pages
        self.assertEqual(pfaf.split_heading("Gluta usitata - Gluta usitata"), ("Gluta usitata", None))

    def test_parse_synonyms(self):
        self.assertEqual(pfaf.parse_synonyms("Toxicodendron radicans. T. pubescens. P.Mill.", "Rhus"),
                         ["Toxicodendron radicans", "Toxicodendron pubescens"])
        self.assertEqual(pfaf.parse_synonyms("Trifolium repens L. var. atropurpureum", "Trifolium"),
                         ["Trifolium repens var. atropurpureum"])
        self.assertEqual(pfaf.parse_synonyms("Endymion non-scriptus. Larix x. eurolepis. Henry.", "Hyacinthoides"),
                         ["Endymion non-scriptus", "Larix x eurolepis"])
        self.assertEqual(pfaf.parse_synonyms("No synonyms are recorded for this name.", "Annona"), [])
        self.assertEqual(pfaf.parse_synonyms("R. pentalobus Hayata is a synonym of R. rolfei J.E.Vidal", "Rubus"),
                         ["Rubus pentalobus", "Rubus rolfei"])

    def test_zone_range(self):
        self.assertEqual(pfaf.zone_range("4-8"), (4, 8))
        self.assertEqual(pfaf.zone_range("10-13"), (10, 13))
        self.assertEqual(pfaf.zone_range(""), (None, None))

    def test_month_span(self):
        self.assertEqual(pfaf.month_span("November", "January"), ["November", "December", "January"])
        self.assertEqual(pfaf.month_span("May", "May"), ["May"])

    def test_iucn(self):
        self.assertEqual(pfaf.iucn("IUCN Red List of Threatened Plants Status : "), (None, None))
        self.assertEqual(pfaf.iucn("IUCN Red List of Threatened Plants Status : Least concern."),
                         ("Least concern.", "Least Concern"))
        # A state list after "not yet assessed" is not an IUCN category.
        text = "This taxon has not yet been assessed. Other information: Vermont (wild garlic) :Threatened."
        self.assertEqual(pfaf.iucn("IUCN Red List of Threatened Plants Status : " + text), (text, None))

    def test_parse_physical(self):
        facts = pfaf.parse_physical(
            "X y is a deciduous Tree growing to 20 m (65ft) by 30 m (98ft) at a slow rate.It is in leaf all year. "
            "It prefers dry moist or wet soil and can tolerate drought. It cannot grow in the shade.")
        self.assertEqual((facts["habit"], facts["leaf_type"], facts["growth_rate"]), ("Tree", "deciduous", "slow"))
        self.assertEqual((facts["height_cm"], facts["width_cm"]), (2000, 3000))
        self.assertEqual(facts["moisture"], ["dry", "moist", "wet"])
        self.assertEqual(facts["light"], ["no shade"])
        self.assertEqual(facts["tolerates"], ["drought"])
        # A zero size is a database placeholder, not a measurement.
        self.assertIsNone(pfaf.parse_physical("X y is a PERENNIAL growing to 0 m (0ft).")["height_cm"])

    def test_clean_text(self):
        self.assertEqual(pfaf.clean_text(" <p>Oak &amp;\n  <em>ash</em></p> "), "Oak & ash")


if __name__ == "__main__":
    unittest.main()
