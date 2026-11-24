import json
import os
import shutil
import tempfile
import unittest

from lucene_index import documents
from lucene_index.documents import entity_document, iucn_code

NCSU_URL = "https://plants.ces.ncsu.edu/plants/quercus-robur/"
PFAF_URL = "https://pfaf.org/user/Plant.aspx?LatinName=Quercus+robur"
TSO_URL = "https://www.treesandshrubsonline.org/articles/quercus/quercus-robur/"
WOOD_URL = "https://www.wood-database.com/english-oak/"


def ncsu(**fields):
    record = {"url": NCSU_URL, "source": "ncsu", "scientific_name": "Quercus robur", "genus": "Quercus",
              "family": "Fagaceae", "common_names": ["English Oak", "Pedunculate Oak"], "synonyms": [],
              "description": "English Oak is a large deciduous tree.", "zone_min": 5, "zone_max": 8,
              "height_max_cm": 2134,
              "attributes": {"Plant Type": ["Tree"], "Light": ["Full sun (6 or more hours of direct sunlight a day)"],
                             "Soil Texture": ["Clay", "Loam (Silt)"], "Soil pH": ["Acid (<6.0)"],
                             "Woody Plant Leaf Characteristics": ["Deciduous"], "Maintenance": ["Low"],
                             "Resistance To Challenges": ["Drought"], "Country Or Region Of Origin": ["Europe"],
                             "Leaf Description": ["The leaves have rounded lobes."],
                             "Phonetic Spelling": ["KWER-kus ROH-bur"]}}
    record.update(fields)
    return record


def pfaf(**fields):
    record = {"url": PFAF_URL, "source": "pfaf", "scientific_name": "Quercus robur", "authority": "L.",
              "genus": "Quercus", "family": "Fagaceae", "common_names": ["english oak"],
              "synonyms": ["Quercus pedunculata", "Quercus robur"], "habit": "Tree", "leaf_type": "deciduous",
              "light": ["no shade", "semi-shade (light woodland)"], "soil": ["heavy (clay)"], "ph": ["neutral"],
              "moisture": ["moist"], "tolerates": ["drought"], "range": "Europe, including Britain.",
              "edible_uses": "Seed - cooked.", "medicinal_uses": "None known", "other_uses": "Tannin.",
              "description": "Quercus robur is a deciduous Tree.", "cultivation": "Succeeds in heavy clay soils.",
              "hazards": "None known", "zone_min": 4, "zone_max": 8, "height_max_cm": 3000,
              "edibility_rating": 4, "medicinal_rating": 3, "iucn_category": None,
              "attributes": {"Special Uses": ["Food Forest"], "Bloom Color": ["Unknown"]}}
    record.update(fields)
    return record


def tso(**fields):
    record = {"url": TSO_URL, "source": "tso", "scientific_name": "Quercus robur", "authority": "L.",
              "genus": "Quercus", "family": "Fagaceae", "common_names": ["Common Oak"],
              "synonyms": ["Quercus pedunculata"], "article_type": "species",
              "description": "A deciduous tree which develops a broad, spreading head. Leaves stalkless.",
              "conservation_status": None, "conservation_code": None, "distribution": None, "attributes": {}}
    record.update(fields)
    return record


def wooddb(**fields):
    record = {"url": WOOD_URL, "source": "wooddb", "scientific_name": "Quercus robur", "genus": "Quercus",
              "family": None, "common_names": ["English Oak", "European Oak"], "synonyms": [],
              "wood_type": "Hardwood", "density_kg_m3": 675.0, "janka_hardness_n": 4980,
              "common_uses": ["Cabinetry", "No data available"], "distribution": "Most of Europe",
              "iucn_status": "Least Concern", "description": "Heartwood is a light to medium brown.",
              "height_max_cm": 3500, "attributes": {}}
    record.update(fields)
    return record


def wikipedia(level=0, **fields):
    page = {"page_id": 201415, "title": "Quercus robur", "binomial": "Quercus robur", "rank": "species",
            "authority": "L. (1753)", "year_described": 1753, "iucn_status": "LC",
            "synonyms": ["Quercus pedunculata", "Quercus pyrenaica"], "common_names": ["English oak", "European oak"],
            "categories": ["Flora of Southeastern Europe", "Trees of Europe", "Garden plants of Europe"],
            "lead": "Quercus robur, the English oak, is a species of flowering plant.",
            "match": {"via": "box", "level": level,
                      "level_name": {0: "own name", 1: "species of a cultivar or variety", 2: "genus"}[level],
                      "ambiguous_pages": 1}}
    page.update(fields)
    return page


def entity(records, wiki=None, key="quercus robur", names=("Quercus robur",)):
    sources = {}
    for record in records:
        sources.setdefault(record["source"], []).append(record["url"])
    return ({"entity_id": 7, "key": key, "aliases": [], "scientific_names": list(names), "sources": sources,
             "n_sources": len(sources), "wikipedia": wiki},
            {record["url"]: documents.slim_record(record) for record in records})


def document(records, wiki=None, **kwargs):
    return entity_document(*entity(records, wiki, **kwargs))


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.doc = document([wooddb(), tso(), pfaf(), ncsu()], wikipedia())

    def test_ids_sources_and_urls_follow_the_site_order(self):
        self.assertEqual(self.doc["id"], ["7"])
        self.assertEqual(self.doc["key"], ["quercus robur"])
        self.assertEqual(self.doc["source"], ["ncsu", "pfaf", "tso", "wooddb"])
        self.assertEqual(self.doc["url"], [NCSU_URL, PFAF_URL, TSO_URL, WOOD_URL])
        self.assertEqual(self.doc["n_sources"], 4)

    def test_names_of_all_records_and_wikipedia(self):
        self.assertEqual(self.doc["name"], ["Quercus robur"])
        self.assertEqual(self.doc["common_name"],
                         ["English Oak", "Pedunculate Oak", "Common Oak", "European Oak"])
        self.assertEqual(self.doc["family"], ["Fagaceae"])
        self.assertEqual(self.doc["genus"], ["Quercus"])

    def test_synonyms_are_unique_and_never_the_plant_itself(self):
        self.assertEqual(self.doc["synonym"], ["Quercus pedunculata", "Quercus pyrenaica"])

    def test_the_species_of_a_wood_page_about_several_species_are_synonyms(self):
        merbau = wooddb(url="https://www.wood-database.com/merbau/", scientific_name="Intsia spp.", genus="Intsia",
                        scientific_names=["Intsia spp.", "Intsia bijuga", "Intsia palembanica"])
        doc = document([merbau], key="intsia spp", names=("Intsia spp.",))
        self.assertEqual(doc["name"], ["Intsia spp."])
        self.assertEqual(doc["synonym"], ["Intsia bijuga", "Intsia palembanica"])

    def test_attributes_of_both_sites_share_one_field(self):
        self.assertEqual(self.doc["plant_type"], ["Tree", "Hardwood"])
        self.assertEqual(self.doc["tolerates"], ["Drought"])
        self.assertEqual(self.doc["maintenance"], ["Low"])
        self.assertEqual(self.doc["moisture"], ["moist"])

    def test_text_collects_the_long_texts_and_skips_fillers(self):
        self.assertIn("English Oak is a large deciduous tree.", self.doc["text"])
        self.assertIn("The leaves have rounded lobes.", self.doc["text"])
        self.assertIn("Succeeds in heavy clay soils.", self.doc["text"])
        self.assertIn("Heartwood is a light to medium brown.", self.doc["text"])
        self.assertNotIn("None known", self.doc["text"])
        self.assertNotIn("KWER-kus ROH-bur", " ".join(self.doc["text"]))
        self.assertEqual(self.doc["uses"], ["Seed - cooked.", "Tannin.", "Food Forest", "Cabinetry"])
        self.assertEqual(self.doc["flower_color"], [])
        self.assertEqual(self.doc["wiki"], ["Quercus robur, the English oak, is a species of flowering plant."])

    def test_origin_from_the_sites_and_the_flora_categories(self):
        self.assertEqual(self.doc["origin"], ["Europe", "Europe, including Britain.", "Most of Europe",
                                              "Southeastern Europe"])
        self.assertEqual(len(self.doc["category"]), 3)


class DeduplicationTest(unittest.TestCase):
    def test_case_and_spaces_do_not_make_a_new_value(self):
        self.assertEqual(documents.unique(["English Oak", "english  oak", "ENGLISH OAK", " ", "Oak"]),
                         ["English Oak", "Oak"])

    def test_fillers_are_dropped(self):
        self.assertEqual(documents.unique(["None known", "No data available", "Not available.", "Unknown", "x"]),
                         ["x"])

    def test_statements_of_no_value_are_dropped(self):
        self.assertEqual(documents.unique(
            ["Not known", "Not known in the wild.", "No flowers", "No flowers.",
             "Not known in a truly wild situation[58].", "Not known 193", "Not known in the wild[11].", "No fruits",
             "None", "Not known but possibly northeast Africa or India.",
             "No fruits. This plants reproduces via spores."]),
            ["Not known but possibly northeast Africa or India.", "No fruits. This plants reproduces via spores."])


class NumbersTest(unittest.TestCase):
    def test_hardiest_zone_widest_range_tallest_height(self):
        doc = document([ncsu(), pfaf(), wooddb()], wikipedia())
        self.assertEqual((doc["zone_min"], doc["zone_max"]), (4, 8))
        self.assertEqual(doc["height_max_cm"], 3500)
        self.assertEqual((doc["density"], doc["janka"]), (675, 4980))
        self.assertEqual((doc["edibility"], doc["medicinal"]), (4, 3))
        self.assertEqual(doc["year"], 1753)

    def test_several_wood_pages_keep_the_largest_value(self):
        light = wooddb(url="https://www.wood-database.com/light-red-meranti/", density_kg_m3=480.4,
                       janka_hardness_n=6000)
        heavy = wooddb(url="https://www.wood-database.com/balau/", density_kg_m3=850.6, janka_hardness_n=4500)
        self.assertEqual((document([light, heavy])["density"], document([light, heavy])["janka"]), (851, 6000))

    def test_every_page_counts_for_the_extremes(self):
        doc = document([ncsu(zone_min=6, zone_max=9, height_max_cm=4000),
                        pfaf(edibility_rating=2, medicinal_rating=3),
                        pfaf(url="https://pfaf.org/user/Plant.aspx?LatinName=Quercus+pedunculata", zone_min=4,
                             zone_max=7, edibility_rating=4, medicinal_rating=1)])
        self.assertEqual((doc["zone_min"], doc["zone_max"], doc["height_max_cm"]), (4, 9, 4000))
        self.assertEqual((doc["edibility"], doc["medicinal"]), (4, 3))

    def test_a_single_tso_zone_is_only_the_coldest_zone(self):
        # Abies fansipanensis: TSO "8"; Melia azedarach: TSO "7-11"; Abelia chinensis: NCSU 7-9, TSO "7".
        self.assertEqual(document([tso(zone_min=8, zone_max=8)])["zone_min"], 8)
        self.assertIsNone(document([tso(zone_min=8, zone_max=8)])["zone_max"])
        doc = document([tso(zone_min=7, zone_max=11)])
        self.assertEqual((doc["zone_min"], doc["zone_max"]), (7, 11))
        doc = document([ncsu(zone_min=7, zone_max=9), tso(zone_min=7, zone_max=7)])
        self.assertEqual((doc["zone_min"], doc["zone_max"]), (7, 9))
        doc = document([pfaf(zone_min=6, zone_max=6)])
        self.assertEqual((doc["zone_min"], doc["zone_max"]), (6, 6))

    def test_missing_numbers_stay_none(self):
        doc = document([tso()])
        for field in ("year", "zone_min", "zone_max", "height_max_cm", "density", "janka", "edibility"):
            self.assertIsNone(doc[field], field)
        self.assertIsNone(documents.extreme([None, True, "5"], max))


class IucnTest(unittest.TestCase):
    def test_codes_and_category_texts(self):
        self.assertEqual(iucn_code("VU"), "vu")
        self.assertEqual(iucn_code("Status: Vulnerable A1cd"), "vu")
        self.assertEqual(iucn_code("Critically Endangered"), "cr")
        self.assertEqual(iucn_code("Extinct in the Wild"), "ew")
        self.assertEqual(iucn_code("Lower Risk/least concern"), "lc")
        self.assertEqual(iucn_code("Lower Risk/conservation dependent"), "nt")
        self.assertEqual(iucn_code("Conservation Dependent"), "nt")
        self.assertEqual(iucn_code("Stable. Least Concern."), "lc")

    def test_no_assessment_is_no_code(self):
        self.assertIsNone(iucn_code("This taxon has not yet been assessed."))
        self.assertIsNone(iucn_code("This taxon has not yet been assessed. Illinois (false tarragon) Endangered"))
        self.assertIsNone(iucn_code("NE"))
        self.assertIsNone(iucn_code("Not evaluated"))
        self.assertIsNone(iucn_code(None))

    def test_wikipedia_before_tso_before_wood_database_before_pfaf(self):
        records = [pfaf(iucn_category="Endangered"), tso(conservation_status="Vulnerable", conservation_code="VU"),
                   wooddb(iucn_status="Near Threatened")]
        self.assertEqual(document(records, wikipedia(iucn_status="CR"))["iucn"], ["cr"])
        self.assertEqual(document(records, wikipedia(iucn_status=None))["iucn"], ["vu"])
        self.assertEqual(document(records[:1] + records[2:])["iucn"], ["nt"])
        self.assertEqual(document(records[:1])["iucn"], ["en"])

    def test_not_evaluated_falls_through_to_the_next_source(self):
        records = [tso(conservation_status="Not evaluated", conservation_code="NE"), wooddb(iucn_status="Endangered")]
        self.assertEqual(document(records)["iucn"], ["en"])

    def test_tso_status_text_is_more_precise_than_its_code(self):
        record = tso(conservation_status="Lower risk/near threatened", conservation_code="LR")
        self.assertEqual(document([record])["iucn"], ["nt"])

    def test_a_cultivar_takes_common_names_but_not_name_status_authority_or_year_of_its_species(self):
        doc = document([ncsu(scientific_name="Quercus robur 'Fastigiata'")], wikipedia(level=1, iucn_status="EN"),
                       key="quercus robur fastigiata", names=("Quercus robur 'Fastigiata'",))
        self.assertEqual(doc["iucn"], [])
        self.assertIsNone(doc["year"])
        self.assertEqual(doc["authority"], [])
        self.assertEqual(doc["name"], ["Quercus robur 'Fastigiata'"])
        self.assertNotIn("Quercus robur", doc["synonym"])
        self.assertIn("European oak", doc["common_name"])
        self.assertIn("Quercus pyrenaica", doc["synonym"])
        self.assertIn("Southeastern Europe", doc["origin"])
        self.assertEqual(len(doc["category"]), 3)

    def test_the_status_of_another_names_article_does_not_override_the_sites(self):
        delavayi = wikipedia(title="Abies delavayi", binomial="Abies delavayi", authority="Franch.",
                             year_described=1999, iucn_status="LC",
                             match={"via": "redirect", "level": 0, "level_name": "own name"})
        record = tso(scientific_name="Abies fansipanensis", authority="Q.P. Xiang", genus="Abies",
                     conservation_status="Critically endangered", conservation_code="CR")
        doc = document([record], delavayi, key="abies fansipanensis", names=("Abies fansipanensis",))
        self.assertEqual(doc["iucn"], ["cr"])
        doc = document([tso(scientific_name="Abies fansipanensis")], delavayi, key="abies fansipanensis",
                       names=("Abies fansipanensis",))
        self.assertEqual(doc["iucn"], ["lc"])


class AuthorityTest(unittest.TestCase):
    def test_wikipedia_authority_first(self):
        self.assertEqual(document([tso(authority="Ehrh.")], wikipedia())["authority"], ["L. (1753)"])

    def test_record_authority_when_wikipedia_has_none(self):
        self.assertEqual(document([pfaf(authority="L."), tso(authority="Linn.")],
                                  wikipedia(authority=""))["authority"], ["Linn."])

    def test_various_is_no_authority(self):
        self.assertEqual(document([pfaf(authority="Various")])["authority"], [])

    def test_a_redirect_to_another_name_gives_its_status_but_not_its_name_authority_or_year(self):
        incana = wikipedia(title="Alnus incana", binomial="Alnus incana", authority="(L.) Moench",
                           year_described=1753, iucn_status="LC",
                           match={"via": "redirect", "level": 0, "level_name": "own name"})
        record = pfaf(scientific_name="Alnus rugosa", authority="(Du Roi.)Spreng.", genus="Alnus",
                      synonyms=["Alnus incana rugosa"])
        doc = document([record], incana, key="alnus rugosa", names=("Alnus rugosa",))
        self.assertEqual(doc["authority"], ["(Du Roi.)Spreng."])
        self.assertIsNone(doc["year"])
        self.assertEqual(doc["iucn"], ["lc"])
        self.assertEqual(doc["name"], ["Alnus rugosa"])
        self.assertEqual(doc["synonym"][:2], ["Alnus incana rugosa", "Alnus incana"])

    def test_the_places_of_another_names_article_only_fill_a_missing_origin(self):
        incana = wikipedia(title="Alnus incana", binomial="Alnus incana",
                           categories=["Alnus", "Trees of Europe", "Trees of Northern America", "Trees of Asia",
                                       "Flora of Alaska"],
                           match={"via": "redirect", "level": 0, "level_name": "own name"})
        record = pfaf(scientific_name="Alnus rugosa", genus="Alnus",
                      range="Northern and Eastern N. America - Hudson's Bay to Virginia. Naturalized in C. Europe[50].")
        doc = document([record], incana, key="alnus rugosa", names=("Alnus rugosa",))
        self.assertEqual(doc["origin"], ["Northern and Eastern N. America - Hudson's Bay to Virginia"])
        doc = document([pfaf(scientific_name="Alnus rugosa", genus="Alnus", range=None)], incana,
                       key="alnus rugosa", names=("Alnus rugosa",))
        self.assertEqual(doc["origin"], ["Europe", "Northern America", "Asia", "Alaska"])

    def test_a_species_article_gives_its_name_as_a_synonym_unless_our_name_starts_with_it(self):
        palmatum = wikipedia(level=1, title="Acer palmatum", binomial="Acer palmatum",
                             authority="Thunb. 1784 not Raf. 1836", synonyms=["Acer amoenum"])
        record = ncsu(scientific_name="Acer palmatum 'Atropurpureum'", synonyms=["Acer palmatum f. atropurpureum"])
        doc = document([record], palmatum, key="acer palmatum atropurpureum",
                       names=("Acer palmatum 'Atropurpureum'",))
        self.assertEqual(doc["name"], ["Acer palmatum 'Atropurpureum'"])
        self.assertEqual(doc["synonym"], ["Acer palmatum f. atropurpureum", "Acer amoenum"])
        harringtonii = wikipedia(level=1, title="Cephalotaxus harringtonii", binomial="Cephalotaxus harringtonii",
                                 synonyms=[], match={"via": "redirect", "level": 1, "level_name": "species"})
        doc = document([ncsu(scientific_name="Cephalotaxus harringtonia 'Duke Gardens'", synonyms=[])], harringtonii,
                       key="cephalotaxus harringtonia duke gardens",
                       names=("Cephalotaxus harringtonia 'Duke Gardens'",))
        self.assertEqual(doc["name"], ["Cephalotaxus harringtonia 'Duke Gardens'"])
        self.assertEqual(doc["synonym"], ["Cephalotaxus harringtonii"])
        self.assertTrue(documents.starts_with_name("Anemone x hybrida 'Honorine Jobert'", "Anemone × hybrida"))
        self.assertFalse(documents.starts_with_name("Acer palmatumx", "Acer palmatum"))

    def test_homonym_and_source_notes_are_cut_from_the_wikipedia_authority(self):
        note = documents.without_authority_note
        self.assertEqual(note("Thunb. 1784 not Raf. 1836"), "Thunb. 1784")
        self.assertEqual(note("L. 1753 not All. 1785 nor Krock. 1787 nor Lour. 1790"), "L. 1753")
        self.assertEqual(note("(L.) Benth. & Hook.f. (1873) Sources: NatureServe, IPNI, GRIN"),
                         "(L.) Benth. & Hook.f. (1873)")
        self.assertEqual(note("Lam. 1792 Source: IPNI UniProt"), "Lam. 1792")
        self.assertEqual(note("L. 1771, conserved name not Heister 1755"), "L. 1771")
        self.assertEqual(note("Cass. conserved spelling"), "Cass.")
        self.assertEqual(note("Jacq. non M.Bieb. non Bojer non Sessé & Moc."), "Jacq.")
        self.assertEqual(note("Roxb. ex Hornem. – not Roxb. 1832, nor Roxb. 1814 (the latter not validly published)"),
                         "Roxb. ex Hornem.")
        self.assertEqual(note("(Benth.) Alph. Wood 1868, not Dougl. ex Benth. 1835"), "(Benth.) Alph. Wood 1868")
        self.assertEqual(note("(L.) Moench"), "(L.) Moench")
        self.assertEqual(note(None), "")
        self.assertEqual(document([tso(authority="Ehrh.")], wikipedia(authority="L. 1753 not Mill. 1754"))["authority"],
                         ["L. 1753"])
        self.assertEqual(document([tso(authority="Ehrh.")], wikipedia(authority="not Mill. 1754"))["authority"],
                         ["Ehrh."])

    def test_a_title_match_with_the_box_of_another_name_is_not_our_article(self):
        spinulum = wikipedia(title="Lycopodium annotinum", binomial="Spinulum annotinum", authority="(L.) A.Haines",
                             year_described=1753, synonyms=["Lycopodium bryophyllum", "Lycopodium annotinum"],
                             match={"via": "title", "level": 0, "level_name": "own name"})
        doc = document([pfaf(scientific_name="Lycopodium annotinum", authority="L.", synonyms=[])], spinulum,
                       key="lycopodium annotinum", names=("Lycopodium annotinum",))
        self.assertEqual(doc["authority"], ["L."])
        self.assertIsNone(doc["year"])
        self.assertEqual(doc["name"], ["Lycopodium annotinum"])
        self.assertEqual(doc["synonym"], ["Spinulum annotinum", "Lycopodium bryophyllum"])

    def test_a_title_match_with_our_name_in_the_box_is_our_article(self):
        gerardii = wikipedia(title="Andropogon gerardi", binomial="Andropogon gerardii", authority="Vitman",
                             match={"via": "title", "level": 0, "level_name": "own name"})
        doc = document([pfaf(scientific_name="Andropogon gerardi", authority="Vitman.")], gerardii,
                       key="andropogon gerardi", names=("Andropogon gerardi",))
        self.assertEqual(doc["authority"], ["Vitman"])
        tulip = wikipedia(title="Tulip", binomial=None, rank="genus", authority="L.", year_described=None,
                          match={"via": "genus", "level": 0, "level_name": "own name"})
        doc = document([ncsu(scientific_name="Tulipa", genus="Tulipa")], tulip, key="tulipa", names=("Tulipa",))
        self.assertEqual(doc["authority"], ["L."])

    def test_a_redirect_from_a_spelling_variant_is_our_own_name(self):
        dioicus = wikipedia(title="Gymnocladus dioicus", binomial="Gymnocladus dioicus", authority="(L.) K.Koch",
                            year_described=1869, match={"via": "redirect", "level": 0, "level_name": "own name"})
        doc = document([pfaf(scientific_name="Gymnocladus dioica", authority="(L.)K.Koch.")], dioicus,
                       key="gymnocladus dioica", names=("Gymnocladus dioica",))
        self.assertEqual(doc["authority"], ["(L.) K.Koch"])
        self.assertEqual(doc["year"], 1869)

    def test_a_misspelt_name_is_our_name_but_a_similar_epithet_is_not(self):
        self.assertTrue(documents.spelling_variant("melia azederach", "melia azedarach"))
        self.assertTrue(documents.spelling_variant("hypochoeris radicata", "hypochaeris radicata"))
        self.assertTrue(documents.spelling_variant("quercus myrsinaefolia", "quercus myrsinifolia"))
        self.assertTrue(documents.spelling_variant("hyacinthoides nonscripta", "hyacinthoides non-scripta"))
        self.assertFalse(documents.spelling_variant("ephedra ciliata", "ephedra foliata"))
        self.assertFalse(documents.spelling_variant("zanthoxylum alatum", "zanthoxylum armatum"))
        self.assertFalse(documents.spelling_variant("ilex aquifolium", "ulex europaeus"))
        self.assertFalse(documents.spelling_variant("quercus", "quercus"))

    def test_a_genus_article_gives_only_its_lead(self):
        genus = wikipedia(level=2, title="Quercus", binomial=None, authority="L.", year_described=1753,
                          iucn_status="LC", common_names=["oak"], lead="Quercus is a genus of trees.")
        doc = document([tso(authority="Nutt.", scientific_name="Quercus michauxii")], genus,
                       key="quercus michauxii", names=("Quercus michauxii",))
        self.assertEqual(doc["authority"], ["Nutt."])
        self.assertIsNone(doc["year"])
        self.assertEqual(doc["iucn"], [])
        self.assertEqual(doc["common_name"], ["Common Oak"])
        self.assertEqual(doc["synonym"], ["Quercus pedunculata"])
        self.assertEqual(doc["category"], [])
        self.assertEqual(doc["wiki"], ["Quercus is a genus of trees."])
        self.assertEqual(doc["wiki_match"], ["genus, via box"])


class WikipediaTest(unittest.TestCase):
    def test_url_uses_underscores(self):
        self.assertEqual(documents.wikipedia_url("Quercus robur"), "https://en.wikipedia.org/wiki/Quercus_robur")
        self.assertEqual(documents.wikipedia_url("Abelia × grandiflora"),
                         "https://en.wikipedia.org/wiki/Abelia_×_grandiflora")
        self.assertEqual(documents.wikipedia_url("What? 100%"), "https://en.wikipedia.org/wiki/What%3F_100%25")

    def test_stored_page_fields(self):
        doc = document([ncsu()], wikipedia(title="Almond", binomial="Prunus amygdalus"))
        self.assertEqual(doc["wiki_title"], ["Almond"])
        self.assertEqual(doc["wiki_url"], ["https://en.wikipedia.org/wiki/Almond"])
        self.assertEqual(doc["wiki_match"], ["own name, via box"])
        self.assertEqual(doc["name"], ["Quercus robur", "Prunus amygdalus"])

    def test_entity_without_wikipedia(self):
        doc = document([tso(), pfaf()])
        for field in ("wiki", "category", "wiki_title", "wiki_url", "wiki_match"):
            self.assertEqual(doc[field], [], field)
        self.assertIsNone(doc["year"])
        self.assertEqual(doc["authority"], ["L."])
        self.assertEqual(doc["name"], ["Quercus robur"])
        self.assertEqual(doc["origin"], ["Europe, including Britain."])

    def test_place_categories(self):
        self.assertEqual(documents.category_places(
            ["Flora of China", "Trees of the United States", "Endangered flora of Europe", "Garden plants of Europe",
             "Plants described in 1753", "Flora without expected TNC conservation status",
             "Trees of Mediterranean climate", "Flora of Southern Africa"]),
            ["China", "United States", "Europe", "Southern Africa"])

    def test_a_category_of_naturalized_or_introduced_plants_is_no_origin(self):
        self.assertEqual(documents.category_places(
            ["Flora of tropical Asia", "Naturalized trees of Alabama", "Introduced flora of Europe",
             "Invasive flora of Hawaii", "Trees of China"]),
            ["tropical Asia", "China"])

    def test_maintenance_categories_are_left_out(self):
        doc = document([ncsu()], wikipedia(categories=[
            "Flora of Europe", "Flora without expected TNC conservation status", "Taxonomy articles created by Polbot",
            "Taxobox binomials not recognized by IUCN", "Articles containing video clips", "Ulmus articles with images",
            "Long stubs with short prose", "Wikipedia Student Program", "Pages with incorrect ref formatting",
            "Plants with edible fruit", "IUCN Red List vulnerable species", "Yamanashi Prefecture"]))
        self.assertEqual(doc["category"], ["Flora of Europe", "Plants with edible fruit",
                                           "IUCN Red List vulnerable species", "Yamanashi Prefecture"])

    def test_origin_stops_where_the_plant_is_only_grown(self):
        doc = document([pfaf(range="E. Asia - China. Naturalized in Europe[50]."),
                        ncsu(attributes={"Country Or Region Of Origin": ["Appalachians; cultivated in Europe"]})])
        self.assertEqual(doc["origin"], ["Appalachians", "E. Asia - China"])
        self.assertEqual(documents.native_part("Czechia (naturalised); France; Germany"), "France; Germany")
        self.assertEqual(documents.native_part("E. Asia - China, Japan, but widely cultivated in Asia."),
                         "E. Asia - China, Japan")
        self.assertEqual(documents.native_part("S. Europe, including Britain."), "S. Europe, including Britain.")
        self.assertEqual(documents.native_part("Cultivated"), "")

    def test_casual_established_and_escaped_plants_are_not_native(self):
        native = documents.native_part
        self.assertEqual(native("C. Europe to W. Asia. A casual in Britain[17]."), "C. Europe to W. Asia")
        self.assertEqual(native("Southern N. America - Mexico. Occasionally established in Europe."),
                         "Southern N. America - Mexico")
        self.assertEqual(native("E. Asia - China, Japan, Korea. A garden escape in Britain."),
                         "E. Asia - China, Japan, Korea")
        self.assertEqual(native("Europe - Balkans. to W. Asia. Occasionally persisting in Britain[17]."),
                         "Europe - Balkans. to W. Asia")
        self.assertEqual(native("S. Europe. W. Asia. N. Africa. a rare casual, occasionally persisting in "
                                "Britain[17]."), "S. Europe; W. Asia; N. Africa")
        # The native part before the remark stays.
        self.assertEqual(native("S. Europe? An occasional escape from cultivation in Britain."), "S. Europe?")
        self.assertEqual(native("A cosmopolitan plant, a locally established casual in Britain[17]."),
                         "A cosmopolitan plant")
        self.assertEqual(native("Europe. Possibly native to Britain but more common as a garden escape."),
                         "Europe; Possibly native to Britain")

    def test_a_remark_on_cultivation_drops_only_itself(self):
        native = documents.native_part
        self.assertEqual(native("Central America (Also grown on plantations)"), "Central America")
        self.assertEqual(native("Southeastern United States, though also widely grown on plantations"),
                         "Southeastern United States")
        self.assertEqual(native("Europe, Naturalized in Northern N. America."), "Europe")
        self.assertEqual(native("Portugal mainland; Spain mainland, Balearic Is., introduced to Canary Is; Syria"),
                         "Portugal mainland; Spain mainland, Balearic Is; Syria")
        self.assertEqual(native("China Anhui, Gansu, Hebei, Xinjiang, introduced elsewhere"),
                         "China Anhui, Gansu, Hebei, Xinjiang")
        self.assertEqual(native("PHILIPPINES; THAILAND; VANUATU; VIETNAM. Casuarina equisetifolia is widely introduced "
                                "and has become an invasive species in many countries"),
                         "PHILIPPINES; THAILAND; VANUATU; VIETNAM")
        # No word about cultivation: the clause stays.
        self.assertEqual(native("Primarily East Africa, though also occurring as far west as Sierra Leone"),
                         "Primarily East Africa, though also occurring as far west as Sierra Leone")


class VocabularyTest(unittest.TestCase):
    def test_ncsu_explanations_in_brackets_are_dropped(self):
        doc = document([ncsu()])
        self.assertEqual(doc["light"], ["Full sun"])
        self.assertEqual(doc["soil"], ["Clay", "Loam"])
        self.assertEqual(doc["ph"], ["Acid"])

    def test_pfaf_classes_get_the_ncsu_word(self):
        doc = document([pfaf(soil=["light (sandy)", "heavy (clay)"])])
        self.assertEqual(doc["light"], ["full sun", "semi-shade (light woodland)", "partial shade"])
        self.assertEqual(doc["soil"], ["light (sandy)", "sand", "heavy (clay)", "clay"])

    def test_no_shade_is_indexed_only_as_full_sun(self):
        # light:shade must not find a plant that cannot grow in shade.
        doc = document([pfaf(light=["semi-shade (light woodland)", "no shade"])])
        self.assertEqual(doc["light"], ["semi-shade (light woodland)", "partial shade", "full sun"])
        self.assertEqual(documents.pfaf_values("light", "no shade"), ["full sun"])
        self.assertEqual(documents.pfaf_values("light", "full shade (deep woodland)"),
                         ["full shade (deep woodland)", "deep shade"])

    def test_tso_leaf_from_the_opening_words(self):
        leaf = documents.tso_leaf
        self.assertEqual(leaf("A deciduous tree to 25 m; bark grey."), ["deciduous"])
        self.assertEqual(leaf("A densely-branched semi-evergreen shrub to 2 m tall, deciduous in colder climates."),
                         ["semi-evergreen", "deciduous"])
        self.assertEqual(leaf("Evergreen or semi-evergreen tree to 20 m tall, intermediate between its"),
                         ["evergreen", "semi-evergreen"])
        self.assertEqual(leaf("A straggling sub-evergreen shrub, with slender, four-angled stems"), ["semi-evergreen"])
        self.assertEqual(leaf("A deciduous or partially evergreen tree up to 30 ft high, usually smaller"),
                         ["deciduous", "semi-evergreen"])
        self.assertEqual(leaf("Deciduous trees to 15 m"), ["deciduous"])
        self.assertEqual(leaf("Tree 15–20 m × c. 1 m dbh. Crown pyramidal in young trees"), [])
        self.assertEqual(leaf("Leaves ovate. An evergreen shrub."), [])
        self.assertEqual(leaf("Editorial Note Bean treated this evergreen as a variety."), [])
        self.assertEqual(leaf(None), [])
        self.assertEqual(document([tso()])["leaf"], ["deciduous"])
        self.assertEqual(document([ncsu(), tso()])["leaf"], ["Deciduous"])

    def test_the_leaf_of_another_plant_is_no_leaf(self):
        self.assertEqual(documents.tso_leaf("In recent years, new introductions of evergreen species such as Cornus "
                                            "hongkongensis"), [])
        self.assertEqual(documents.tso_leaf("An epiphytic shrub growing on deciduous trees"), [])
        self.assertEqual(documents.tso_leaf("A shrub of evergreen habit"), ["evergreen"])

    def test_tso_plant_type_from_the_opening_words(self):
        self.assertEqual(documents.tso_plant_types("A deciduous tree to 25 m; bark grey."), ["tree"])
        self.assertEqual(documents.tso_plant_types("Shrub or small tree, 8–10 m."), ["shrub", "tree"])
        self.assertEqual(documents.tso_plant_types("A shrub 10 ft high, or in gardens a small tree"), ["shrub", "tree"])
        self.assertEqual(documents.tso_plant_types("Leaves ovate. A shrub."), [])
        self.assertEqual(documents.tso_plant_types("Editorial Note Bean treated this tree as a variety."), [])
        self.assertEqual(documents.tso_plant_types(None), [])

    def test_the_host_of_a_climber_or_parasite_is_no_plant_type(self):
        self.assertEqual(documents.tso_plant_types("A tall climber, reaching to the tops of lofty trees"), ["climber"])
        self.assertEqual(documents.tso_plant_types("An evergreen shrub, parasitic on various trees"), ["shrub"])
        self.assertEqual(documents.tso_plant_types("A vigorous climber festooning small trees and shrubs"), ["climber"])
        self.assertEqual(documents.tso_plant_types("An evergreen climber clinging to trees, etc."), ["climber"])
        self.assertEqual(documents.tso_plant_types("Among the most valuable of small shrubs"), ["shrub"])
        self.assertEqual(documents.tso_plant_types("Rootstocks chosen for their influence on tree growth"), ["tree"])

    def test_hardwood_and_softwood_are_trees(self):
        self.assertEqual(document([wooddb()])["plant_type"], ["Hardwood", "tree"])
        self.assertEqual(document([wooddb(wood_type="Monocot")])["plant_type"], ["Monocot"])


class ReadDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="vinf-test-")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, folder, rows):
        os.makedirs(os.path.join(self.folder, folder))
        with open(os.path.join(self.folder, folder, "part-00000"), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_entities_meet_their_records_through_the_url(self):
        first, _ = entity([ncsu(), tso()], wikipedia())
        second, _ = entity([pfaf(url="https://pfaf.org/x", scientific_name="Acer rubrum")], key="acer rubrum",
                           names=("Acer rubrum",))
        second["entity_id"] = 8
        second["sources"]["tso"] = ["https://www.treesandshrubsonline.org/missing/"]
        self.write("entities", [first, second])
        self.write("records/ncsu", [ncsu()])
        self.write("records/tso", [tso()])
        self.write("records/pfaf", [pfaf(url="https://pfaf.org/x", scientific_name="Acer rubrum")])
        docs = list(documents.read_documents(os.path.join(self.folder, "entities"),
                                             os.path.join(self.folder, "records")))
        self.assertEqual([doc["id"] for doc in docs], [["7"], ["8"]])
        self.assertEqual(docs[0]["common_name"], ["English Oak", "Pedunculate Oak", "Common Oak", "European oak"])
        self.assertEqual(docs[1]["name"], ["Acer rubrum"])
        # A page without a record still counts as a source page.
        self.assertEqual(docs[1]["source"], ["pfaf", "tso"])


if __name__ == "__main__":
    unittest.main()
