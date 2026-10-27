import unittest

from tools.merge_entities import entity_key, merge


def record(source, name, synonyms=(), url=None):
    return {"source": source, "scientific_name": name, "synonyms": list(synonyms),
            "url": url or "https://{}/{}".format(source, name.replace(" ", "-"))}


class EntityKeyTest(unittest.TestCase):
    def test_species_and_qualifiers(self):
        self.assertEqual(entity_key("Quercus robur"), "quercus robur")
        self.assertEqual(entity_key("Quercus robur 'Fastigiata'"), "quercus robur fastigiata")
        self.assertEqual(entity_key("Brassica oleracea Kale Group"), "brassica oleracea kale group")
        self.assertEqual(entity_key("Berberis thunbergii Sunjoy® Group"), "berberis thunbergii sunjoy group")
        self.assertEqual(entity_key("Dianthus chinensis x barbatus"), "dianthus chinensis x barbatus")

    def test_cultivar_with_apostrophe_differs_from_shorter_cultivar(self):
        self.assertNotEqual(entity_key("Phlox paniculata 'David'"), entity_key("Phlox paniculata 'David's Lavender'"))

    def test_hybrid_sign_spellings_agree(self):
        self.assertEqual(entity_key("Abelia x grandiflora"), entity_key("Abelia × grandiflora"))

    def test_genus_level_pages(self):
        self.assertEqual(entity_key("Abelia 'Edward Goucher'"), "abelia edward goucher")
        self.assertEqual(entity_key("Hosta"), "hosta")


class MergeTest(unittest.TestCase):
    def test_same_name_from_two_sites_is_one_entity(self):
        entities, stats = merge([record("ncsu", "Quercus robur"), record("pfaf", "Quercus robur")])
        self.assertEqual(stats["entities"], 1)
        self.assertEqual(entities[0]["n_sources"], 2)

    def test_listed_synonym_joins_the_accepted_name(self):
        _entities, stats = merge([record("ncsu", "Ranunculus ficaria", synonyms=["Ficaria verna"]),
                                  record("pfaf", "Ficaria verna")])
        self.assertEqual(stats["entities"], 1)
        self.assertEqual(stats["synonym_merges"], 1)

    def test_two_pages_of_one_site_are_never_merged(self):
        # An ambiguous synonym must not collapse two plants that one site keeps apart.
        _entities, stats = merge([record("ncsu", "Acer rubrum", synonyms=["Acer saccharinum"]),
                                  record("ncsu", "Acer saccharinum")])
        self.assertEqual(stats["entities"], 2)


if __name__ == "__main__":
    unittest.main()
