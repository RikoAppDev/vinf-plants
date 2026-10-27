import unittest

from extractor.normalize import clean_family, family_mapping, species_key


class FamilyTest(unittest.TestCase):
    def test_clean_family(self):
        self.assertEqual(clean_family("Asteraceae (Compositae) - Aster or Sunflower Family"), "Asteraceae")
        self.assertEqual(clean_family("commelinaceae"), "Commelinaceae")
        self.assertEqual(clean_family("‎Ulmaceae"), "Ulmaceae")
        self.assertEqual(clean_family("Leguminosae"), "Fabaceae")
        self.assertIsNone(clean_family("c"))
        self.assertIsNone(clean_family(""))

    def test_typos_are_repaired(self):
        raw = ["Rosaceae"] * 50 + ["Roseaceae", "Rosacea", "Roseacae"] + ["Solanaceae"] * 10 + ["Solonaceae"]
        mapping = family_mapping(raw)
        self.assertEqual(mapping["Roseaceae"], "Rosaceae")
        self.assertEqual(mapping["Rosacea"], "Rosaceae")
        self.assertEqual(mapping["Roseacae"], "Rosaceae")
        self.assertEqual(mapping["Solonaceae"], "Solanaceae")

    def test_real_families_that_look_alike_stay_apart(self):
        raw = (["Rosaceae"] * 200 + ["Moraceae"] * 30 + ["Rutaceae"] * 20 + ["Lamiaceae"] * 100
               + ["Lauraceae"] * 15 + ["Fabaceae"] * 100 + ["Taxaceae"] * 10 + ["Polygonaceae"] * 30
               + ["Polygalaceae"] * 2)
        mapping = family_mapping(raw)
        for family in ("Moraceae", "Rutaceae", "Lauraceae", "Taxaceae", "Polygalaceae"):
            self.assertEqual(mapping[family], family)

    def test_one_letter_stem_differences_are_real_families(self):
        # Both pairs occur on PFAF.
        raw = ["Asteraceae"] * 300 + ["Asteliaceae"] * 4 + ["Melanthiaceae"] * 20 + ["Melianthaceae"] * 2
        mapping = family_mapping(raw)
        self.assertEqual(mapping["Asteliaceae"], "Asteliaceae")
        self.assertEqual(mapping["Melianthaceae"], "Melianthaceae")

    def test_non_family_values_become_none(self):
        mapping = family_mapping(["Rosaceae"] * 5 + ["hy-DRAN-jee-ah kwer-sih-FOH-lee-ah", "c"])
        self.assertIsNone(mapping["hy-DRAN-jee-ah kwer-sih-FOH-lee-ah"])
        self.assertIsNone(mapping["c"])


class SpeciesKeyTest(unittest.TestCase):
    def test_binomials(self):
        self.assertEqual(species_key("Quercus robur L."), "quercus robur")
        self.assertEqual(species_key("Quercus robur 'Fastigiata'"), "quercus robur")
        self.assertEqual(species_key("Arctostaphylos uva-ursi"), "arctostaphylos uva-ursi")

    def test_hybrids_keep_their_sign(self):
        self.assertEqual(species_key("Abelia x grandiflora"), "abelia × grandiflora")
        self.assertEqual(species_key("Abelia ×grandiflora"), "abelia × grandiflora")

    def test_not_binomials(self):
        self.assertEqual(species_key("Acer"), "")
        self.assertEqual(species_key("Acer spp."), "")
        self.assertEqual(species_key(""), "")


if __name__ == "__main__":
    unittest.main()
