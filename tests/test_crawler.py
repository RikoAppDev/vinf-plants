"""Offline tests of the crawl loop, frontier, storage and robots.txt handling.

No network: requests.Session is replaced by FakeSession, time.sleep by a
no-op, and all state is written to a temporary directory (never data/).
"""

import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

import requests
from requests.structures import CaseInsensitiveDict

from crawler import config, crawl
from crawler.frontier import Frontier
from crawler.robots import RobotsRules
from crawler.storage import LOG_COLUMNS, Storage

BASE = "https://example.org"
SITEMAP = BASE + "/sitemap.xml"
ROBOTS = BASE + "/robots.txt"
CHALLENGE_HTML = "<html><head><title>One moment, please...</title></head><body></body></html>"

TEST_SITE = config.SiteConfig(
    name="test",
    base_url=BASE,
    sitemaps=(SITEMAP,),
    seeds=(),
    allow=re.compile(r"^https://example\.org/p/[a-z]+/$"),
    allow_aliases=re.compile(r"^https://example\.org/p/[a-z]+/$"),
    relevant=re.compile(r"^https://example\.org/p/[a-z]+/$"),
    delay_s=0.0,
    follow_links=False,
)


def page(name):
    return BASE + "/p/{}/".format(name)


class FakeResponse:
    def __init__(self, status=200, text="", content_type="text/html; charset=utf-8", url=None, headers=None):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.headers = CaseInsensitiveDict({"Content-Type": content_type, **(headers or {})})
        self.elapsed = timedelta(milliseconds=5)


def sitemap(*urls):
    locs = "".join("<url><loc>{}</loc></url>".format(url) for url in urls)
    return FakeResponse(text='<?xml version="1.0"?><urlset>{}</urlset>'.format(locs), content_type="text/xml")


class FakeSession:
    """Answers by URL. A value is a response, an exception, or a list of them
    (one per call, the last one repeats)."""

    def __init__(self, answers):
        self.answers = answers
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        answer = self.answers.get(url, FakeResponse(404, "not found"))
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, Exception):
            raise answer
        if answer.url is None:
            answer.url = url
        return answer


def read_log(data_dir):
    with open(os.path.join(data_dir, "state", "test", "crawl_log.tsv"), encoding="utf-8") as handle:
        next(handle)
        return [dict(zip(LOG_COLUMNS, line.rstrip("\n").split("\t"))) for line in handle]


class CrawlTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.sleeps = []
        patches = [
            mock.patch.dict(config.SITES, {"test": TEST_SITE}),
            mock.patch.object(crawl.time, "sleep", self.sleeps.append),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_crawl(self, answers, **kwargs):
        session = FakeSession(answers)
        output = io.StringIO()
        with mock.patch.object(crawl.requests, "Session", return_value=session), contextlib.redirect_stdout(output):
            crawl.crawl("test", self.data_dir, kwargs.get("max_pages"), False, kwargs.get("reseed", False))
        return session, output.getvalue()

    def raw_files(self):
        return sorted(os.listdir(os.path.join(self.data_dir, "raw", "test")))


class FrontierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "state", "discovered.tsv")

    def test_added_url_is_on_disk_before_close(self):
        frontier = Frontier(self.path, set())
        frontier.add(page("a"), 1, SITEMAP)
        with open(self.path, encoding="utf-8") as handle:  # as seen after a kill -9
            self.assertEqual(handle.read(), "{}\t1\t{}\n".format(page("a"), SITEMAP))
        frontier.close()

    def test_truncated_last_line_is_skipped_and_not_glued_to_the_next_url(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{}\t1\t\nhttps://example.org/p/b".format(page("a")))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            frontier = Frontier(self.path, set())
        self.assertIn("malformed", output.getvalue())
        self.assertEqual(frontier.pop(), (page("a"), 1, ""))
        self.assertIsNone(frontier.pop())
        self.assertTrue(frontier.add(page("b"), 1, ""))  # the cut URL can be discovered again
        frontier.close()
        with contextlib.redirect_stdout(io.StringIO()):
            reloaded = Frontier(self.path, {page("a")})
        self.assertEqual(reloaded.pop(), (page("b"), 1, ""))
        reloaded.close()

    def test_fetched_urls_are_known_but_not_queued(self):
        frontier = Frontier(self.path, set())
        frontier.add(page("a"), 1, "")
        frontier.add(page("b"), 1, "")
        frontier.close()
        resumed = Frontier(self.path, {page("a")})
        self.assertIn(page("a"), resumed)
        self.assertEqual(len(resumed), 1)
        self.assertFalse(resumed.add(page("a"), 1, ""))
        resumed.close()


class FetchedUrlsTest(unittest.TestCase):
    """Resume: final answers are skipped, transient ones are fetched again."""

    STATUSES = {
        "200": True, "404": True, "410": True, "400": True,
        "redirect-duplicate": True, "redirect-outside": True,
        "401": False, "403": False, "429": False, "500": False, "503": False,
        "": False, "challenge": False, "robots": False,
    }

    def test_only_final_statuses_count_as_fetched(self):
        with tempfile.TemporaryDirectory() as data_dir:
            storage = Storage(data_dir, "test")
            for status in self.STATUSES:
                storage.log(url="https://example.org/s/{}".format(status or "timeout"), status=status)
            storage.close()
            storage = Storage(data_dir, "test")
            fetched = storage.fetched_urls()
            storage.close()
        for status, final in self.STATUSES.items():
            url = "https://example.org/s/{}".format(status or "timeout")
            self.assertEqual(url in fetched, final, status or "empty status (timeout)")


class RetryWaitTest(unittest.TestCase):
    def test_huge_retry_after_is_capped(self):
        response = FakeResponse(429, headers={"Retry-After": "86400"})
        self.assertEqual(crawl.retry_wait_seconds(response, 1), config.MAX_RETRY_AFTER_S)

    def test_small_retry_after_is_used(self):
        self.assertEqual(crawl.retry_wait_seconds(FakeResponse(503, headers={"Retry-After": "7"}), 1), 7.0)

    def test_http_date_retry_after_is_understood_and_capped(self):
        response = FakeResponse(429, headers={"Retry-After": "Fri, 31 Dec 2100 23:59:59 GMT"})
        self.assertEqual(crawl.retry_wait_seconds(response, 1), config.MAX_RETRY_AFTER_S)

    def test_backoff_without_header(self):
        self.assertEqual(crawl.retry_wait_seconds(None, 1), 5.0)
        self.assertEqual(crawl.retry_wait_seconds(FakeResponse(500, headers={"Retry-After": "soon"}), 2), 10.0)

    def test_fetch_never_sleeps_longer_than_the_cap(self):
        session = FakeSession({page("a"): FakeResponse(429, headers={"Retry-After": "86400"})})
        sleeps = []
        with mock.patch.object(crawl.time, "sleep", sleeps.append), contextlib.redirect_stdout(io.StringIO()):
            response, attempts, error = crawl.fetch(session, page("a"))
        self.assertEqual((response.status_code, attempts, error), (429, 3, "HTTP 429"))
        self.assertEqual(sleeps, [config.MAX_RETRY_AFTER_S] * 2)


class RobotsTest(unittest.TestCase):
    def rules(self, answer):
        return RobotsRules(FakeSession({ROBOTS: answer}), BASE, config.ROBOTS_AGENT, (1, 1))

    def test_server_error_429_and_network_error_disallow_everything(self):
        for answer in (FakeResponse(500), FakeResponse(503), FakeResponse(429), requests.ConnectionError()):
            rules = self.rules(answer)
            self.assertFalse(rules.allowed(page("a")), answer)
            self.assertIn("RFC 9309", rules.problem)

    def test_missing_or_forbidden_robots_txt_allows_everything(self):
        for status in (404, 410, 401, 403):
            rules = self.rules(FakeResponse(status))
            self.assertTrue(rules.allowed(page("a")), status)
            self.assertEqual(rules.problem, "")

    def test_html_instead_of_robots_txt_is_a_challenge(self):
        rules = self.rules(FakeResponse(200, CHALLENGE_HTML))
        self.assertTrue(rules.challenge)
        self.assertFalse(rules.allowed(page("a")))

    def test_rules_and_crawl_delay_are_parsed(self):
        rules = self.rules(FakeResponse(200, "User-agent: *\nDisallow: /p/secret/\nCrawl-delay: 5\n", "text/plain"))
        self.assertTrue(rules.allowed(page("a")))
        self.assertFalse(rules.allowed(page("secret")))
        self.assertEqual(rules.crawl_delay(), 5.0)

    def test_group_for_our_crawler_wins_over_the_wildcard(self):
        robots_txt = "User-agent: VINF-FIIT-STU-crawler\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
        self.assertFalse(self.rules(FakeResponse(200, robots_txt, "text/plain")).allowed(page("a")))

    def test_user_agent_is_a_browser_that_names_the_crawler(self):
        self.assertTrue(config.USER_AGENT.startswith("Mozilla/5.0 ("))
        self.assertIn(config.ROBOTS_AGENT + "/0.1", config.USER_AGENT)


class PfafUrlRulesTest(unittest.TestCase):
    SITE = config.SITES["pfaf"]
    CANONICAL = "https://pfaf.org/user/Plant.aspx?LatinName=Acer+rubrum"

    def test_every_case_variant_maps_to_one_url(self):
        for url in ("https://pfaf.org/user/Plant.aspx?LatinName=Acer+rubrum",
                    "https://pfaf.org/User/Plant.aspx?LatinName=Acer+rubrum",
                    "https://pfaf.org/user/plant.aspx?latinname=Acer+rubrum",
                    "https://pfaf.org/user/plant.aspx?LatinName=Acer+rubrum",
                    "https://pfaf.org/User/plant.aspx?LatinName=Acer+rubrum",
                    "https://pfaf.org/User/plant.aspx?latinname=Acer+rubrum"):
            self.assertEqual(crawl.canonicalize(self.SITE, url), self.CANONICAL, url)

    def test_escaped_apostrophe_is_unified(self):
        url = "https://pfaf.org/User/plant.aspx?latinname=Fragaria+vesca+%27Semperflorens%27"
        self.assertEqual(crawl.canonicalize(self.SITE, url),
                         "https://pfaf.org/user/Plant.aspx?LatinName=Fragaria+vesca+'Semperflorens'")

    def test_real_plant_names_are_allowed(self):
        for name in ("Acer+rubrum", "Berberis+x+lologensis", "Rhododendron+'PJM'",
                     "Cimicifuga+racemosa+(Actaea+racemosa)", "Dryopteris+felix-mas", "Allium"):
            self.assertTrue(self.SITE.allow.match("https://pfaf.org/user/Plant.aspx?LatinName=" + name), name)

    def test_test_entries_and_other_pages_are_rejected(self):
        for name in ("harishtest", "test1234abc", "abc", "Tesing-Testing3", "Tesing-Testing+Botanic",
                     "Test_20170320_2", "Acer+rubrum&x=1"):
            self.assertFalse(self.SITE.allow.match("https://pfaf.org/user/Plant.aspx?LatinName=" + name), name)
        self.assertFalse(self.SITE.allow.match("https://pfaf.org/user/search_name.aspx?family=Aceraceae"))


class SeedingTest(CrawlTestCase):
    def test_challenge_instead_of_sitemap_is_not_stored_and_stops_the_run(self):
        _session, output = self.run_crawl({ROBOTS: FakeResponse(404), SITEMAP: FakeResponse(200, CHALLENGE_HTML)})
        log = read_log(self.data_dir)
        self.assertEqual([(row["url"], row["status"]) for row in log], [(ROBOTS, "404"), (SITEMAP, "challenge")])
        self.assertEqual(self.raw_files(), [])
        self.assertNotIn("crawl finished", output)
        self.assertIn("challenge", output)

    def test_challenge_sitemap_with_503_also_stops_the_run(self):
        _session, output = self.run_crawl({ROBOTS: FakeResponse(404), SITEMAP: FakeResponse(503, CHALLENGE_HTML)})
        self.assertEqual(read_log(self.data_dir)[-1]["status"], "challenge")
        self.assertNotIn("crawl finished", output)

    def test_html_page_instead_of_sitemap_is_treated_like_a_challenge(self):
        _session, output = self.run_crawl({ROBOTS: FakeResponse(404), SITEMAP: FakeResponse(200, "<html>Home</html>")})
        self.assertEqual(read_log(self.data_dir)[-1]["status"], "challenge")
        self.assertNotIn("crawl finished", output)

    def test_unavailable_robots_txt_stops_before_any_other_request(self):
        session, output = self.run_crawl({ROBOTS: FakeResponse(503), SITEMAP: sitemap(page("a"))})
        self.assertEqual(session.calls, [ROBOTS])
        self.assertEqual([row["status"] for row in read_log(self.data_dir)], ["503"])
        self.assertIn("RFC 9309", output)

    def test_robots_txt_copy_is_kept(self):
        robots_txt = "User-agent: *\nDisallow: /private/\n"
        self.run_crawl({ROBOTS: FakeResponse(200, robots_txt, "text/plain"), SITEMAP: sitemap(page("a")),
                        page("a"): FakeResponse(200, "<html>a</html>")})
        with open(os.path.join(self.data_dir, "state", "test", "robots.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), robots_txt)

    def test_reseed_queues_only_new_sitemap_urls(self):
        pages = {page(name): FakeResponse(200, "<html>{}</html>".format(name)) for name in "abc"}
        self.run_crawl({SITEMAP: sitemap(page("a")), **pages})
        session, _ = self.run_crawl({SITEMAP: sitemap(page("a"), page("b")), **pages})
        self.assertEqual(session.calls, [ROBOTS])  # without --reseed the sitemap is not read again
        session, output = self.run_crawl({SITEMAP: sitemap(page("a"), page("b")), **pages}, reseed=True)
        self.assertEqual(session.calls, [ROBOTS, SITEMAP, page("b")])
        self.assertIn("1 new URLs queued", output)
        self.assertEqual(sum(name.startswith("sitemap.xml") for name in self.raw_files()), 2)  # first copy kept


class CrawlLoopTest(CrawlTestCase):
    def prepare_state(self, rows):
        """discovered.tsv + crawl_log.tsv as left by an earlier run."""
        storage = Storage(self.data_dir, "test")
        frontier = Frontier(storage.discovered_path, set())
        for url, status in rows:
            frontier.add(url, 1, SITEMAP)
            storage.log(url=url, status=status, attempts=3)
        frontier.close()
        storage.close()

    def test_resume_retries_transient_failures_only(self):
        self.prepare_state([(page("ok"), "200"), (page("gone"), "404"), (page("dup"), "redirect-duplicate"),
                            (page("limited"), "429"), (page("down"), "503"), (page("timeout"), ""),
                            (page("forbidden"), "403")])
        session, _ = self.run_crawl({name: FakeResponse(200, "<html></html>") for name in
                                     (page("limited"), page("down"), page("timeout"), page("forbidden"))})
        self.assertEqual(session.calls, [ROBOTS, page("limited"), page("down"), page("timeout"), page("forbidden")])

    def test_redirects_never_store_a_second_copy(self):
        answers = {
            SITEMAP: sitemap(page("old"), page("new"), page("away"), page("moved")),
            page("old"): FakeResponse(200, "<html>new</html>", url=page("new")),
            page("new"): FakeResponse(200, "<html>new</html>"),
            page("away"): FakeResponse(200, "<html>shop</html>", url=BASE + "/shop/"),
            page("moved"): FakeResponse(200, "<html>target</html>", url=page("target")),
            page("target"): FakeResponse(200, "<html>target</html>"),
        }
        session, _ = self.run_crawl(answers)
        statuses = {row["url"]: (row["status"], row["final_url"], row["file"]) for row in read_log(self.data_dir)}
        self.assertEqual(statuses[page("old")], ("redirect-duplicate", page("new"), ""))
        self.assertEqual(statuses[page("away")], ("redirect-outside", BASE + "/shop/", ""))
        self.assertEqual(statuses[page("moved")], ("redirect-duplicate", page("target"), ""))
        self.assertEqual(statuses[page("new")][0], "200")
        self.assertEqual(statuses[page("target")][0], "200")  # unknown target was queued and stored once
        self.assertEqual(session.calls.count(page("new")), 1)
        self.assertEqual(len(self.raw_files()), 3)  # sitemap + new + target

    def test_repeated_503_stops_the_crawl(self):
        answers = {SITEMAP: sitemap(page("a"), page("b"), page("c"), page("d")),
                   **{page(name): FakeResponse(503, headers={"Retry-After": "86400"}) for name in "abcd"}}
        session, output = self.run_crawl(answers)
        # 3 attempts per URL count as 3 blocks: the 5-block limit is hit on the 2nd URL.
        self.assertEqual(session.calls[2:], [page("a")] * 3 + [page("b")] * 3)
        self.assertIn("blocked responses in a row", output)
        self.assertLessEqual(max(self.sleeps), config.MAX_RETRY_AFTER_S)

    def test_challenge_with_403_stops_and_is_not_final(self):
        answers = {SITEMAP: sitemap(page("a"), page("b")), page("a"): FakeResponse(403, CHALLENGE_HTML)}
        session, _output = self.run_crawl(answers)
        self.assertNotIn(page("b"), session.calls)
        self.assertEqual(read_log(self.data_dir)[-1]["status"], "challenge")
        storage = Storage(self.data_dir, "test")
        self.assertNotIn(page("a"), storage.fetched_urls())
        storage.close()


if __name__ == "__main__":
    unittest.main()
