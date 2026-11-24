"""Tests of the web search page on a tiny index; skipped where PyLucene is not installed.

The index holds the documents of test_lucene_index and a few more that the page needs: a plant of every
Wikipedia match level, two pages on one site, a single hardiness zone, values with HTML characters and a
page URL that is no http URL.

Run them in the PyLucene image: ./lucene_docker.sh unittest tests.test_lucene_web
"""

import contextlib
import io
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from lucene_index import documents, querycheck
from tests.test_lucene_index import DOCS, doc, lucene, run_main

if lucene:
    from crawler import config
    from lucene_index import build, search, web

    class QuietHandler(web.Handler):
        def log_message(self, *args):
            pass


WIKI = "https://en.wikipedia.org/wiki/"
TSO = "https://www.treesandshrubsonline.org/articles/clematis/"
EXTRA_DOCS = [
    doc(12, name=["Ulmus minor"], common_name=["Field elm"], plant_type=["Tree"], tolerates=["Drought"],
        soil=["Clay"], origin=["Europe"], iucn=["vu"], text=["Drought tolerant once established."], source=["pfaf"],
        url=["https://pfaf.org/user/Plant.aspx?LatinName=Ulmus+minor"], wiki_title=["Ulmus minor"],
        wiki_url=[WIKI + "Ulmus_minor"], wiki_match=["own name, via box"]),
    doc(13, name=["Salvia greggii 'Flame'"], common_name=["Autumn sage"], flower_color=["Red/Burgundy"],
        attracts=["Hummingbirds"], source=["ncsu"], url=["https://plants.ces.ncsu.edu/plants/salvia-greggii-flame/"],
        zone_min=7, wiki_title=["Salvia greggii"], wiki_url=[WIKI + "Salvia_greggii"],
        wiki_match=["species of a cultivar or variety, via box"]),
    doc(14, name=["Clematis akebioides"], plant_type=["climber"], source=["tso"],
        url=[TSO + "clematis-akebioides-1/", TSO + "clematis-akebioides/"], wiki_title=["Clematis"],
        wiki_url=[WIKI + "Clematis"], wiki_match=["genus, via genus"]),
    doc(15, name=["Sorbus domestica"], soil=["Loam"], origin=["<i>Europe</i> & Asia Minor"],
        source=["pfaf"], url=["javascript:alert(1)"]),
    doc(16, name=["Guaiacum officinale"], common_name=["Lignum vitae"], plant_type=["Tree"], source=["wooddb"],
        janka=19510, density=1260, url=["https://www.wood-database.com/lignum-vitae/"]),
    doc(17, name=["Picea abies"], synonym=["Abies excelsa", "Pinus abies", "Abies picea", "Pinus excelsa",
                                           "Abies cinerea", "Pinus picea"],
        origin=["Mountains of " + "central and northern " * 8 + "Europe"], source=["tso"]),
]
WEB_DOCS = DOCS + EXTRA_DOCS

NAME_RE = re.compile(r'<span class="name">([^<]*)</span>')
TOTAL_RE = re.compile(r'<p class="summary"><b>([\d,]+)</b>')
MATCHED_RE = re.compile(r'<p class="matched">(.*?)</p>')
NONE_RE = re.compile(r'<p class="none">(.*?)</p>', re.DOTALL)
TIME_RE = re.compile(r"[\d.]+ ms")


@unittest.skipUnless(lucene, "PyLucene is not installed (run ./lucene_docker.sh unittest tests.test_lucene_web)")
class LuceneWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build.start_vm()
        cls.folder = tempfile.mkdtemp(prefix="vinf-lucene-web-")
        build.build_index(WEB_DOCS, cls.folder)
        cls.engine = web.Engine(cls.folder)
        # The expected error messages come from a searcher of its own: the engine's searchers belong to its worker.
        cls.searcher = search.Searcher(cls.folder)
        cls.server = web.make_server(cls.engine, "127.0.0.1", 0)
        cls.server.RequestHandlerClass = QuietHandler
        cls.url = "http://127.0.0.1:{}/".format(cls.server.server_address[1])
        # The server thread and its request threads are not attached to the JVM: the engine runs every
        # Lucene call on its own attached thread.
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.engine.close()
        cls.searcher.close()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def get(self, path="", base=None, **params):
        url = (base or self.url) + path + ("?" + urlencode(params) if params else "")
        try:
            with urlopen(url, timeout=30) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as error:
            with error:
                return error.code, error.read().decode("utf-8")

    def names(self, query, **options):
        status, body = self.get(q=query, **options)
        self.assertEqual(status, 200, body)
        return NAME_RE.findall(body)

    def cards(self, query, **options):
        """{plant name: HTML of its result card} of a query."""
        status, body = self.get(q=query, **options)
        self.assertEqual(status, 200, body)
        return {NAME_RE.search(card).group(1): card for card in body.split('<article class="hit">')[1:]}

    def quiet_get(self, **params):
        """(status, body, what the server wrote to stderr meanwhile)."""
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, body = self.get(**params)
        return status, body, errors.getvalue()

    def test_start_page_has_the_form_examples_and_fields(self):
        status, body = self.get()
        self.assertEqual(status, 200)
        self.assertIn('<input type="search" name="q" value=""', body)
        for name in ("top", "similarity", "operator"):
            self.assertIn('<select name="{}">'.format(name), body)
        for _kind, query, _note in web.EXAMPLES:
            self.assertIn("<code>{}</code>".format(web.escape(query)), body)
        self.assertIn("/?q=quercus+NOT+robur&amp;top=10&amp;similarity=bm25&amp;operator=or", body)
        for field in ("zone_min", "height_max_cm", "soil", "iucn", "wiki"):
            self.assertIn("<code>{}</code>".format(field), body)
        self.assertIn("<details class=\"help\" open>", body)
        self.assertEqual(NAME_RE.findall(body), [])

    def test_the_first_option_of_every_selector_is_the_default_of_the_core(self):
        self.assertEqual(web.form_values({}), {"q": "", "length": 0, "top": "10",
                                               "similarity": search.DEFAULT_SIMILARITY,
                                               "operator": search.DEFAULT_OPERATOR})
        _status, body = self.get()
        for name, default in (("top", "10"), ("similarity", search.DEFAULT_SIMILARITY),
                              ("operator", search.DEFAULT_OPERATOR)):
            self.assertRegex(body, '<select name="{}"><option value="{}" selected>'.format(name, default))
        self.assertEqual(set(web.SIMILARITY_CHOICES), set(search.SIMILARITIES))
        self.assertEqual(set(web.OPERATOR_CHOICES), set(search.OPERATORS))

    def test_every_example_returns_hits(self):
        self.assertGreaterEqual(len(web.EXAMPLES), 12)
        for _kind, query, _note in web.EXAMPLES:
            status, body = self.get(q=query)
            self.assertEqual(status, 200, query)
            self.assertGreater(len(NAME_RE.findall(body)), 0, query)

    def test_examples_do_what_they_say(self):
        examples = {query: (kind, note) for kind, query, note in web.EXAMPLES}
        self.assertIn("year:[1754 TO 1800] AND plant_type:tree", examples)
        self.assertIn("1754 to 1800", examples["year:[1754 TO 1800] AND plant_type:tree"][1])
        self.assertEqual(self.names("year:[1754 TO 1800] AND plant_type:tree"), ["Acer palmatum"])
        self.assertEqual(self.names("light:shade AND plant_type:shrub AND leaf:evergreen"), ["Kalmia latifolia"])
        self.assertEqual(self.names("tolerates:drought AND soil:clay AND plant_type:tree"), ["Ulmus minor"])
        self.assertEqual(self.names("iucn:(vu OR en OR cr) AND origin:europe"), ["Ulmus minor"])
        self.assertEqual(self.names("source:wooddb AND janka:[10000 TO *]"), ["Guaiacum officinale"])
        tag_examples = [query for query in examples
                        if len([field for field in documents.TAG_FIELDS if field + ":" in query]) >= 2]
        self.assertGreaterEqual(len(tag_examples), 2)
        for kind, _note in examples.values():
            self.assertNotRegex(kind, r"\bK\d|question")
        self.assertNotIn(",", web.PLACEHOLDER)
        self.assertNotIn("1753]", web.PLACEHOLDER)
        self.assertGreater(len(self.names(web.PLACEHOLDER)), 0)

    def test_help_explains_property_fields_and_source_values(self):
        _status, body = self.get()
        self.assertIn("free text searches the names, the descriptions and the Wikipedia lead only", body)
        for site in documents.SITES:
            self.assertIn(site, web.EXACT_HINTS["source"])
        self.assertIn("wooddb (Wood Database)", body)
        for code in documents.IUCN_CODES:
            self.assertRegex(web.EXACT_HINTS["iucn"], r"\b{}\b".format(code))
        self.assertIn("vu vulnerable", body)

    def test_site_names_come_from_the_site_list(self):
        self.assertEqual(set(web.SITE_LABELS), set(documents.SITES))
        for site, site_config in config.SITES.items():
            self.assertEqual(web.site_name(site_config.base_url + "/some/page/"), web.SITE_LABELS[site])
        self.assertEqual(web.site_name("https://example.org/x"), "example.org")

    def test_summary_names_the_similarity_and_the_operator(self):
        status, body = self.get(q="mountain laurel")
        self.assertEqual(status, 200)
        self.assertEqual(TOTAL_RE.findall(body), ["3"])
        self.assertRegex(body, r"3 shown &middot; [\d.]+ ms &middot; BM25 similarity &middot; default operator OR")
        self.assertNotIn("<details class=\"help\" open>", body)
        _status, body = self.get(q="oak", similarity="classic", operator="and")
        self.assertIn("classic tf-idf similarity &middot; default operator AND", body)
        self.assertIn('<option value="classic" selected>classic tf-idf</option>', body)

    def test_parsed_query_is_shown(self):
        _status, body = self.get(q='common_name:"mountain laurel"')
        self.assertIn('<pre class="parsed"><span class="label">parsed</span>'
                      '(common_name:&quot;mountain laurel&quot;)^0.3</pre>', body)

    def test_options_are_used_and_bad_values_fall_back(self):
        self.assertEqual(sorted(self.names("english oak")), ["Quercus alba", "Quercus robur"])
        self.assertEqual(self.names("english oak", operator="and"), ["Quercus robur"])
        _status, body = self.get(q="oak", similarity="classic", top="20")
        self.assertIn('<option value="classic" selected>', body)
        self.assertIn('<option value="20" selected>', body)
        status, body = self.get(q="oak", similarity="nope", operator="xor", top="7")
        self.assertEqual(status, 200)
        self.assertIn("BM25 similarity &middot; default operator OR", body)
        self.assertIn('<option value="10" selected>', body)

    def test_top_limits_the_hits_shown_not_the_total(self):
        self.assertGreater(len(WEB_DOCS), 10)
        for top, shown in (("10", 10), ("20", len(WEB_DOCS)), ("50", len(WEB_DOCS))):
            status, body = self.get(q="*:*", top=top)
            self.assertEqual(status, 200)
            self.assertEqual(len(NAME_RE.findall(body)), shown, top)
            self.assertEqual(TOTAL_RE.findall(body), [str(len(WEB_DOCS))], top)
            self.assertIn("{} shown".format(shown), body)

    def test_hit_card_shows_the_stored_values(self):
        status, body = self.get(q="id:1")
        self.assertEqual(status, 200)
        for text in ("Quercus robur", "L. (1753)", "English oak, Pedunculate oak", "Fagaceae &middot; Tree",
                     "zone 4–8", "height 35 m", "year 1753", "iucn LC", "density 675 kg/m³",
                     "janka 4,980 N", 'href="https://pfaf.org/x"', ">PFAF</a>", "Quercus robur</span>"):
            self.assertIn(text, body)
        self.assertRegex(body, r'<span class="score" title="score">\d+\.\d{4}</span>')

    def test_a_single_zone_is_shown_alone(self):
        card = self.cards("id:13")["Salvia greggii &#x27;Flame&#x27;"]
        self.assertIn("<li>zone 7</li>", card)
        self.assertNotIn("None", card)

    def test_matched_values_show_why_a_filter_matched(self):
        cards = self.cards("soil:clay AND origin:europe")
        self.assertEqual(sorted(cards), ["Quercus robur", "Ulmus minor"])
        self.assertEqual(MATCHED_RE.findall(cards["Quercus robur"]),
                         ['<span class="label">matched</span>soil: <b>Clay</b>, Loam &middot; origin: <b>Europe</b>'])
        self.assertIn("plant_type: <b>Tree</b>", self.cards("year:1784 AND plant_type:tree")["Acer palmatum"])
        self.assertIn("year: <b>1784</b>", self.cards("year:1784")["Acer palmatum"])
        # A field that is not stored (text) shows nothing; free text found in the name adds nothing.
        self.assertEqual(MATCHED_RE.findall(self.cards('text:"drought tolerant"~3')["Ulmus minor"]), [])
        self.assertEqual(MATCHED_RE.findall(self.cards("quercus")["Quercus robur"]), [])

    def test_matched_values_show_the_synonym_a_hit_was_found_by(self):
        cards = self.cards("pedunculata")
        self.assertEqual(list(cards), ["Quercus robur"])
        self.assertIn("synonym: <b>Quercus pedunculata</b>", cards["Quercus robur"])

    def test_matched_values_are_escaped_and_cut(self):
        card = self.cards("origin:asia")["Sorbus domestica"]
        self.assertIn("origin: <b>&lt;i&gt;Europe&lt;/i&gt; &amp; Asia Minor</b>", card)
        self.assertNotIn("<i>", card)
        card = self.cards("synonym:picea")["Picea abies"]
        self.assertIn('synonym: <b>Abies picea</b>, <b>Pinus picea</b>, Abies excelsa, Pinus abies '
                      '<span class="more">+2 more</span>', card)
        line = MATCHED_RE.findall(self.cards("origin:europe")["Picea abies"])[0]
        self.assertIn("Europe</b>", line)
        self.assertLess(len(re.sub(r"<[^>]+>", "", line)), web.MATCHED_WIDTH + 30)

    def test_wildcards_with_many_stars_are_highlighted_in_well_under_a_second(self):
        # A regex with one \w* per star tries every split of a word among the stars: about 3 s for 16 stars
        # on Atropurpureum, minutes for 24, and the regex holds the interpreter lock all that time.
        named = {"name": ["Acer palmatum 'Atropurpureum'"]}
        hit = {"name": ["Acer palmatum 'Atropurpureum'"], "common_name": ["Japanese maple"],
               "synonym": ["Acer atropurpureum", "Acer " + "a" * 60, "aaaaam " * 30 + "y", "a " + "- " * 40 + "y"],
               "origin": ["Atropurpureum " * 200]}
        queries = ["a" + "*" * 40 + "s", "a*b*c*d*e*f*g*h*i*j*k*l*m*n*o*p*s", "a*a*s", "a" + "?" * 40 + "s",
                   "a" + "*?" * 20 + "s", '"acer a*t*r*o*p*u*r*p*u*r*e*u*m"', '"a*a*m a*a*m a*a*m a*a*m a*a*m x"',
                   '"a ' + "- " * 15 + 'x"', '"a ' + "? " * 15 + 'x"',
                   "synonym:a" + "*" * 40 + "s", "synonym:a*a*s", "origin:a*u*s",
                   "origin:a*b*c*d*e*f*g*h*i*j*k*l*m*n*o*p*s OR origin:a" + "*" * 40 + "s",
                   " ".join("q*u*e*r*c*u*s{}".format(number) for number in range(30))]
        for case, query in [(named, "a" + "*" * 16 + "s")] + [(hit, query) for query in queries]:
            started = time.perf_counter()
            web.matched_values(case, query)
            self.assertLess(time.perf_counter() - started, 0.2, query)
        # Runs of stars are one star, so the long run still marks the matching value.
        shown, _left_out = web.matched_values(hit, "synonym:a" + "*" * 40 + "m")[0][1:]
        self.assertEqual(shown[0], ("Acer atropurpureum", True))
        self.assertTrue(web.matched_values(hit, "synonym:a?r*u*m")[0][1][0][1])
        # More stars than that are not highlighted: the values are shown, none in bold.
        shown, _left_out = web.matched_values(hit, "synonym:a*t*r*o*m")[0][1:]
        self.assertEqual([matched for _text, matched in shown], [False] * 4)

    def test_a_query_with_many_stars_gets_a_prompt_answer(self):
        for query in ("antarctica a" + "*" * 40 + "s", "antarctica a*b*c*d*e*f*g*h*i*j*k*l*m*n*o*p*s"):
            started = time.perf_counter()
            status, body = self.get(q=query, top="50")
            self.assertLess(time.perf_counter() - started, 2, query)
            self.assertEqual(status, 200)
            self.assertIn("Nothofagus antarctica", NAME_RE.findall(body))

    def test_two_pages_of_one_site_get_different_labels(self):
        card = self.cards("id:14")["Clematis akebioides"]
        self.assertIn('href="{}clematis-akebioides-1/"'.format(TSO), card)
        self.assertRegex(card, r">TSO 1</a> <a [^>]*>TSO 2</a>")
        self.assertIn(">NCSU</a>", self.cards("id:13")["Salvia greggii &#x27;Flame&#x27;"])

    def test_a_url_that_is_not_http_is_no_link(self):
        card = self.cards("id:15")["Sorbus domestica"]
        self.assertNotIn('href="javascript', card)
        self.assertIn("javascript:alert(1)", card)

    def test_wikipedia_link_and_what_the_article_is_about(self):
        for doc_id, name, title, label in (
                ("12", "Ulmus minor", "Ulmus_minor", "article about this plant"),
                ("13", "Salvia greggii &#x27;Flame&#x27;", "Salvia_greggii", "article about its species"),
                ("14", "Clematis akebioides", "Clematis", "article about its genus")):
            card = self.cards("id:" + doc_id)[name]
            self.assertRegex(card, r'<a href="{}{}" [^>]*>[^<]+</a> <span class="match">\({}\)</span>'.format(
                re.escape(WIKI), title, label))
            self.assertNotIn(", via ", card)
            self.assertNotIn("own name", card)

    def test_no_hits_hint_names_and_only_when_it_is_used(self):
        status, body = self.get(q="name:nothinglikethis")
        self.assertEqual(status, 200)
        self.assertEqual(TOTAL_RE.findall(body), ["0"])
        hint = NONE_RE.findall(body)[0]
        self.assertNotIn("AND", hint)
        self.assertIn("<code>plant_type:tree</code>, not <code>plant_type:trees</code>", hint)
        for params in ({"q": "plant_type:trees AND soil:clay"}, {"q": "nothinglikethis", "operator": "and"}):
            _status, body = self.get(**params)
            self.assertIn("OR instead of AND", NONE_RE.findall(body)[0], params)

    def test_notes_of_a_query_that_may_surprise(self):
        # The wording belongs to querycheck: the page has to show every notice of it, escaped.
        for query in ("quercus not robur", "NOT robur"):
            notes = querycheck.notes(query)
            self.assertTrue(notes, query)
            status, body = self.get(q=query)
            self.assertEqual(status, 200, query)
            self.assertIn('<ul class="notes">{}</ul>'.format("".join(
                "<li>{}</li>".format(web.escape(note)) for note in notes)), body)
        self.assertEqual(TOTAL_RE.findall(body), ["0"])
        _status, body = self.get(q="quercus NOT robur")
        self.assertNotIn('class="notes"', body)

    def test_query_errors_are_400_with_the_explanation(self):
        # The wording belongs to lucene_index.search: the page has to show its explanation and Lucene's message.
        with_lucene_message = 0
        for query in ("year:[1700 TO", '"unclosed', "year:abc", "(quercus", "*ercus", "color:red", "NAME:robur",
                      "url:pfaf", "year:[1700 to 1753]"):
            status, body, errors = self.quiet_get(q=query)
            self.assertEqual(status, 400, query)
            with self.assertRaises(search.QueryError) as caught:
                self.searcher.search(query)
            self.assertIn('<p class="explanation">{}</p>'.format(web.escape(caught.exception.explanation)), body)
            if caught.exception.lucene_message:
                with_lucene_message += 1
                self.assertIn("<pre>Lucene: {}</pre>".format(web.escape(caught.exception.lucene_message)), body)
            self.assertEqual(errors, "", query)
            self.assertIn('<details class="help" open>', body)
            self.assertIn('value="{}"'.format(web.escape(query)), body)
        self.assertGreater(with_lucene_message, 0)
        # The worker is still alive after the errors.
        self.assertEqual(self.names("quercus NOT robur"), ["Quercus alba"])

    def test_an_unexpected_java_error_is_500_and_logged(self):
        broken = web.Engine(self.folder)
        try:
            broken.searchers[search.DEFAULT_SIMILARITY, search.DEFAULT_OPERATOR].close()
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status, body = web.search_page(broken, web.form_values({"q": ["oak"]}))
            self.assertEqual(status, 500)
            # The page says in plain words what happened; the Java message goes to the log only.
            self.assertIn("<b>The search failed</b>", body)
            self.assertIn('<p class="explanation">{}</p>'.format(web.escape(web.INTERNAL_ERROR)), body)
            self.assertIn("log of the server", web.INTERNAL_ERROR)
            for java in ("AlreadyClosedException", "org.apache", "IndexReader"):
                self.assertNotIn(java, body)
            log = errors.getvalue()
            self.assertEqual(len(log.strip().splitlines()), 1, log)
            self.assertIn("'oak'", log)
            self.assertIn("org.apache.lucene.store.AlreadyClosedException", log)
        finally:
            broken.close()

    def test_an_error_outside_the_engine_is_500_and_logged(self):
        class BrokenEngine:
            documents, index_dir = 0, "nowhere"

            def search(self, *args):
                raise RuntimeError("the engine is broken")

        server = web.make_server(BrokenEngine(), "127.0.0.1", 0)
        server.RequestHandlerClass = QuietHandler
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status, body = self.get(base="http://127.0.0.1:{}/".format(server.server_address[1]), q="oak")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(status, 500)
        self.assertIn(web.escape(web.INTERNAL_ERROR), body)
        self.assertNotIn("the engine is broken", body)
        self.assertIn("RuntimeError: the engine is broken", errors.getvalue())
        self.assertIn("Traceback", errors.getvalue())

    def test_query_is_escaped(self):
        status, body = self.get(q="<script>alert('x')</script>")
        self.assertEqual(status, 400)
        self.assertNotIn("<script", body)
        self.assertIn('value="&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"', body)
        status, body = self.get(q='"mountain laurel"')
        self.assertIn('value="&quot;mountain laurel&quot;"', body)
        self.assertIn("&lt;script&gt;", web.render_page(self.engine, web.form_values({"q": ["<script>"]})))

    def test_control_characters_are_removed(self):
        status, body = self.get(q="\x00oak\x07")
        self.assertEqual(status, 200)
        self.assertNotIn("\x00", body)
        self.assertNotIn("\x07", body)
        self.assertIn('value="oak"', body)
        self.assertEqual(web.form_values({"q": ["quercus\tNOT\nrobur\x1b"]})["q"], "quercus NOT robur")

    def test_a_long_query_is_refused_and_not_echoed(self):
        long_query = "oak " * 499 + "oaks"
        self.assertEqual(len(long_query), 2000)
        status, body = self.get(q=long_query)
        self.assertEqual(status, 400)
        self.assertIn("The query is too long", body)
        self.assertIn("2,000 characters", body)
        self.assertNotIn(long_query, body)
        self.assertLess(len(body), len(self.get()[1]) + 2 * web.MAX_QUERY_LENGTH)
        longest = "quercus" + " " * (web.MAX_QUERY_LENGTH - 16) + "AND robur"
        self.assertEqual(len(longest), web.MAX_QUERY_LENGTH)
        self.assertEqual(self.names(longest), ["Quercus robur"])

    def test_parallel_requests_give_equal_answers(self):
        queries = ["quercus NOT robur", "soil:clay", "querc*", "color:red", "year:[1754 TO 1800]"]
        expected = {query: TIME_RE.sub("", self.get(q=query)[1]) for query in queries}
        with ThreadPoolExecutor(max_workers=20) as pool:
            answers = list(pool.map(lambda query: (query, self.get(q=query)), queries * 4))
        self.assertEqual(len(answers), 20)
        for query, (status, body) in answers:
            self.assertIn(status, (200, 400))
            self.assertEqual(TIME_RE.sub("", body), expected[query], query)

    def test_unknown_path_is_404(self):
        status, body = self.get("favicon.ico")
        self.assertEqual(status, 404)
        self.assertIn("No page at /favicon.ico", body)

    def test_engine_returns_plain_python_values(self):
        result = self.engine.search("name:quercus", 5)
        self.assertEqual(result["total"], 2)
        self.assertIs(type(result["parsed"]), str)
        self.assertEqual(result["parsed"], "(name:quercus)^0.4")
        self.assertEqual(sorted(hit["name"][0] for hit in result["hits"]), ["Quercus alba", "Quercus robur"])

        def plain(value):
            if isinstance(value, list):
                return all(isinstance(item, str) for item in value)
            return value is None or type(value) in (int, float, str)

        for hit in result["hits"]:
            for field, value in hit.items():
                self.assertTrue(plain(value), (field, type(value)))

    def test_start_without_an_index_names_the_build_command(self):
        scratch = tempfile.mkdtemp(prefix="vinf-lucene-web-empty-")
        self.addCleanup(shutil.rmtree, scratch, True)
        for folder in (scratch, os.path.join(scratch, "missing")):
            code, output, errors = run_main(web.main, ["--index", folder, "--port", "0"])
            self.assertEqual(code, 2, errors)
            self.assertEqual(output, "")
            self.assertEqual(len(errors.strip().splitlines()), 1, errors)
            self.assertIn(folder, errors)
            self.assertIn(build.BUILD_COMMAND, errors)


if __name__ == "__main__":
    unittest.main()
