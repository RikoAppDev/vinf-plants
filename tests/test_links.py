import os
import unittest

from crawler import config
from crawler.links import extract_links, extract_sitemap_urls, normalize_url
from crawler.storage import file_name_for

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BASE = "https://plants.ces.ncsu.edu/plants/quercus-alba/"


class NormalizeUrlTest(unittest.TestCase):
    def test_relative_url_becomes_absolute(self):
        self.assertEqual(normalize_url("/plants/acer-rubrum/", BASE), "https://plants.ces.ncsu.edu/plants/acer-rubrum/")

    def test_fragment_is_dropped(self):
        self.assertEqual(normalize_url("/plants/acer-rubrum/#top", BASE), "https://plants.ces.ncsu.edu/plants/acer-rubrum/")

    def test_html_entities_in_query_are_decoded(self):
        self.assertEqual(normalize_url("/find_a_plant/?a=1&amp;b=2", BASE), "https://plants.ces.ncsu.edu/find_a_plant/?a=1&b=2")

    def test_host_is_lowercased_but_path_is_not(self):
        self.assertEqual(normalize_url("HTTPS://Plants.CES.ncsu.edu/Plants/X/", BASE), "https://plants.ces.ncsu.edu/Plants/X/")

    def test_non_http_links_are_skipped(self):
        for raw in ("mailto:someone@example.org", "javascript:void(0)", "tel:+421", "#section", ""):
            self.assertIsNone(normalize_url(raw, BASE), raw)


class ExtractLinksTest(unittest.TestCase):
    def test_all_quote_styles(self):
        page = """<a href="/plants/a/">A</a> <A class='x' HREF='/plants/b/'>B</A> <a href=/plants/c/>C</a>"""
        self.assertEqual(extract_links(page, BASE), [
            "https://plants.ces.ncsu.edu/plants/a/",
            "https://plants.ces.ncsu.edu/plants/b/",
            "https://plants.ces.ncsu.edu/plants/c/",
        ])

    def test_duplicates_are_reported_once(self):
        page = '<a href="/plants/a/">1</a><a href="/plants/a/#x">2</a>'
        self.assertEqual(extract_links(page, BASE), ["https://plants.ces.ncsu.edu/plants/a/"])

    def test_link_tags_without_anchor_are_ignored(self):
        self.assertEqual(extract_links('<link href="/static/site.css"><area href="/x/">', BASE), [])

    def test_real_page_links_to_related_plants_but_facets_are_not_allowed(self):
        with open(os.path.join(FIXTURES, "ncsu_hydrocotyle_americana.html"), encoding="utf-8") as handle:
            links = extract_links(handle.read(), "https://plants.ces.ncsu.edu/plants/hydrocotyle-americana/")
        allow = config.SITES["ncsu"].allow
        allowed = [link for link in links if allow.match(link)]
        self.assertIn("https://plants.ces.ncsu.edu/plants/hydrocotyle-umbellata/", allowed)
        self.assertTrue(any("/find_a_plant/?tag=" in link for link in links))
        self.assertFalse(any("find_a_plant" in link or "common-name" in link for link in allowed))


class SitemapTest(unittest.TestCase):
    def test_loc_entries(self):
        xml = "<urlset><url><loc>https://x.org/a/</loc></url><url><loc> https://x.org/b/?p=1&amp;q=2 </loc></url></urlset>"
        self.assertEqual(extract_sitemap_urls(xml), ["https://x.org/a/", "https://x.org/b/?p=1&q=2"])


class FileNameTest(unittest.TestCase):
    def test_name_is_readable_safe_and_stable(self):
        name = file_name_for("https://plants.ces.ncsu.edu/plants/quercus-alba/")
        self.assertRegex(name, r"^plants_quercus-alba__[0-9a-f]{10}\.html$")
        self.assertEqual(name, file_name_for("https://plants.ces.ncsu.edu/plants/quercus-alba/"))

    def test_different_urls_never_collide(self):
        self.assertNotEqual(file_name_for("https://x.org/a?b=1"), file_name_for("https://x.org/a_b=1"))


if __name__ == "__main__":
    unittest.main()
