"""Static configuration: HTTP behaviour and per-site crawl rules.

Every value here has to be justified on the course wiki (headers, timeouts,
sleeps), so the reasoning is kept next to the value.
"""

import os
import re
from dataclasses import dataclass

# Optional contact (from the environment, never hard-coded) so a site admin can reach us instead of blocking us.
CONTACT = os.environ.get("VINF_CRAWLER_CONTACT", "").strip()

# Our own product token: robots.txt groups are matched against it and it stays visible in the User-Agent.
ROBOTS_AGENT = "VINF-FIIT-STU-crawler"

# A regular browser User-Agent (Chrome on macOS) followed by our token, so the crawler is still identifiable.
BROWSER_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
USER_AGENT = "{} {}/0.1 (academic student project; information retrieval course{})".format(
    BROWSER_USER_AGENT, ROBOTS_AGENT, "; contact: " + CONTACT if CONTACT else ""
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    # HTML pages, XML sitemaps and plain-text robots.txt; PFAF answers 406 unless text/plain is listed.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1",
    # All target sites are English; avoids localized variants of a page.
    "Accept-Language": "en",
    # gzip keeps the transfer small for the server; requests decompresses it.
    "Accept-Encoding": "gzip, deflate",
}

# Pages (60-180 kB) arrive in ~1.5 s, so a 30 s read timeout fires only when the server is stuck.
CONNECT_TIMEOUT_S = 10
READ_TIMEOUT_S = 30

# Markers of an anti-bot challenge page served with HTTP 200 instead of content.
CHALLENGE_MARKERS = ("<title>One moment, please...</title>", "<title>Just a moment...</title>")

# Transient failures (network error, 429, 5xx): exponential backoff 5, 10, 20 s; a Retry-After header wins.
MAX_RETRIES = 3
BACKOFF_BASE_S = 5.0

# Cap for one Retry-After wait (5 min, 30x even our longest delay). A server asking for hours is blocking us,
# and MAX_CONSECUTIVE_BLOCKS stops the crawl instead of sleeping for days.
MAX_RETRY_AFTER_S = 300.0

# 403/429/503 this many times in a row (retries included) means we are blocked: stop, do not hammer.
MAX_CONSECUTIVE_BLOCKS = 5

# Random extra sleep (0..JITTER_S) so requests do not arrive in a fixed rhythm.
JITTER_S = 0.5


@dataclass(frozen=True)
class SiteConfig:
    name: str
    base_url: str
    sitemaps: tuple        # sitemap URLs used as seeds
    seeds: tuple           # extra start URLs
    allow: re.Pattern      # URLs we are willing to download
    allow_aliases: re.Pattern  # wider pattern used with --include-aliases
    relevant: re.Pattern   # URLs that are entity (plant) pages, used in statistics
    delay_s: float         # minimal pause between two requests to this host
    follow_links: bool = True   # False: crawl only the sitemap URLs (entity lists are complete)
    canonical: tuple = ()       # (pattern, replacement) pairs that map duplicate URL spellings to one


_NCSU = "https://plants.ces.ncsu.edu"

SITES = {
    # NC State Extension Gardener Plant Toolbox. robots.txt is 404 (no rules), so 1 request/s is our own pace.
    "ncsu": SiteConfig(
        name="ncsu",
        base_url=_NCSU,
        sitemaps=(_NCSU + "/sitemap.xml",),
        seeds=(),
        # Plant pages only: faceted search (/find_a_plant/?tag=...) is a crawler trap with no new entities.
        allow=re.compile(r"^https://plants\.ces\.ncsu\.edu/plants/[a-z0-9-]+/$"),
        # /common-name/ pages are near-duplicates (same plant, other heading), so they are opt-in.
        allow_aliases=re.compile(r"^https://plants\.ces\.ncsu\.edu/plants/[a-z0-9-]+/(common-name/[a-z0-9-]+/)?$"),
        relevant=re.compile(r"^https://plants\.ces\.ncsu\.edu/plants/[a-z0-9-]+/$"),
        delay_s=1.0,
    ),
    # Plants For A Future. robots.txt allows / except a few service pages, no Crawl-delay; the operator
    # asks to be notified; text is CC BY 4.0. The sitemap lists most plants in several letter cases of
    # "User/plant.aspx?latinname=" (the ASP.NET server ignores case), so they are canonicalised to one URL.
    # A name must start with a capitalised genus ("Acer+rubrum"), which keeps out sitemap test entries
    # ("harishtest", "abc"). The name's own case is kept ("Apios+americana" vs "Apios+Americana"):
    # lowercasing could merge different cultivars; such rare duplicates are merged by the extracted name.
    "pfaf": SiteConfig(
        name="pfaf",
        base_url="https://pfaf.org",
        sitemaps=("https://pfaf.org/sitemap.xml",),
        seeds=(),
        allow=re.compile(r"^https://pfaf\.org/user/Plant\.aspx\?LatinName=[A-Z][a-z]+(\+[^&#]*)?$"),
        allow_aliases=re.compile(r"^https://pfaf\.org/user/Plant\.aspx\?LatinName=[A-Z][a-z]+(\+[^&#]*)?$"),
        relevant=re.compile(r"^https://pfaf\.org/user/Plant\.aspx\?LatinName=[A-Z][a-z]+(\+[^&#]*)?$"),
        delay_s=4.0,
        follow_links=False,
        canonical=(
            (r"(?i)^https://pfaf\.org/user/plant\.aspx\?latinname=", "https://pfaf.org/user/Plant.aspx?LatinName="),
            # One cultivar is listed both with ' and with its escaped form %27.
            (r"%27", "'"),
        ),
    ),
    # The Wood Database. robots.txt: "Crawl-delay: 5" (we use 6 s). The post sitemap lists only species pages.
    "wooddb": SiteConfig(
        name="wooddb",
        base_url="https://www.wood-database.com",
        sitemaps=("https://www.wood-database.com/post-sitemap.xml",),
        seeds=(),
        allow=re.compile(r"^https://www\.wood-database\.com/[a-z0-9-]+/$"),
        allow_aliases=re.compile(r"^https://www\.wood-database\.com/[a-z0-9-]+/$"),
        relevant=re.compile(r"^https://www\.wood-database\.com/[a-z0-9-]+/$"),
        delay_s=6.0,
        follow_links=False,
    ),
    # Trees and Shrubs Online (International Dendrology Society). No robots.txt, CC BY-SA 4.0.
    # The host shows a JS challenge to suspicious traffic: go slowly (10 s), stop at the first challenge.
    "tso": SiteConfig(
        name="tso",
        base_url="https://www.treesandshrubsonline.org",
        sitemaps=("https://www.treesandshrubsonline.org/sitemap.xml",),
        seeds=(),
        allow=re.compile(r"^https://www\.treesandshrubsonline\.org/articles/[a-z0-9-]+/[a-z0-9-]+/$"),
        allow_aliases=re.compile(r"^https://www\.treesandshrubsonline\.org/articles/[a-z0-9-]+/[a-z0-9-]+/$"),
        relevant=re.compile(r"^https://www\.treesandshrubsonline\.org/articles/[a-z0-9-]+/[a-z0-9-]+/$"),
        delay_s=10.0,
        follow_links=False,
    ),
}
