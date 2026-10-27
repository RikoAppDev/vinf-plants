import os
import unittest

from extractor import ncsu

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


class QuercusAlbaTest(unittest.TestCase):
    """A tree page: has dimensions, many sections and repeated labels."""

    @classmethod
    def setUpClass(cls):
        cls.plant = ncsu.extract_plant(load("ncsu_quercus_alba.html"))

    def test_names(self):
        self.assertEqual(self.plant["scientific_name"], "Quercus alba")
        self.assertIn("White Oak", self.plant["common_names"])
        self.assertIn("American White Oak", self.plant["common_names"])

    def test_taxonomy(self):
        self.assertEqual(self.plant["genus"], "Quercus")
        self.assertEqual(self.plant["family"], "Fagaceae")

    def test_dimensions_are_converted_to_centimetres(self):
        self.assertEqual((self.plant["height_min_cm"], self.plant["height_max_cm"]), (1524, 4115))
        self.assertEqual((self.plant["width_min_cm"], self.plant["width_max_cm"]), (1524, 2438))

    def test_hardiness_zones(self):
        self.assertEqual((self.plant["zone_min"], self.plant["zone_max"]), (3, 9))

    def test_multi_valued_and_free_text_attributes(self):
        attributes = self.plant["attributes"]
        self.assertGreaterEqual(len(attributes), 50)
        self.assertIn("Native Plant", attributes["Plant Type"])
        self.assertTrue(attributes["Description"][0])
        self.assertNotIn("<", " ".join(attributes["Description"]))


class HydrocotyleAmericanaTest(unittest.TestCase):
    """A small herb page: no dimensions, has synonyms."""

    @classmethod
    def setUpClass(cls):
        cls.plant = ncsu.extract_plant(load("ncsu_hydrocotyle_americana.html"))

    def test_names_and_synonyms(self):
        self.assertEqual(self.plant["scientific_name"], "Hydrocotyle americana")
        self.assertIn("Navelwort", self.plant["common_names"])
        self.assertIn("Hydrocotyle nitens", self.plant["synonyms"])

    def test_taxonomy(self):
        self.assertEqual(self.plant["family"], "Araliaceae")

    def test_missing_dimensions_stay_empty(self):
        self.assertIsNone(self.plant["height_min_cm"])
        self.assertIsNone(self.plant["height_max_cm"])

    def test_html_entities_are_decoded(self):
        origin = " ".join(self.plant["attributes"]["Country Or Region Of Origin"])
        self.assertIn("North Central & Eastern United States", origin)


class UnitParsingTest(unittest.TestCase):
    def test_length_range(self):
        self.assertEqual(ncsu.length_range_cm("Height: 50 ft. 0 in. - 135 ft. 0 in."), (1524, 4115))
        self.assertEqual(ncsu.length_range_cm("Height: 0 ft. 6 in. - 1 ft. 0 in."), (15, 30))
        self.assertEqual(ncsu.length_range_cm("no numbers here"), (None, None))

    def test_zone_range(self):
        self.assertEqual(ncsu.zone_range("3a, 3b, 4a, 9b"), (3, 9))
        self.assertEqual(ncsu.zone_range("10a, 11b"), (10, 11))
        self.assertEqual(ncsu.zone_range(""), (None, None))

    def test_clean_text(self):
        self.assertEqual(ncsu.clean_text(" <p>Oak &amp;\n  <em>ash</em></p> "), "Oak & ash")


if __name__ == "__main__":
    unittest.main()
