import html
import os
import re
import unittest

from wikipedia import wikitext

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "wikipedia")

# 11 pages copied byte for byte from enwiki-20261001-pages-articles. Expected values
# were checked against the wikitext in the fixture files.
BOX_FIELDS = {"page_id", "title", "redirect", "box", "genus", "species", "taxon", "binomial", "rank", "authority",
              "year_described", "iucn_status", "synonyms", "synonym_authors", "categories", "common_names", "lead",
              "plant_hint"}


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def record(name):
    """The page as the splitter hands it over: "</page>" is the record delimiter."""
    return load(name).rsplit("</page>", 1)[0]


def page(name):
    return wikitext.parse_page(record(name))


def page_record(wikitext_source, title="Test page", ns=0, page_id=1):
    """A dump record around hand-written wikitext, escaped the way the dump escapes it."""
    escaped = html.escape(wikitext_source, quote=False).replace('"', "&quot;")
    return ("\n  <page>\n    <title>{}</title>\n    <ns>{}</ns>\n    <id>{}</id>\n    <revision>\n      <id>7</id>\n"
            "      <text bytes=\"1\" xml:space=\"preserve\">{}</text>\n    </revision>\n  ").format(
                title, ns, page_id, escaped)


class AllFixturesTest(unittest.TestCase):
    """Record contract on every fixture page."""

    @classmethod
    def setUpClass(cls):
        cls.pages = {name: page(name) for name in sorted(os.listdir(FIXTURES)) if name.endswith(".xml")}

    def test_eleven_fixture_pages(self):
        self.assertEqual(len(self.pages), 11)

    def test_box_pages_have_every_field(self):
        boxes = {name for name, result in self.pages.items() if result.get("box") is not None}
        self.assertEqual(len(boxes), 9)
        for name in boxes:
            with self.subTest(page=name):
                self.assertEqual(set(self.pages[name]), BOX_FIELDS)
                self.assertIsInstance(self.pages[name]["synonyms"], list)
                self.assertIsInstance(self.pages[name]["synonym_authors"], dict)
                self.assertLessEqual(set(self.pages[name]["synonym_authors"]), set(self.pages[name]["synonyms"]))
                self.assertIsInstance(self.pages[name]["plant_hint"], bool)

    def test_text_fields_are_clean(self):
        for name, result in self.pages.items():
            if result.get("box") is None:
                continue
            texts = ([result["lead"], result["authority"] or ""] + result["common_names"] + result["synonyms"]
                     + list(result["synonym_authors"].values()))
            for text in texts:
                with self.subTest(page=name, text=text[:40]):
                    for markup in ("<", "{{", "}}", "[[", "]]", "''", "&nbsp;", "&amp;", "\xa0", "  "):
                        self.assertNotIn(markup, text)

    def test_full_element_with_closing_tag_parses_the_same(self):
        self.assertEqual(wikitext.parse_page(load("kalmia_latifolia.xml")), self.pages["kalmia_latifolia.xml"])


class SplitterRecordsTest(unittest.TestCase):
    """Records the splitter produces besides ordinary pages."""

    def test_first_record_carries_the_siteinfo_header(self):
        header = ('<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11" xml:lang="en">\n'
                  "  <siteinfo>\n    <sitename>Wikipedia</sitename>\n    <namespaces>\n"
                  '      <namespace key="0" case="first-letter" />\n    </namespaces>\n  </siteinfo>\n  ')
        result = wikitext.parse_page(header + record("quatorzain.xml"))
        self.assertEqual(result, {"page_id": 51671, "title": "Quatorzain", "redirect": None, "box": None})

    def test_dump_tail_is_none(self):
        self.assertIsNone(wikitext.parse_page("\n</mediawiki>\n"))
        self.assertIsNone(wikitext.parse_page(""))

    def test_other_namespaces_are_none(self):
        self.assertIsNone(wikitext.parse_page(record("almond.xml").replace("<ns>0</ns>", "<ns>4</ns>")))
        self.assertIsNone(wikitext.parse_page(page_record("{{Speciesbox|genus=A|species=b}}", ns=14)))

    def test_empty_text_element(self):
        source = record("quatorzain.xml")
        empty = re.sub(r"<text [^>]*>[^<]*</text>", '<text bytes="0" />', source)
        self.assertEqual(wikitext.parse_page(empty)["box"], None)


class RedirectTest(unittest.TestCase):

    def test_redirect_has_only_the_target(self):
        self.assertEqual(page("olive_tree.xml"), {"page_id": 44976, "title": "Olive tree", "redirect": "Olive"})

    def test_escaped_redirect_title(self):
        source = page_record("#REDIRECT [[A&B]]", title="A and B").replace(
            "<revision>", '<redirect title="A &amp; B &quot;x&quot;" />\n    <revision>')
        self.assertEqual(wikitext.parse_page(source)["redirect"], 'A & B "x"')


class NoBoxTest(unittest.TestCase):

    def test_article_without_box(self):
        self.assertEqual(page("quatorzain.xml"), {"page_id": 51671, "title": "Quatorzain", "redirect": None, "box": None})

    def test_similar_template_is_no_box(self):
        source = page_record("{{Taxobox colour|Plantae}} and {{Speciesbox/doc}}")
        self.assertIsNone(wikitext.parse_page(source)["box"])

    def test_commented_out_box_is_no_box(self):
        source = page_record("<!-- {{Speciesbox | genus = Prunus | species = dulcis}} -->\nText.")
        self.assertEqual(wikitext.parse_page(source), {"page_id": 1, "title": "Test page", "redirect": None,
                                                        "box": None})


class AlmondTest(unittest.TestCase):
    """Speciesbox under a common-name title; synonyms in {{species list}} inside {{collapsible list}}."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("almond.xml")

    def test_names(self):
        self.assertEqual((self.page["page_id"], self.page["title"], self.page["box"]), (1064, "Almond", "speciesbox"))
        self.assertEqual((self.page["genus"], self.page["species"], self.page["taxon"]), ("Prunus", "amygdalus", None))
        self.assertEqual(self.page["binomial"], "Prunus amygdalus")
        self.assertEqual(self.page["rank"], "species")

    def test_authority_and_year(self):
        # "[[August Batsch|Batsch]], 1801"
        self.assertEqual(self.page["authority"], "Batsch, 1801")
        self.assertEqual(self.page["year_described"], 1801)
        self.assertIsNone(self.page["iucn_status"])

    def test_synonyms_from_species_lists(self):
        # Names stand at odd positions. "Amygdalus amygdalus" and "Prunus communis" carry "[[nom. illeg.]]"
        # in their author cell: illegitimate names are often later homonyms, so they are left out.
        self.assertEqual(self.page["synonyms"], [
            "Amygdalus communis", "Druparia amygdalus", "Amygdalus amara",
            "Amygdalus amygdalina", "Amygdalus cochinchinensis", "Amygdalus communis var. fragilis",
            "Amygdalus communis var. macrocarpa", "Amygdalus decipiens", "Amygdalus dulcis", "Amygdalus elata",
            "Amygdalus korshinskyi var. bornmuelleri", "Amygdalus sativa", "Amygdalus sinensis",
            "Amygdalus stocksiana", "Persica", "Prunus cochinchinensis", "Prunus dulcis", "Prunus dulcis var. amara",
            "Prunus dulcis var. fragilis", "Prunus dulcis var. spontanea", "Prunus intermedia", "Prunus stocksiana",
            "Trichocarpus"])

    def test_synonym_authors_from_the_author_cells(self):
        # "[[L.]], 1753", "(Mill.) [[D.A.Webb]], 1967 [[nom. superfl.]]", "Oken ex M.Roem., 1847"
        authors = self.page["synonym_authors"]
        self.assertEqual(authors["Amygdalus communis"], "L.")
        self.assertEqual(authors["Prunus dulcis"], "(Mill.) D.A.Webb")
        self.assertEqual(authors["Amygdalus amygdalina"], "Oken ex M.Roem.")
        self.assertEqual(authors["Amygdalus decipiens"], "Poit. & Turpin")
        self.assertEqual(authors["Persica"], "Mill.")
        self.assertEqual(set(authors), set(self.page["synonyms"]))

    def test_categories_without_sort_keys(self):
        self.assertEqual(self.page["categories"], [
            "Almonds", "Prunus", "Crops originating from Asia", "Edible nuts and seeds", "Flora of temperate Asia",
            "Pollination management", "Snacks", "Nut oils", "Crops", "Fruit trees", "Symbols of California",
            "Taxa named by August Batsch", "Drought-tolerant trees"])

    def test_common_name_skips_bold_italic_scientific_names(self):
        # "The '''almond''' ('''''Prunus amygdalus''''', syn. '''''Prunus dulcis''''' ..."
        self.assertEqual(self.page["common_names"], ["almond"])

    def test_lead(self):
        lead = self.page["lead"]
        self.assertTrue(lead.startswith(
            "The almond (Prunus amygdalus, syn. Prunus dulcis (Mill.) D.A.Webb, nom. illeg. non Prunus dulcis "
            "Rouchy) is a species of tree from the genus Prunus. Along with the peach,"))
        self.assertTrue(lead.endswith("leading to lower supply and increased prices."))
        self.assertIn("California produces about 80% of the world's almond supply.", lead)
        self.assertNotIn("Description", lead)
        self.assertNotIn("Alice", lead)

    def test_plant_hint(self):
        self.assertTrue(self.page["plant_hint"])


class KalmiaLatifoliaTest(unittest.TestCase):
    """IUCN status next to a second status system; no synonyms."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("kalmia_latifolia.xml")

    def test_names(self):
        self.assertEqual((self.page["genus"], self.page["species"], self.page["binomial"], self.page["rank"]),
                         ("Kalmia", "latifolia", "Kalmia latifolia", "species"))

    def test_iucn_status_ignores_the_natureserve_status(self):
        # status = LC, status_system = IUCN3.1; status2 = G5, status2_system = TNC
        self.assertEqual(self.page["iucn_status"], "LC")

    def test_authority_without_year_takes_the_category_year(self):
        self.assertEqual(self.page["authority"], "L.")
        self.assertEqual(self.page["year_described"], 1753)

    def test_box_without_synonyms(self):
        self.assertEqual(self.page["synonyms"], [])

    def test_common_names(self):
        self.assertEqual(self.page["common_names"], ["mountain laurel", "calico-bush", "spoonwood"])

    def test_lead(self):
        self.assertEqual(self.page["lead"], (
            "Kalmia latifolia, the mountain laurel, calico-bush, or spoonwood, is a flowering plant and one of the 10 "
            "species in the genus of Kalmia belonging to the heath(er) family Ericaceae. It is native to the eastern "
            "United States. Its range stretches from southern Maine to northern Florida, and west to Indiana and "
            "Louisiana. Mountain laurel is the state flower of Connecticut and Pennsylvania. It is the namesake of "
            "Laurel County in Kentucky, the city of Laurel, Mississippi, Mount Laurel, New Jersey, and the Laurel "
            "Highlands in southwestern Pennsylvania."))

    def test_categories_and_hint(self):
        self.assertEqual(len(self.page["categories"]), 10)
        self.assertEqual(self.page["categories"][0], "Kalmia")
        self.assertTrue(self.page["plant_hint"])


class AgapanthusAfricanusTest(unittest.TestCase):
    """{{Plainlist}} synonyms with <small> authors; two "Plants described in" categories."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("agapanthus_africanus.xml")

    def test_authority_links_reduced_to_labels(self):
        # "([[Carl Linnaeus|L.]]) [[Hoffmanns.]]"
        self.assertEqual(self.page["authority"], "(L.) Hoffmanns.")

    def test_earliest_described_year(self):
        # "Plants described in 1824" comes before "Plants described in 1753".
        self.assertEqual(self.page["year_described"], 1753)

    def test_synonyms_without_authors_and_flagged_names(self):
        # "*''Agapanthus tuberosus'' <small>L. ex DC.</small> nom. inval." and "*''Crinum floridum''
        # <small>Salisb.</small> nom. illeg." are flagged by their own entry and left out.
        self.assertEqual(self.page["synonyms"], [
            "Abumon africanum", "Agapanthus minor", "Agapanthus umbellatus", "Crinum africanum",
            "Mauhlia africana", "Mauhlia linearis", "Mauhlia umbellata", "Tulbaghia africana",
            "Tulbaghia heisteri", "Tulbaghia minor"])

    def test_synonym_authors_from_small_tags(self):
        authors = self.page["synonym_authors"]
        self.assertEqual(authors["Abumon africanum"], "(L.) Britton")
        self.assertEqual(authors["Agapanthus umbellatus"], "L'Hér.")
        self.assertEqual(authors["Mauhlia umbellata"], "(L'Hér.) Thunb. ex Schult. & Schult.f.")
        self.assertNotIn("Agapanthus tuberosus", authors)

    def test_common_names_of_the_first_paragraph(self):
        self.assertEqual(self.page["common_names"], ["African lily", "lily of the Nile"])

    def test_lead_without_files_and_refs(self):
        self.assertEqual(self.page["lead"], (
            "Agapanthus africanus, commonly named the African lily, is a flowering plant from the genus Agapanthus "
            "found only on rocky sandstone slopes of the winter rainfall fynbos from the Cape Peninsula to "
            "Swellendam. It is also called the lily of the Nile in spite of only growing in South Africa."))

    def test_categories(self):
        self.assertEqual(self.page["categories"], [
            "Agapanthus", "Endemic flora of the Cape Provinces", "Plants described in 1824", "Plants described in 1753",
            "Botanical taxa named by Carl Linnaeus"])
        self.assertTrue(self.page["plant_hint"])


class AlderTest(unittest.TestCase):
    """Automatic taxobox of a genus; genus synonyms with {{small}} authors."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("alder.xml")

    def test_genus_page(self):
        self.assertEqual(self.page["box"], "automatic taxobox")
        self.assertEqual((self.page["taxon"], self.page["genus"], self.page["species"]), ("Alnus", "Alnus", None))
        self.assertIsNone(self.page["binomial"])
        self.assertEqual(self.page["rank"], "genus")

    def test_authority_without_year(self):
        self.assertEqual(self.page["authority"], "Mill.")
        self.assertIsNone(self.page["year_described"])
        self.assertIsNone(self.page["iucn_status"])

    def test_genus_synonyms(self):
        self.assertEqual(self.page["synonyms"], ["Betula-alnus", "Duschekia", "Alnaster", "Clethropsis", "Semidopsis",
                                                 "Alnobetula", "Cremastogyne"])

    def test_genus_synonym_authors_from_small_templates(self):
        # "|''Alnobetula'' {{small|(W.D.J.Koch) Schur.}}"
        self.assertEqual(self.page["synonym_authors"]["Betula-alnus"], "Marshall")
        self.assertEqual(self.page["synonym_authors"]["Alnobetula"], "(W.D.J.Koch) Schur.")

    def test_common_names(self):
        # "'''Alders''' are [[tree]]s of the genus '''''Alnus'''''"
        self.assertEqual(self.page["common_names"], ["Alders"])

    def test_lead(self):
        self.assertEqual(self.page["lead"], (
            "Alders are trees of the genus Alnus in the birch family Betulaceae. The genus includes about 35 species "
            "of monoecious trees and shrubs, a few reaching a large size, distributed throughout the north temperate "
            "zone with a few species extending into Central America, as well as the northern and southern Andes."))

    def test_plant_hint_from_short_description(self):
        # No plant category; "{{Short description|Genus of flowering plants in the birch family}}".
        self.assertEqual(self.page["categories"], ["Alnus", "Taxa named by Philip Miller",
                                                   "Extant Thanetian first appearances"])
        self.assertTrue(self.page["plant_hint"])


class NorthernCavefishTest(unittest.TestCase):
    """An animal: IUCN status, year in the authority, "Taxa named by" category."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("northern_cavefish.xml")

    def test_names(self):
        self.assertEqual((self.page["box"], self.page["binomial"], self.page["rank"]),
                         ("speciesbox", "Amblyopsis spelaea", "species"))

    def test_status_and_year(self):
        self.assertEqual(self.page["iucn_status"], "NT")
        self.assertEqual(self.page["authority"], "DeKay, 1842")
        self.assertEqual(self.page["year_described"], 1842)

    def test_common_names(self):
        self.assertEqual(self.page["common_names"], ["northern cavefish", "northern blindfish"])

    def test_not_a_plant(self):
        self.assertIn("Taxa named by James Ellsworth De Kay", self.page["categories"])
        self.assertFalse(self.page["plant_hint"])


class PseudotsugaMenziesiiGlaucaTest(unittest.TestCase):
    """Infraspeciesbox with `varietas`; bullet synonyms with "var."."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("pseudotsuga_menziesii_var_glauca.xml")

    def test_trinomial(self):
        self.assertEqual(self.page["box"], "infraspeciesbox")
        self.assertEqual((self.page["genus"], self.page["species"]), ("Pseudotsuga", "menziesii"))
        self.assertEqual(self.page["binomial"], "Pseudotsuga menziesii var. glauca")
        self.assertEqual(self.page["rank"], "infraspecies")

    def test_authority(self):
        self.assertEqual(self.page["authority"], "(Mayr) Franco")
        self.assertIsNone(self.page["year_described"])

    def test_synonyms_keep_varieties(self):
        # "* ''Pseudotsuga taxifolia'' var. ''caesia'' (Schwer.) Asch. &amp; Graebn."
        self.assertEqual(self.page["synonyms"], ["Pseudotsuga menziesii var. caesia",
                                                 "Pseudotsuga taxifolia var. caesia",
                                                 "Pseudotsuga taxifolia var. glauca"])

    def test_common_name_and_lead(self):
        self.assertEqual(self.page["common_names"], ["Rocky Mountain Douglas-fir"])
        self.assertTrue(self.page["lead"].startswith(
            "Pseudotsuga menziesii var. glauca, or Rocky Mountain Douglas-fir, is an evergreen conifer native"))
        # "600&amp;nbsp;m" in the dump
        self.assertIn("It occurs from 600 m altitude in the north of the range, up to 3,000 m,", self.page["lead"])
        self.assertIn('confined to "sky islands" on the higher mountains', self.page["lead"])


class CalamansiTest(unittest.TestCase):
    """Hybrid species: "species = × microcarpa"; <br> between name and author."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("calamansi.xml")

    def test_hybrid_names(self):
        self.assertEqual(self.page["binomial"], "Citrus × microcarpa")
        self.assertEqual((self.page["genus"], self.page["species"]), ("Citrus", "microcarpa"))
        self.assertEqual(self.page["rank"], "species")

    def test_hybrid_synonyms(self):
        self.assertEqual(self.page["synonyms"], ["× Citrofortunella microcarpa", "Citrus × mitis",
                                                 "× Citrofortunella mitis"])

    def test_authors_on_the_line_after_the_name(self):
        # "* ''Citrus × mitis''<br /><small>Blanco</small>"
        self.assertEqual(self.page["synonym_authors"], {
            "× Citrofortunella microcarpa": "(Bunge) Wijnands", "Citrus × mitis": "Blanco",
            "× Citrofortunella mitis": "(Blanco) J.W.Ingram & H.E.Moore"})

    def test_common_names(self):
        # "'''Calamansi''' ('''''Citrus'' × ''microcarpa'''''), also known as '''calamondin''', ..."
        self.assertEqual(self.page["common_names"], ["Calamansi", "calamondin", "Philippine lime", "Philippine lemon"])

    def test_no_year(self):
        self.assertEqual(self.page["authority"], "Bunge")
        self.assertIsNone(self.page["year_described"])


class PhegopterisTest(unittest.TestCase):
    """Fern genus: {{Genus list}} synonyms, year from "Taxa described in"."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("phegopteris.xml")

    def test_genus(self):
        self.assertEqual((self.page["taxon"], self.page["genus"], self.page["rank"]),
                         ("Phegopteris", "Phegopteris", "genus"))

    def test_authority_and_year(self):
        self.assertEqual(self.page["authority"], "(C.Presl) Fée")
        self.assertEqual(self.page["year_described"], 1852)

    def test_genus_list(self):
        self.assertEqual(self.page["synonyms"], ["Lastrella", "Thelypteris subg. Phegopteris"])

    def test_common_names_and_hint(self):
        self.assertEqual(self.page["common_names"], ["beech ferns"])
        self.assertTrue(self.page["plant_hint"])


class GinkgoaceaeTest(unittest.TestCase):
    """A family: rank above genus, plant hint only from the short description."""

    @classmethod
    def setUpClass(cls):
        cls.page = page("ginkgoaceae.xml")

    def test_family(self):
        self.assertEqual((self.page["taxon"], self.page["rank"]), ("Ginkgoaceae", "higher"))
        self.assertIsNone(self.page["genus"])
        self.assertIsNone(self.page["binomial"])

    def test_authority_with_refs(self):
        self.assertEqual(self.page["authority"], "Engl.")

    def test_no_synonyms_and_no_common_name(self):
        # "The '''Ginkgoaceae''' are a family ..." names the taxon, not a common name.
        self.assertEqual(self.page["synonyms"], [])
        self.assertEqual(self.page["common_names"], [])

    def test_plant_hint(self):
        self.assertTrue(self.page["plant_hint"])
        self.assertTrue(self.page["lead"].startswith("The Ginkgoaceae are a family of gymnosperms which appeared"))


class OldTaxoboxTest(unittest.TestCase):
    """The old {{Taxobox}} (no page of the sample uses it) keeps the name in `binomial`."""

    @classmethod
    def setUpClass(cls):
        source = (
            "{{Short description|Species of tree}}\n"
            "{{Taxobox\n| name = Sweet chestnut\n| regnum = [[Plant]]ae\n| familia = [[Fagaceae]]\n"
            "| genus = ''[[Castanea]]''\n| species = '''''C. sativa'''''\n| binomial = ''Castanea sativa''\n"
            "| binomial_authority = [[Philip Miller|Mill.]]<ref>IPNI</ref>\n| status = LR/lc\n"
            "| status_system = IUCN2.3\n"
            "| synonyms = ''Castanea vesca'' <small>Gaertn.</small><br />''Fagus castanea'' <small>L.</small>\n}}\n"
            "The '''sweet chestnut''' ('''''Castanea sativa'''''), or '''Spanish chestnut''', is a tree.\n\n"
            "== Description ==\nText.\n[[Category:Trees of Europe]]\n")
        cls.page = wikitext.parse_page(page_record(source, title="Castanea sativa", page_id=42))

    def test_names(self):
        self.assertEqual(self.page["box"], "taxobox")
        self.assertEqual((self.page["genus"], self.page["species"]), ("Castanea", "sativa"))
        self.assertEqual((self.page["binomial"], self.page["rank"]), ("Castanea sativa", "species"))
        self.assertEqual(self.page["authority"], "Mill.")

    def test_old_iucn_class(self):
        self.assertEqual(self.page["iucn_status"], "LC")

    def test_synonyms_and_common_names(self):
        self.assertEqual(self.page["synonyms"], ["Castanea vesca", "Fagus castanea"])
        self.assertEqual(self.page["common_names"], ["sweet chestnut", "Spanish chestnut"])
        self.assertEqual(self.page["lead"], "The sweet chestnut (Castanea sativa), or Spanish chestnut, is a tree.")

    def test_kingdom_in_box_marks_a_plant(self):
        self.assertTrue(wikitext.PLANTAE_RE.search("| regnum = [[Plant]]ae"))
        self.assertTrue(self.page["plant_hint"])


class TemplateTest(unittest.TestCase):
    """Balanced {{ }} scanning and parameter splitting."""

    def test_template_end_with_nested_templates(self):
        text = "x {{Speciesbox | a = {{small|{{!}}}} | b = 2}} tail"
        start = text.index("{{")
        self.assertEqual(text[start:wikitext.template_end(text, start)], "{{Speciesbox | a = {{small|{{!}}}} | b = 2}}")

    def test_template_end_of_unclosed_template(self):
        self.assertEqual(wikitext.template_end("{{Speciesbox | a = {{b}}", 0), 24)

    def test_find_template(self):
        text = "{{Short description|x}}\n{{automatic_taxobox\n| taxon = Alnus\n| synonyms = {{collapsible list|a}}\n}}\nAfter"
        start, end = wikitext.find_template(text, wikitext.BOX_RE)
        self.assertTrue(text[start:end].startswith("{{automatic_taxobox"))
        self.assertEqual(text[end:], "\nAfter")
        self.assertIsNone(wikitext.find_template("no box here", wikitext.BOX_RE))

    def test_box_names_ignore_case_spaces_and_underscores(self):
        for opening in ("{{Speciesbox|", "{{speciesbox\n|", "{{Species box |", "{{Automatic_taxobox|",
                        "{{automatic  taxobox }}", "{{Taxobox <!-- old -->", "{{Infraspeciesbox|",
                        "{{Sub_species_box|", "{{Hybridbox|"):
            with self.subTest(opening=opening):
                self.assertTrue(wikitext.BOX_RE.search(opening))
        for opening in ("{{Taxobox colour|Plantae}}", "{{Speciesbox/doc}}", "{{Taxobox_norank_entry|x}}"):
            with self.subTest(opening=opening):
                self.assertIsNone(wikitext.BOX_RE.search(opening))

    def test_top_level_templates(self):
        text = "a {{x|{{y}}}} b {{z}}"
        self.assertEqual([text[start:end] for start, end in wikitext.top_level_templates(text)],
                         ["{{x|{{y}}}}", "{{z}}"])

    def test_template_params(self):
        params = wikitext.template_params(
            "{{Speciesbox\n| Genus = Prunus <!-- a | b -->\n| authority = [[Carl Linnaeus|L.]] {{small|x|y}}\n"
            "| first\n| second = [[a|b]]|third}}")
        self.assertEqual(params, {"genus": "Prunus", "authority": "[[Carl Linnaeus|L.]] {{small|x|y}}",
                                  "1": "first", "second": "[[a|b]]", "2": "third"})

    def test_template_name_and_key(self):
        self.assertEqual(wikitext.template_name("{{ Species list |A|B}}"), "Species list")
        self.assertEqual(wikitext.template_name("{{ndash}}"), "ndash")
        self.assertEqual(wikitext.name_key("Automatic_taxobox"), "automatictaxobox")


class PlainTextTest(unittest.TestCase):
    """Markup removal edge cases."""

    def test_links_with_and_without_pipe(self):
        self.assertEqual(wikitext.plain_text("[[Carl Linnaeus|L.]] and [[Prunus]], [[bee]]s"), "L. and Prunus, bees")
        self.assertEqual(wikitext.plain_text("[[:Category:Trees|trees]] [[Synonym (taxonomy)#Botany|syn.]]"),
                         "trees syn.")

    def test_refs_with_and_without_body(self):
        text = ('A<ref name="eb"/> B<ref name=x>{{cite web|title=T}}</ref> C<ref name="a/b">note</ref>'
                "<ref>two\nlines</ref> D")
        self.assertEqual(wikitext.plain_text(text), "A B C D")

    def test_entities_typed_by_editors(self):
        # The dump stores "600&amp;nbsp;m"; the page text after one unescape is "600&nbsp;m".
        self.assertEqual(wikitext.plain_text("600&nbsp;m, Alice&#039;s, 3&ndash;4"), "600 m, Alice's, 3–4")

    def test_nested_templates_dropped(self):
        # {{convert}} used to be the outer template here; it now keeps its number (see test_convert_keeps_numbers).
        self.assertEqual(wikitext.plain_text("A {{cite|3|m|{{abbr|x}}}}{{efn|note {{r|b}}}} B"), "A B")

    def test_inline_templates_keep_their_words(self):
        self.assertEqual(wikitext.plain_text("from {{lang|la|amygdalus}} {{ndash}} {{small|L.}}"),
                         "from amygdalus – L.")

    def test_files_with_links_in_the_caption(self):
        text = "[[File:K.jpg|thumb|The [[Type (biology)|type]] of ''Kalmia'']]Kalmia [[Image:x.png]]is"
        self.assertEqual(wikitext.plain_text(text), "Kalmia is")

    def test_comments_tags_quotes_and_external_links(self):
        text = "'''Bold''' <!-- hidden --> ''it''<br/>x <small>small</small> [https://e.org label] [https://e.org]"
        self.assertEqual(wikitext.plain_text(text), "Bold it x small label")

    def test_brackets_left_by_dropped_templates(self):
        self.assertEqual(wikitext.plain_text("'''Asterales''' ({{IPAc-en|x}}) is an order"), "Asterales is an order")

    def test_clean_name(self):
        self.assertEqual(wikitext.clean_name("''[[Prunus]]'' <!-- x -->"), "Prunus")
        self.assertEqual(wikitext.clean_name("Dryas (plant)"), "Dryas")
        self.assertEqual(wikitext.clean_name("Tracheophytes/Plantae"), "Tracheophytes")
        self.assertIsNone(wikitext.clean_name(""))


class FieldHelpersTest(unittest.TestCase):

    def test_categories(self):
        text = "[[Category:Prunus|Almond]]\n[[category: Trees_of Europe ]]\n[[Category:Prunus]][[File:x.jpg]]"
        self.assertEqual(wikitext.categories(text), ["Prunus", "Trees of Europe"])

    def test_year_described(self):
        self.assertEqual(wikitext.year_described("(Linnaeus, 1758)", []), 1758)
        self.assertEqual(wikitext.year_described("L. 1753 not Scop. 1777 nor Thell. 1911", []), 1753)
        self.assertEqual(wikitext.year_described("L. not Hook.f. 1881", ["Plants described in 1753"]), 1753)
        self.assertEqual(wikitext.year_described("Mill.", ["Taxa described in 1768", "Fish described in 1754"]), 1754)
        self.assertIsNone(wikitext.year_described(None, ["Plants"]))

    def test_iucn_status(self):
        self.assertEqual(wikitext.iucn_status({"status": "lc", "status_system": "IUCN3.1"}), "LC")
        self.assertEqual(wikitext.iucn_status({"status": "LR/nt", "status_system": "iucn2.3"}), "NT")
        self.assertEqual(wikitext.iucn_status({"status": "EN<ref>x</ref>", "status_system": "IUCN 3.1"}), "EN")
        self.assertIsNone(wikitext.iucn_status({"status": "G5", "status_system": "TNC"}))
        self.assertIsNone(wikitext.iucn_status({"status": "NE", "status_system": "IUCN3.1"}))
        self.assertIsNone(wikitext.iucn_status({"status": "LC"}))

    def test_bold_terms(self):
        paragraph = "'''Calamansi''' ('''''Citrus'' × ''microcarpa'''''), ''it '''both''' it'', '''''Alnus'' tree'''"
        self.assertEqual(wikitext.bold_terms(paragraph), [("Calamansi", False), ("Citrus × microcarpa", True),
                                                          ("both", True), ("Alnus tree", True)])
        self.assertEqual(wikitext.bold_terms("'''open\n'''shut'''"), [("shut", False)])

    def test_common_names(self):
        paragraph = ("The '''almond''' ('''''Prunus amygdalus''''') or '''[[Cruciferae]]''', "
                     "'''''Foo'' bar''', '''Prunus dulcis''', '''\"wood lily\"''', '''almond'''")
        self.assertEqual(wikitext.common_names(paragraph, ["Prunus dulcis"]), ["almond", "wood lily"])

    def test_first_paragraph_skips_files_and_templates(self):
        lead = "\n[[File:a.jpg|thumb|x]]\n{{multiple image|a|b}}\n\nFirst '''one'''.\n\nSecond."
        self.assertEqual(wikitext.first_paragraph(lead), "First '''one'''.")

    def test_lead_ends_at_the_first_heading(self):
        text = "{{Speciesbox}}\nLead text.\n==Description==\nBody"
        self.assertEqual(wikitext.lead_wikitext(text, len("{{Speciesbox}}")), "\nLead text.\n")

    def test_plant_hint(self):
        self.assertTrue(wikitext.plant_hint("", "", ["Flora of Spain"]))
        self.assertFalse(wikitext.plant_hint("", "", ["Taxa named by Carl Linnaeus"]))
        self.assertTrue(wikitext.plant_hint("{{Short description|Genus of conifers}}", "", []))
        self.assertFalse(wikitext.plant_hint("{{Short description|Family of fruit bats}}", "", []))

    def test_plant_hint_from_a_botanical_family_category(self):
        # Lactuca and Oenanthe (plant) in the full dump; Pyronia is a butterfly, Wheatear a bird.
        self.assertTrue(wikitext.plant_hint("", "", ["Lactuca", "Asteraceae genera"]))
        self.assertTrue(wikitext.plant_hint("", "", ["Oenanthe (plant)", "Apioideae genera"]))
        self.assertTrue(wikitext.plant_hint("", "", ["Ilex", "Ornamental trees"]))
        self.assertFalse(wikitext.plant_hint("", "", ["Pyronia", "Satyrini", "Butterfly genera"]))
        self.assertFalse(wikitext.plant_hint("", "", ["Wheatears", "Taxa named by Louis Pierre Vieillot"]))


class SynonymTest(unittest.TestCase):

    def test_species_list_in_collapsible_list(self):
        # The flag in the author cell belongs to its own name only.
        value = ("{{collapsible list |title=Homotypic|{{species list\n|Amygdalus amygdalus |(Batsch) Frye, 1912 "
                 "[[nom. illeg.]]\n|Persica |Mill., 1754\n}}}}")
        self.assertEqual(wikitext.parse_synonyms(value), ["Persica"])

    def test_genus_list_with_hybrid_sign(self):
        value = "{{Genus list|hidden=yes|Aurantium|Mill.|×Citrofortunella|J.W.Ingram|Citreum|Mill.}}"
        self.assertEqual(wikitext.parse_synonyms(value), ["Aurantium", "× Citrofortunella", "Citreum"])

    def test_plainlist_with_authors_and_notes(self):
        value = ("{{Plainlist | style = x; |\n*''Crinum floridum'' <small>Salisb.</small> nom. superfl.\n"
                 "*''Prunus dulcis'' var. ''amara'' <small>(DC.) Buchheim</small>\n}}")
        self.assertEqual(wikitext.parse_synonyms(value), ["Crinum floridum", "Prunus dulcis var. amara"])

    def test_abbreviated_genus(self):
        value = ("* ''Lactuca scariola'' <small>L.</small>\n* ''L.&nbsp;scariola'' var. ''integrata'' "
                 "<small>Gren.</small>\n* ''Q. robur''")
        self.assertEqual(wikitext.parse_synonyms(value, "Lactuca"),
                         ["Lactuca scariola", "Lactuca scariola var. integrata"])

    def test_plain_lines(self):
        value = "Homotypic<br />Betulales<br>* Foo bar de Vriese\nsee [[list]]\n<!-- ''Hidden name'' -->"
        self.assertEqual(wikitext.parse_synonyms(value), ["Betulales", "Foo bar"])

    def test_accepted_name_and_duplicates_dropped(self):
        value = "* ''Musa silvéstris''\n* ''Musa textilis''\n* ''Musa silvéstris''"
        self.assertEqual(wikitext.parse_synonyms(value, "Musa", {"Musa textilis"}), ["Musa silvéstris"])

    def test_empty(self):
        self.assertEqual(wikitext.parse_synonyms(None), [])
        self.assertEqual(wikitext.parse_synonyms("''see'' [[Taxonomic synonyms of Solanum tuberosum|list]]"), [])


class RankTest(unittest.TestCase):

    def test_automatic_taxobox_ranks(self):
        rank = wikitext.taxon_rank
        self.assertEqual(rank("automatic taxobox", {}, "Asteraceae", None, ""), "higher")
        self.assertEqual(rank("automatic taxobox", {"subdivision_ranks": "Subgenera and sections"}, "Quercus", None,
                              ""), "genus")
        self.assertEqual(rank("automatic taxobox", {"subdivision_ranks": "Genera"}, "Amphibia", None, ""), "higher")
        self.assertEqual(rank("automatic taxobox", {}, "Nyssa", None, "Nyssa is a small genus of trees"), "genus")
        self.assertEqual(rank("automatic taxobox", {}, "Carnivora", None, "Carnivora is an order of mammals",
                              "Carnivora"), "higher")
        self.assertEqual(rank("automatic taxobox", {}, "Bison", None, "", "Bison"), "genus")
        self.assertIsNone(rank("automatic taxobox", {}, "Prunus sect. Armeniaca", None, "Apricot is a genus"))
        self.assertEqual(rank("automatic taxobox", {}, "Acer palmatum", "Acer palmatum", ""), "species")
        self.assertIsNone(rank("hybridbox", {}, None, None, ""))

    def test_box_names(self):
        self.assertEqual(wikitext.box_names("speciesbox", {"taxon": "Prunus dulcis"}),
                         ("Prunus", "dulcis", "Prunus dulcis", "Prunus dulcis"))
        self.assertEqual(wikitext.box_names("subspeciesbox", {"genus": "Equus", "species": "ferus",
                                                               "subspecies": "caballus"}),
                         ("Equus", "ferus", None, "Equus ferus caballus"))
        self.assertEqual(wikitext.box_names("automatic taxobox", {}, "Panthera"), (None, None, "Panthera", None))
        self.assertEqual(wikitext.box_names("speciesbox", {"genus": "Dryas (plant)", "species": "octopetala"}),
                         ("Dryas", "octopetala", None, "Dryas octopetala"))


class NotGenusRankTest(unittest.TestCase):
    """F1: sections, undescribed species and cultivars are no genus pages."""

    def test_old_taxobox_below_genus(self):
        # "North American azaleas": genus = ''[[Rhododendron]]'', sectio = Pentanthera
        rank = wikitext.taxon_rank
        params = {"genus": "''[[Rhododendron]]''", "sectio": "'''''Pentanthera'''''"}
        self.assertIsNone(rank("taxobox", params, None, None, ""))
        for below in ("subgenus", "subsectio", "series", "species"):
            with self.subTest(below=below):
                self.assertIsNone(rank("taxobox", {"genus": "''Prunus''", below: "''X''"}, None, None, ""))
        self.assertEqual(rank("taxobox", {"genus": "''Prunus''", "sectio": ""}, None, None, ""), "genus")
        self.assertEqual(rank("taxobox", {"familia": "[[Rosaceae]]"}, None, None, ""), "higher")

    def test_undescribed_species_under_a_genus_taxon(self):
        source = ("{{Automatic taxobox\n| taxon = Pelargonium\n}}\n'''''Pelargonium'' sp. Striatellum''', commonly "
                  "known as '''Omeo stork's-bill''', is an undescribed species of plant in the genus Pelargonium.\n")
        result = wikitext.parse_box(source, "Pelargonium sp. Striatellum")
        self.assertIsNone(result["rank"])
        self.assertEqual(result["genus"], "Pelargonium")
        self.assertEqual(result["common_names"], ["Omeo stork's-bill"])

    def test_informal_titles_and_cultivars(self):
        rank = wikitext.taxon_rank
        for title in ("Acacia aff. victoriae", "Grevillea sp. nov. Cooljarloo", "Prunus 'Kanzan'",
                      "Rosa ‘Peace’"):
            with self.subTest(title=title):
                taxon = title.split(" ")[0]
                self.assertIsNone(rank("automatic taxobox", {}, taxon, None, taxon + " is a genus of plants", title))
        self.assertEqual(rank("automatic taxobox", {}, "Bison", None, "", "Bison"), "genus")


class GenusRankTest(unittest.TestCase):
    """F2: a lead that says genus beats the name ending, "family" and "clade"."""

    def rank(self, taxon, lead, params=None):
        return wikitext.taxon_rank("automatic taxobox", params or {}, taxon, None, lead, taxon)

    def test_lead_says_genus(self):
        self.assertEqual(self.rank("Hippophae", "Hippophae is a genus of flowering plants in the family "
                                                "Elaeagnaceae."), "genus")
        self.assertEqual(self.rank("Syncarpia", "Syncarpia is a small group of trees in the myrtle family "
                                                "(Myrtaceae) described as a genus in 1839."), "genus")
        self.assertEqual(self.rank("Rosmarinus", "Rosmarinus is a small taxonomic clade of woody, perennial herbs "
                                                 "in the family Lamiaceae. In 2017 the species in the genus "
                                                 "Rosmarinus were moved into the large genus Salvia."), "genus")
        self.assertEqual(self.rank("Byrsonima", "Byrsonima is one of about 75 genera in the Malpighiaceae, a family "
                                                "of flowering plants."), "genus")
        self.assertEqual(self.rank("Chrysopsis", "Chrysopsis (golden asters) are plants in the family Asteraceae. "
                                                 "Some species formerly classified in this genus are now elsewhere."),
                         "genus")

    def test_subdivision_ranks_are_weak_evidence(self):
        # Neviusia: "subdivision_ranks = Genera" over a list of species.
        self.assertEqual(self.rank("Neviusia", "Neviusia, the snow-wreaths, is a genus of ornamental plants.",
                                   {"subdivision_ranks": "Genera"}), "genus")
        self.assertEqual(self.rank("Amphibia", "", {"subdivision_ranks": "Genera"}), "higher")

    def test_type_species_beats_the_ending(self):
        self.assertEqual(self.rank("Hippophae", "", {"type_species": "''Hippophae rhamnoides''"}), "genus")

    def test_higher_taxa_stay_higher(self):
        self.assertEqual(self.rank("Asteraceae", "Asteraceae is a large family of over 1,600 genera."), "higher")
        self.assertEqual(self.rank("Rosaceae", "Rosaceae is a family of plants. The type genus is Rosa."), "higher")
        self.assertEqual(self.rank("Malvoideae", "Malvoideae is a subfamily. The genus Malva gives the name."),
                         "higher")
        self.assertEqual(self.rank("Carnivora", "Carnivora is an order of mammals"), "higher")

    def test_parse_box_of_a_genus_with_a_higher_ending(self):
        source = ("{{Automatic taxobox\n| taxon = Hippophae\n| authority = L.\n}}\n"
                  "'''''Hippophae''''' is a genus of flowering plants.\n")
        result = wikitext.parse_box(source, "Hippophae")
        self.assertEqual((result["genus"], result["rank"]), ("Hippophae", "genus"))


class LeadStartTest(unittest.TestCase):
    """F3: map data and wrapper templates do not hide the first paragraph."""

    def test_mapframe_in_the_box(self):
        source = ("{{Speciesbox\n| genus = Aria\n| species = admonitor\n| status = EN\n| status_system = IUCN3.1\n"
                  "| range_map = <mapframe width=220>[{\"type\":\"ExternalData\","
                  "\"properties\":{\"title\":\"native\"}}]</mapframe>\n"
                  "| synonyms = * ''Sorbus admonitor'' <small>M.Proctor</small>\n}}\n\n"
                  "'''''Aria admonitor''''', the '''Watersmeet whitebeam''', is a tree.\n")
        result = wikitext.parse_page(page_record(source, title="Aria admonitor"))
        self.assertEqual(result["synonyms"], ["Sorbus admonitor"])
        self.assertEqual(result["synonym_authors"], {"Sorbus admonitor": "M.Proctor"})
        self.assertEqual(result["common_names"], ["Watersmeet whitebeam"])
        self.assertEqual(result["lead"], "Aria admonitor, the Watersmeet whitebeam, is a tree.")
        self.assertEqual(result["iucn_status"], "EN")

    def test_other_non_wikitext_elements_in_the_box(self):
        source = ("{{Speciesbox\n| genus = Aria\n| species = b\n| note = <math>\\frac{a}{b}}</math> "
                  "<syntaxhighlight lang=json>{\"a\": {\"b\": 1}}</syntaxhighlight>\n| authority = L.\n}}\n"
                  "'''''Aria b''''' is a tree.")
        result = wikitext.parse_box(source, "Aria b")
        self.assertEqual((result["authority"], result["lead"]), ("L.", "Aria b is a tree."))

    def test_box_in_a_wrapper_template(self):
        source = ("{{stack|\n{{Speciesbox\n| taxon = Asparagus officinalis\n| authority = L.\n}}\n}}\n\n"
                  "'''Asparagus''' ('''''Asparagus officinalis''''') or '''garden asparagus''' is a plant.\n")
        result = wikitext.parse_box(source, "Asparagus")
        self.assertEqual(result["lead"], "Asparagus (Asparagus officinalis) or garden asparagus is a plant.")
        self.assertEqual(result["common_names"], ["garden asparagus"])

    def test_unclosed_template_before_the_box(self):
        source = "{{Short description|x\n{{Speciesbox|genus=Aria|species=b}}\nLead text."
        self.assertEqual(wikitext.parse_box(source, "Aria b")["lead"], "Lead text.")

    def test_first_paragraph_needs_letters(self):
        self.assertEqual(wikitext.first_paragraph("}}\n\n] |\n\nFirst '''one'''."), "First '''one'''.")


class LeadMarkupTest(unittest.TestCase):
    """F6: pseudo-headings, lists, tables and {{convert}} in the lead."""

    def test_pseudo_heading_ends_the_lead(self):
        source = ("{{Automatic taxobox\n| taxon = Maltebrunia\n}}\n'''''Maltebrunia''''' is a genus.\n\n; Species\n"
                  "* ''[[Maltebrunia leersioides]]'' <small>Kunth</small> – Madagascar\n{| class=\"wikitable\"\n|-\n"
                  "! Name\n|}\n")
        self.assertEqual(wikitext.parse_box(source, "Maltebrunia")["lead"], "Maltebrunia is a genus.")

    def test_lists_and_tables_dropped(self):
        text = ("{{X}}\nFirst.\n* a list item\n# numbered\n: indented\n{| class=\"wikitable\"\n|-\n| cell\n|}\n"
                "Second.\n==Description==\nBody")
        self.assertEqual(wikitext.plain_text(wikitext.lead_wikitext(text, len("{{X}}"))), "First. Second.")

    def test_list_lines_inside_refs_and_templates_kept_whole(self):
        # Panax notoginseng: a reference with bulleted citations inside the first paragraph.
        source = ("{{Speciesbox\n| genus = Panax\n| species = notoginseng\n}}\n"
                  "'''''Panax notoginseng''''' is called '''Chinese ginseng'''<ref name=\"M\">{{cite web|title=a}}\n"
                  "*{{cite web |title=b}}</ref> or '''notoginseng''' {{efn|x\n* a note}} and '''sanchi'''.\n")
        result = wikitext.parse_box(source, "Panax notoginseng")
        self.assertEqual(result["common_names"], ["Chinese ginseng", "notoginseng", "sanchi"])
        self.assertEqual(result["lead"], "Panax notoginseng is called Chinese ginseng or notoginseng and sanchi.")

    def test_convert_keeps_numbers(self):
        plain = wikitext.plain_text
        self.assertEqual(plain("It grows to {{convert|2|m|ft}} tall at {{cvt|800|-|1800|m}} elevation."),
                         "It grows to 2 m tall at 800–1800 m elevation.")
        self.assertEqual(plain("{{convert|2|to|3|m|ft|abbr=on}} long"), "2 to 3 m long")
        self.assertEqual(plain("at {{cvt|800-1800|m}}"), "at 800-1800 m")
        self.assertEqual(plain("{{convert|6|ft|2|in|m}}"), "6 ft 2 in")
        self.assertEqual(plain("{{Convert|1.5|x|2|cm}}"), "1.5 × 2 cm")
        self.assertEqual(plain("{{convert|-5|C|F}} in winter"), "-5 °C in winter")
        # Wheat, Eggplant: "e6" before the unit is "million".
        self.assertEqual(plain("production was {{convert|61|e6t|e6ST}}, with"), "production was 61 million t, with")


class SynonymNameTest(unittest.TestCase):
    """F4: connectors, &nbsp;, informal names, bold headings, shifted species lists."""

    def test_infrageneric_connectors(self):
        self.assertEqual(wikitext.parse_synonyms("* ''Oryza'' sect. ''Maltebrunia'' <small>(Kunth) Rchb.</small>",
                                                 "Maltebrunia", {"Maltebrunia"}), ["Oryza sect. Maltebrunia"])
        value = ("* ''Billardiera'' ser. ''Pictae'' <small>(Benth.) E.M.Benn.</small>\n"
                 "* ''Marianthus'' sect. ''Granularia'' <small>Kuntze</small>")
        self.assertEqual(wikitext.parse_synonyms(value, "Marianthus", {"Marianthus"}),
                         ["Billardiera ser. Pictae", "Marianthus sect. Granularia"])

    def test_nbsp_between_italic_runs(self):
        self.assertEqual(wikitext.parse_synonyms("*''Platanus''&nbsp;×&nbsp;''hybrida'' <small>Brot.</small>",
                                                 "Platanus"), ["Platanus × hybrida"])
        self.assertEqual(wikitext.parse_synonyms("*''Platanus''&amp;nbsp;×&amp;nbsp;''hybrida''", "Platanus"),
                         ["Platanus × hybrida"])

    def test_informal_names_and_the_own_genus(self):
        parse = wikitext.parse_synonyms
        self.assertEqual(parse("*''Nepenthes'' sp.<br /><small>Sh.Kurata (1976)</small>", "Nepenthes"), [])
        self.assertEqual(parse("''Acacia'' sp. Pilbara <small>(S.van Leeuwen 690)</small>", "Acacia"), [])
        self.assertEqual(parse("*''Prunus {{as written|mississi|pi}}'' <small>Marsh.</small>", "Prunus"), [])
        self.assertEqual(parse("* ''Prunus''\n* ''Padus'' <small>Mill.</small>", "Prunus"), ["Padus"])

    def test_bold_headings(self):
        self.assertEqual(wikitext.parse_synonyms("'''Basionym'''<br/>\n* ''Aster novae-angliae'' {{small|L.}}",
                                                 "Symphyotrichum"), ["Aster novae-angliae"])
        self.assertEqual(wikitext.parse_synonyms("'''Homotypic'''<br>''Aster x-us''", "Aster"), ["Aster x-us"])
        self.assertEqual(wikitext.parse_synonyms("'''Synonyms''' ''Aster x-us''", "Aster"), ["Aster x-us"])
        # Gentiana acaulis: the heading names the accepted taxon, not a synonym.
        value = ("'''Synonyms of ''Gentiana acaulis'''''\n*''Gentianusa acaulis'' (L.) Pohl\n"
                 "'''Synonyms of ''Gentiana acaulis'' subsp. ''acaulis'' '''\n*''Ciminalis acaulis'' Borkh.")
        self.assertEqual(wikitext.parse_synonyms(value, "Gentiana", {"Gentiana acaulis"}),
                         ["Gentianusa acaulis", "Ciminalis acaulis"])

    def test_author_abbreviation_is_no_flag(self):
        # "De Not." is De Notaris; only a lower-case "not" introduces another name.
        self.assertEqual(wikitext.parse_synonyms("* ''Pallavicinia'' <small>De Not.</small>", "Solanum"),
                         ["Pallavicinia"])
        self.assertEqual(wikitext.synonym_entries("* ''Pallavicinia'' <small>De Not.</small>"),
                         [("Pallavicinia", "De Not.")])

    def test_species_list_with_a_missing_author_cell(self):
        value = ("{{Species list\n|Satureja montana subsp. montana\n|Satureja montana var. stenophylla |Boiss.\n"
                 "|Satureja trifida |Moench\n}}")
        self.assertEqual(wikitext.parse_synonyms(value, "Satureja"), [
            "Satureja montana subsp. montana", "Satureja montana var. stenophylla", "Satureja trifida"])
        entries = wikitext.synonym_entries(value, "Satureja")
        self.assertEqual(entries, [("Satureja montana subsp. montana", None),
                                   ("Satureja montana var. stenophylla", "Boiss."), ("Satureja trifida", "Moench")])

    def test_species_list_name_cell_with_part_of_the_author(self):
        # Dracocephalum parviflorum, Berberis repens: the basionym author sits in the name cell.
        value = ("{{Species list\n | Dracocephalum parviflorum var. chelonicum | Lunell\n"
                 " | Ruyschiana parviflora (Nutt.) | House\n}}")
        self.assertEqual(wikitext.synonym_entries(value, "Dracocephalum"), [
            ("Dracocephalum parviflorum var. chelonicum", "Lunell"), ("Ruyschiana parviflora", "(Nutt.) House")])

    def test_bracketed_entry(self):
        # Utricularia hirta: "*[''U.&nbsp;capillacea''&nbsp;<small>[[Martin Vahl (botanist)|Vahl]]</small>]"
        value = "*[''U.&nbsp;capillacea''&nbsp;<small>[[Martin Vahl (botanist)|Vahl]]</small>]"
        self.assertEqual(wikitext.synonym_entries(value, "Utricularia"), [("Utricularia capillacea", "Vahl")])

    def test_species_list_with_an_author_cell_without_name(self):
        value = "{{Species list|Satureja alba|L.|(L.) Mill.|Satureja nigra|Moench|Persica|Mill.}}"
        self.assertEqual(wikitext.parse_synonyms(value, "Satureja"), ["Satureja alba", "Satureja nigra", "Persica"])


class FlaggedSynonymTest(unittest.TestCase):
    """J1: homonyms and misapplied names are left out; authors are kept per name."""

    def test_flagged_entries_dropped(self):
        value = ("* ''Acer flabellatum'' Greene 1912 not Rehder 1905\n* ''Quercus undulata'' Benth., nom. illeg.\n"
                 "* ''Smilax excelsa'' Duhamel nom. inval.\n"
                 "* ''Salix fragilis'' Host, not ''Salix'' × ''fragilis'' L.\n"
                 "* ''Genista ephedroides'' sensu Coste\n* ''Prunus communis'' (L.) Arcang.\n"
                 "* ''Prunus amara'' <small>auct.</small>\n* ''Prunus nana'' Mill. p.p.\n"
                 "* ''Prunus fruticosa'' Pall., pro parte\n* ''Prunus x-us'' Nonne\n* ''Prunus y-us'' L. (misapplied)")
        self.assertEqual(wikitext.parse_synonyms(value), ["Prunus communis", "Prunus x-us"])

    def test_flag_belongs_to_its_own_entry(self):
        self.assertEqual(wikitext.parse_synonyms("* ''Abies alba'' Mill.\n* ''Abies picea'' auct. non Mill."),
                         ["Abies alba"])
        self.assertEqual(wikitext.parse_synonyms("''Abies alba'' Mill., ''Abies pectinata'' DC. nom. illeg., "
                                                 "''Abies nobilis'' A.Dietr."), ["Abies alba", "Abies nobilis"])
        # The author line after <br> belongs to the name before it.
        self.assertEqual(wikitext.parse_synonyms("* ''Abies alba''<br /><small>auct. non Mill.</small>\n"
                                                 "* ''Abies nobilis''<br /><small>A.Dietr.</small>"),
                         ["Abies nobilis"])

    def test_synonym_entries_keep_the_author(self):
        value = ("* ''Prunus communis'' (L.) Arcang., 1882\n* ''Prunus x-us'' {{au|[[Carl Linnaeus|L.]]}}\n"
                 "* ''Prunus y-us''\n* ''Prunus z-us'' <small>Mill. (1768)</small>")
        self.assertEqual(wikitext.synonym_entries(value), [
            ("Prunus communis", "(L.) Arcang."), ("Prunus x-us", "L."), ("Prunus y-us", None),
            ("Prunus z-us", "Mill.")])

    def test_author_notes_stripped(self):
        # Wasabi, Dactylorhiza fuchsii, Pea in the sample.
        value = ("*''Lunaria japonica'' ([[basionym]]) <small>Miq.</small>\n"
                 "*''Orchis longibracteata'' {{small|F.W.Schmidt (1795), tentatively listed as a synonym}}\n"
                 "*''Pisum album'' {{small|Garsault (1764), opus utique rej.}}\n"
                 "*''Mentha sylvestris'' convar. ''cyrtophylla'' Alef.")
        self.assertEqual(wikitext.synonym_entries(value), [
            ("Lunaria japonica", "Miq."), ("Orchis longibracteata", "F.W.Schmidt"), ("Pisum album", "Garsault"),
            ("Mentha sylvestris convar. cyrtophylla", "Alef.")])

    def test_spelled_out_flags(self):
        value = ("* ''Mithridatium'' <small>Adans. 1763, illegitimate superfluous name</small>\n"
                 "* ''Blumenbachia'' <small>Koeler 1802, rejected name</small>\n"
                 "* ''Dens-canis'' <small>Tourn. ex Rupp. 1745, invalid</small>\n* ''Erythronium'' L.")
        self.assertEqual(wikitext.parse_synonyms(value), ["Erythronium"])

    def test_parse_box_synonym_authors(self):
        source = ("{{Speciesbox\n| genus = Acer\n| species = macrophyllum\n| authority = Pursh\n| synonyms =\n"
                  "* ''Acer flabellatum'' Greene 1912 not Rehder 1905\n* ''Acer leucoderme'' Small\n"
                  "* ''Acer murrayanum'' Dippel\n}}\n'''''Acer macrophyllum''''' is a tree.")
        result = wikitext.parse_box(source, "Acer macrophyllum")
        self.assertEqual(result["synonyms"], ["Acer leucoderme", "Acer murrayanum"])
        self.assertEqual(result["synonym_authors"], {"Acer leucoderme": "Small", "Acer murrayanum": "Dippel"})


class YearDescribedTest(unittest.TestCase):
    """F5: the year after a parenthesised basionym author is the year of the new combination."""

    def test_combination_year_is_not_the_description_year(self):
        year = wikitext.year_described
        self.assertEqual(year("(L.) Spreng., 1826", ["Plants described in 1753"]), 1753)
        self.assertIsNone(year("(L.) Delarbre 1800", []))
        self.assertEqual(year("(Hook.) Nutt. 1834 not L. 1753", ["Plants described in 1818"]), 1818)

    def test_zoological_and_plain_years_kept(self):
        year = wikitext.year_described
        self.assertEqual(year("(Linnaeus, 1758)", []), 1758)
        self.assertEqual(year("(Linnaeus, 1758)", ["Taxa described in 1760"]), 1758)
        self.assertEqual(year("Batsch, 1801", ["Plants described in 1753"]), 1801)
        self.assertEqual(year("L. 1753 not Scop. 1777", []), 1753)


class CommonNameFilterTest(unittest.TestCase):
    """F7: rank fragments and Latin binomials in bold are no common names."""

    def test_rank_fragment(self):
        paragraph = "'''''Dudleya saxosa''''' '''subsp. ''saxosa''''' is a plant, the '''Panamint dudleya'''."
        self.assertEqual(wikitext.common_names(paragraph, ["Dudleya saxosa subsp. saxosa", "Dudleya"]),
                         ["Panamint dudleya"])
        # Koelreuteria elegans: "'''''Koelreuteria elegans''''' '''ssp'''. ''formosana''"
        self.assertEqual(wikitext.common_names("'''ssp'''. ''formosana'', the '''flamegold'''", []), ["flamegold"])

    def test_bold_latin_binomial_of_the_genus(self):
        self.assertEqual(wikitext.common_names("'''''Asimina incana''''' or '''Asimina speciosa''' is a shrub.",
                                               ["Asimina incana", "Asimina"]), [])
        self.assertEqual(wikitext.common_names("'''Peperomia scandens''' and '''Draba corymbosa R. Br. ex DC'''",
                                               [], genus="Peperomia"), ["Draba corymbosa R. Br. ex DC"])

    def test_english_names_starting_with_the_genus_kept(self):
        paragraph = "'''Vanilla orchids''', '''Asparagus fern''', '''Stauntonia vine''', '''Kalimeris asters'''"
        self.assertEqual(wikitext.common_names(paragraph, [], genus="Vanilla"),
                         ["Vanilla orchids", "Asparagus fern", "Stauntonia vine", "Kalimeris asters"])
        self.assertEqual(wikitext.common_names("'''Stauntonia vine'''", [], genus="Stauntonia"), ["Stauntonia vine"])


class BoxDetailTest(unittest.TestCase):
    """F8: rare box layouts and name cleaning."""

    def test_old_taxobox_trinomial_and_genus_authority(self):
        source = ("{{Taxobox\n| regnum = [[Plantae]]\n| genus = ''[[Citrus]]''\n"
                  "| species = ''[[Citrus medica|C. medica]]''\n"
                  "| binomial_authority = L.\n| trinomial = ''Citrus medica'' var. ''sarcodactylis''\n"
                  "| trinomial_authority = (Hoola van Nooten) Swingle\n}}\nText.")
        result = wikitext.parse_box(source, "Buddha's hand")
        self.assertEqual((result["binomial"], result["rank"]), ("Citrus medica var. sarcodactylis", "infraspecies"))
        self.assertEqual(result["authority"], "(Hoola van Nooten) Swingle")
        source = ("{{Taxobox\n| regnum = [[Animalia]]\n| genus = '''''Lophophora'''''\n"
                  "| genus_authority = Möschler, 1890\n}}\nText.")
        result = wikitext.parse_box(source, "Lophophora")
        self.assertEqual((result["rank"], result["authority"], result["year_described"]),
                         ("genus", "Möschler, 1890", 1890))

    def test_hybridbox(self):
        # Template:Hybridbox has genus, species1, species2 (or father/mother) and no parameter for the
        # epithet of the hybrid, so a binomial is built only from an explicit species / nothospecies.
        source = ("{{Hybridbox\n| name = ''Abies'' × ''borisii-regis''\n| genus = Abies\n| species1 = alba\n"
                  "| species2 = cephalonica\n| authority = Mattf.\n}}\nText.")
        result = wikitext.parse_box(source, "Abies × borisii-regis")
        self.assertEqual((result["genus"], result["species"], result["binomial"], result["rank"]),
                         ("Abies", None, None, None))
        for param in ("species", "nothospecies"):
            with self.subTest(param=param):
                names = wikitext.box_names("hybridbox", {"genus": "Abies", param: "borisii-regis",
                                                         "species1": "alba", "species2": "cephalonica"})
                self.assertEqual(names, ("Abies", "borisii-regis", None, "Abies × borisii-regis"))

    def test_informal_groups_of_automatic_taxoboxes(self):
        for taxon in ("Cladrastis clade", "Aloe group", "Quercus robur complex", "Dryas alliance"):
            with self.subTest(taxon=taxon):
                self.assertEqual(wikitext.box_names("automatic taxobox", {"taxon": taxon}), (None, None, taxon, None))
        self.assertEqual(wikitext.box_names("automatic taxobox", {"taxon": "Acer palmatum"}),
                         ("Acer", "palmatum", "Acer palmatum", "Acer palmatum"))

    def test_clean_name_underscores(self):
        self.assertEqual(wikitext.clean_name("Plinia_(bug)"), "Plinia")
        self.assertEqual(wikitext.clean_name("Prunus_dulcis"), "Prunus dulcis")

    def test_genus_repeated_in_the_species(self):
        self.assertEqual(wikitext.box_names("speciesbox", {"genus": "Juncus", "species": "Juncus xiphioides"}),
                         ("Juncus", "xiphioides", None, "Juncus xiphioides"))
        self.assertEqual(wikitext.box_names("speciesbox", {"genus": "Juncus", "species": "''J. xiphioides''"}),
                         ("Juncus", "xiphioides", None, "Juncus xiphioides"))

    def test_capital_x_as_hybrid_sign(self):
        self.assertEqual(wikitext.box_names("speciesbox", {"genus": "Quercus", "species": "X bimundorum"}),
                         ("Quercus", "bimundorum", None, "Quercus × bimundorum"))
        names = wikitext.box_names("automatic taxobox", {"taxon": "Quercus x bimundorum"})
        self.assertEqual(names[3], "Quercus × bimundorum")
        self.assertEqual(wikitext.taxon_rank("automatic taxobox", {}, names[2], names[3], ""), "species")
        names = wikitext.box_names("taxobox", {"binomial": "''Quercus'' X ''bimundorum''"})
        self.assertEqual(names[3], "Quercus × bimundorum")

    def test_file_caption_with_an_external_link(self):
        self.assertEqual(wikitext.plain_text("[[File:a.jpg|thumb|Photo [http://x.org by X]]] Text"), "Text")


class PlantHintGeneraTest(unittest.TestCase):
    """J2: order and plant-group genus categories, yams."""

    def test_plant_order_and_group_genera(self):
        hint = wikitext.plant_hint
        self.assertTrue(hint("", "", ["Dioscorea", "Dioscoreales genera"]))
        self.assertTrue(hint("{{Short description|Genus of yams}}", "", []))
        for group in ("Gymnosperm", "Fern", "Moss", "Liverwort", "Lycophyte", "Hornwort", "Conifer", "Cycad"):
            with self.subTest(group=group):
                self.assertTrue(hint("", "", [group + " genera"]))
        self.assertTrue(hint("", "", ["Marchantia", "Marchantiales genera"]))

    def test_animal_fungal_and_lichen_genera(self):
        hint = wikitext.plant_hint
        for name in ("Lecanorales genera", "Agaricales genera", "Peltigerales genera", "Lichen genera",
                     "Gastropod genera", "Noctuoidea genera", "Passeriformes genera", "Lepidoptera genera",
                     "Rhizobiales genera", "Squamata genera"):
            with self.subTest(category=name):
                self.assertFalse(hint("", "", [name]))


if __name__ == "__main__":
    unittest.main()
