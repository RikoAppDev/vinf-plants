"""Web search page over the PyLucene index: a query form, the hits as cards and the query help.

Usage (in the PyLucene image coady/pylucene, see lucene_docker.sh):
    LUCENE_PORT=8080 ./lucene_docker.sh lucene_index.web        then open http://localhost:8080
    python -m lucene_index.web --port 8080 --host 0.0.0.0

GET /?q=...&top=10&similarity=bm25&operator=or runs lucene_index.search on the index opened at
startup and shows the hits on the search page; GET / shows the form, clickable example queries and
the searchable fields. Standard library only (http.server, html.escape), no JavaScript.
"""

import argparse
import collections
import html
import os
import re
import signal
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import lucene

from crawler.config import SITES as CRAWLED_SITES
from sparkjobs.join_wiki import LEVELS

from . import documents, querycheck
from .build import BUILD_COMMAND, ENGLISH_FIELDS, INDEX_DIR, STORED_TEXT_FIELDS
from .search import (DEFAULT_FIELDS, DEFAULT_OPERATOR, DEFAULT_SIMILARITY, OPERATORS, SIMILARITIES, QueryError,
                     Searcher, index_exists)


def default_first(choices, default):
    return (default,) + tuple(choice for choice in choices if choice != default)


TOPS = ("10", "20", "50")
# The first option of a selector is the default of lucene_index.search, so the page ranks like the command line.
SIMILARITY_CHOICES = default_first(SIMILARITIES, DEFAULT_SIMILARITY)
OPERATOR_CHOICES = default_first(OPERATORS, DEFAULT_OPERATOR)
SIMILARITY_LABELS = {"bm25": "BM25", "classic": "classic tf-idf"}
DEFAULT_PORT = 8080
# lucene_docker.sh publishes LUCENE_PORT and passes it in, so the page listens on the published port.
PORT_ENV = "LUCENE_PORT"
COMMON_SHOWN = 5
# No plant query needs more; a longer one is refused instead of being searched and echoed back.
MAX_QUERY_LENGTH = 1000
# Values of one field, and characters of one value, in the line of matched values on a card.
MATCHED_SHOWN = 4
MATCHED_WIDTH = 80
# A query word becomes a regex with one \w* per star, which tries every split of a value word among the
# stars: k stars cost about L**k steps on a word of L letters, and the regex holds the interpreter lock, so
# every request waits. Runs of stars count as one; a term or phrase with more stars is not highlighted.
MAX_HIGHLIGHT_STARS = 2
# Each highlighted word is one regex search in every stored value of a card; later words are not highlighted.
MAX_HIGHLIGHT_WORDS = 20
INTERNAL_ERROR = "an internal error stopped the search; the log of the server has the details"
SYNTAX_ADVICE = "See the syntax and the example queries below."
TITLE_WIDTH = 80
PLACEHOLDER = "year:[1754 TO 1800] AND plant_type:tree"
# A tab or line break separates words like a space; the other control characters are dropped.
SPACE_CONTROL_RE = re.compile(r"[\t\n\v\f\r]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")

# (query type, query, what it finds): one example of every kind of query the parser handles.
EXAMPLES = (
    ("Boolean NOT", "quercus NOT robur", "oaks except the English oak"),
    ("phrase", '"mountain laurel"', "both words, next to each other"),
    ("proximity", 'text:"drought tolerant"~3', "both words close together, also in the other order"),
    ("fuzzy", "rhododendorn~", "a misspelt name, up to two edits away"),
    ("range, AND", "year:[1754 TO 1800] AND plant_type:tree", "trees named from 1754 to 1800"),
    ("open ranges", "density:[700 TO *] AND zone_min:[* TO 6]", "wood of 700 kg/m³ or more, hardy to zone 6"),
    ("OR group", "iucn:(vu OR en OR cr) AND origin:europe", "threatened plants of Europe"),
    ("wildcard", "querc*", "every word that starts with querc"),
    ("boost", "name:robur^3 OR common_name:oak",
     "robur in the name or oak in a common name; a name match counts three times as much"),
    ("plant properties", "light:shade AND plant_type:shrub AND leaf:evergreen", "evergreen shrubs that grow in shade"),
    ("plant properties", "tolerates:drought AND soil:clay AND plant_type:tree",
     "trees that tolerate drought and grow in clay"),
    ("plant properties", "flower_color:red AND attracts:hummingbirds", "red flowers that attract hummingbirds"),
    ("one site", "source:wooddb AND janka:[10000 TO *]", "very hard woods (10,000 N or more) of the Wood Database"),
    ("five filters", "authority:L AND year:1753 AND soil:clay AND zone_min:[* TO 5] AND plant_type:tree",
     "trees Linnaeus named in 1753 that grow in clay, hardy to zone 5"),
)
SYNTAX = (
    ("word word", "free text, in the boosted fields below; OR between the words unless the operator is AND"),
    ("plant_type:tree", "plant properties are searched through their field; free text searches the names, "
                        "the descriptions and the Wikipedia lead only"),
    ("field:value", "one field, e.g. soil:clay, iucn:en, source:wooddb"),
    ("AND OR NOT + - ( )", "Boolean operators in capitals, required and excluded terms, grouping"),
    ('"full sun"~2', "phrase, with an optional slop"),
    ("word~  word*", "fuzzy and wildcard terms (a wildcard cannot start a word)"),
    ("[a TO b]  {a TO b}  *", "inclusive and exclusive ranges, * for an open end"),
    ("term^2", "boost"),
    ("*:*", "every plant; *:* NOT robur is every plant without robur"),
)
# Site names shown on a hit; source:<site> finds the plants of a site.
SITE_LABELS = {"ncsu": "NCSU", "pfaf": "PFAF", "tso": "TSO", "wooddb": "Wood Database"}
# Host (without www.) of the pages of every site.
SITE_HOSTS = {re.sub(r"^www\.", "", urlsplit(site.base_url).netloc.lower()): name
              for name, site in CRAWLED_SITES.items()}
# What the linked article is about, per match level of sparkjobs.join_wiki.
WIKI_ARTICLES = {LEVELS[documents.OWN_NAME]: "article about this plant",
                 LEVELS[documents.SPECIES]: "article about its species",
                 LEVELS[documents.GENUS]: "article about its genus"}
THREATENED = {"vu", "en", "cr", "ew", "ex"}


def iucn_names():
    """{code: name} of the IUCN codes of the index, in the order of documents.IUCN_NAMES."""
    names = {}
    for name, code in documents.IUCN_NAMES.items():
        if code in documents.IUCN_CODES:
            names.setdefault(code, name)
    return names


EXACT_HINTS = {"key": "lower-case scientific name",
               "source": ", ".join("{} ({})".format(site, SITE_LABELS[site]) for site in documents.SITES),
               "iucn": ", ".join("{} {}".format(code, name) for code, name in iucn_names().items())}
NUMBER_HINTS = {
    "year": "year the name was published", "zone_min": "coldest USDA hardiness zone",
    "zone_max": "warmest USDA zone", "height_max_cm": "cm", "density": "wood, kg/m³",
    "janka": "wood hardness, N", "edibility": "PFAF rating 0-5", "medicinal": "PFAF rating 0-5",
    "n_sources": "sites with a page, 1-4",
}

CSS = """
:root{--ink:#1d2421;--muted:#67716c;--line:#e1e5e0;--paper:#f6f7f3;--card:#fff;--green:#2d6a4f;
--green-soft:#e3efe7;--chip:#f0f2ee;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:880px;margin:0 auto;padding:36px 20px 56px}
a{color:var(--green)}
code,pre{font-family:var(--mono)}
header h1{margin:0;font-size:26px;letter-spacing:-.01em}
header h1 a{color:inherit;text-decoration:none}
header p{margin:4px 0 0;color:var(--muted);font-size:15px}
.search{margin:22px 0 0}
.bar{display:flex;gap:8px}
.bar input{flex:1;min-width:0;padding:11px 14px;font:15px/1.4 var(--mono);color:var(--ink);background:#fff;
border:1px solid #c8cec8;border-radius:10px}
.bar input:focus{outline:none;border-color:var(--green);box-shadow:0 0 0 3px var(--green-soft)}
.bar button{padding:0 22px;font-family:inherit;font-size:15px;font-weight:600;color:#fff;background:var(--green);
border:0;border-radius:10px;cursor:pointer}
.bar button:hover{background:#245a42}
.opts{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:10px;font-size:14px;color:var(--muted)}
.opts select{margin-left:4px;padding:3px 6px;font:inherit;color:var(--ink);background:#fff;border:1px solid #c8cec8;
border-radius:6px}
.notes{margin:22px 0 0;padding:10px 16px 10px 34px;font-size:14px;color:#5c4a12;background:#fdf7e3;
border:1px solid #efdfae;border-radius:10px}
.summary{margin:26px 0 8px;font-size:15px}
.summary b{font-variant-numeric:tabular-nums}
.summary .dim{color:var(--muted)}
.parsed{margin:0 0 16px;padding:8px 12px;font-size:13px;color:#3b4540;background:#fff;border:1px solid var(--line);
border-radius:8px;white-space:pre-wrap;word-break:break-word}
.parsed .label{margin-right:8px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.hit{margin:12px 0;padding:14px 18px 16px;background:var(--card);border:1px solid var(--line);border-radius:12px;
box-shadow:0 1px 2px rgba(20,40,30,.04)}
.head{display:flex;align-items:baseline;gap:10px}
.rank{flex:none;min-width:28px;color:var(--muted);font:13px var(--mono)}
.name{font-size:18px;font-weight:600;font-style:italic}
.author{color:var(--muted);font-size:14px}
.score{flex:none;margin-left:auto;padding-left:12px;color:var(--muted);font:12px var(--mono)}
.card{margin-left:38px}
.common{margin:2px 0 0}
.more{color:var(--muted);font-size:14px}
.kind{margin:2px 0 0;color:var(--muted);font-size:14px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0;padding:0;list-style:none}
.chips li{padding:1px 9px;font-size:13px;background:var(--chip);border-radius:999px}
.chips li.threatened{color:#8a2a12;background:#fbe9e3}
.matched{margin:10px 0 0;font-size:14px;word-break:break-word}
.matched .label{margin-right:8px}
.matched b{font-weight:600;background:var(--green-soft);border-radius:3px}
.links{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 8px;margin:10px 0 0;font-size:14px}
.links a{text-decoration:none}
.links a:hover{text-decoration:underline}
.links .source{padding:0 7px;border:1px solid var(--line);border-radius:6px}
.links .label{margin-left:6px}
.links .label:first-child{margin-left:0}
.match{color:var(--muted)}
.none{margin:20px 0;padding:14px 18px;background:var(--card);border:1px dashed #c8cec8;border-radius:12px}
.error{margin:26px 0 0;padding:14px 18px;color:#7d2410;background:#fdf0ec;border:1px solid #f0c8bd;border-radius:12px}
.error pre{margin:8px 0;font-size:13px;white-space:pre-wrap;word-break:break-word}
.error p{margin:0;font-size:14px}
.error .explanation{margin:6px 0 0;font-size:15px}
.help{margin-top:30px;padding:2px 20px 16px;background:var(--card);border:1px solid var(--line);border-radius:12px}
.help summary{padding:12px 0 6px;font-weight:600;cursor:pointer}
.help h2{margin:18px 0 6px;font-size:15px}
.examples,.syntax{width:100%;border-collapse:collapse;font-size:14px}
.examples td,.syntax td{padding:6px 10px 6px 0;border-top:1px solid var(--line);vertical-align:top}
.examples td:first-child{width:118px;color:var(--muted);white-space:nowrap}
.examples td:last-child,.syntax td:last-child{color:var(--muted)}
.examples a{text-decoration:none;word-break:break-word}
.examples a:hover{text-decoration:underline}
.syntax td:first-child{width:200px;white-space:pre}
.fields{margin:0}
.fields dt{margin-top:10px;font-size:14px;font-weight:600}
.fields dd{margin:4px 0 0}
.fields ul{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.fields li{padding:1px 8px;font-size:13px;background:var(--chip);border-radius:6px}
.fields li span{color:var(--muted)}
footer{margin-top:26px;color:var(--muted);font-size:13px}
"""


def attach_thread():
    lucene.getVMEnv().attachCurrentThread()


class Engine:
    """The searchers of every similarity and operator, opened once.

    All Lucene calls run on one worker thread that is attached to the JVM. The request threads of the
    server never touch a Java object, and the query parser, which is not thread-safe, is used by one
    thread only.
    """

    def __init__(self, index_dir=INDEX_DIR):
        self.searchers = {(similarity, operator): Searcher(index_dir, similarity, operator)
                          for similarity in SIMILARITIES for operator in OPERATORS}
        self.documents = next(iter(self.searchers.values())).reader.numDocs()
        self.index_dir = index_dir
        self.worker = ThreadPoolExecutor(max_workers=1, initializer=attach_thread)

    def search(self, query_string, top=10, similarity=DEFAULT_SIMILARITY, operator=DEFAULT_OPERATOR):
        """{"parsed", "total", "hits", "ms"} of a query, or {"status", "error", "lucene"} if it fails:
        status 400 for a query the user can correct, 500 for any other error."""
        return self.worker.submit(self._search, query_string, top, similarity, operator).result()

    def _search(self, query_string, top, similarity, operator):
        # Only Python values leave this thread: a Java object freed in a request thread would need
        # that thread attached to the JVM.
        try:
            started = time.perf_counter()
            query, total, hits = self.searchers[similarity, operator].search(query_string, top)
            return {"parsed": query.toString(), "total": total, "hits": hits,
                    "ms": (time.perf_counter() - started) * 1000}
        except QueryError as error:
            return {"status": 400, "error": error.explanation, "lucene": error.lucene_message}
        except lucene.JavaError as error:
            # The page says in plain words that the search failed; the Java message, which says why,
            # goes to the log of the server only.
            message = " ".join(error.getJavaException().toString().split())
            print("search failed for {!r}: {}".format(query_string, message), file=sys.stderr, flush=True)
            return {"status": 500, "error": INTERNAL_ERROR, "lucene": None}
        except Exception:
            traceback.print_exc()
            return {"status": 500, "error": INTERNAL_ERROR, "lucene": None}

    def close(self):
        self.worker.shutdown()
        for searcher in self.searchers.values():
            searcher.close()


def escape(value):
    return html.escape(str(value))


def excerpt(text, match=None, width=MATCHED_WIDTH):
    """text cut to about width characters, around the regex match if the cut would hide it."""
    if len(text) <= width:
        return text
    start = 0
    if match is not None and match.end() > width - 1:
        start = max(min(match.start() - width // 4, len(text) - width + 1), 0)
    end = start + width - 1
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def clean_query(text):
    return CONTROL_RE.sub("", SPACE_CONTROL_RE.sub(" ", text))


def form_values(params):
    """Query and options of a parse_qs dict; an unknown option falls back to its default, the first choice.

    "length" is the length of the query before it is cut to MAX_QUERY_LENGTH.
    """
    def pick(name, allowed):
        value = (params.get(name) or [allowed[0]])[0]
        return value if value in allowed else allowed[0]

    query = clean_query((params.get("q") or [""])[0]).strip()
    return {"q": query[:MAX_QUERY_LENGTH].rstrip(), "length": len(query), "top": pick("top", TOPS),
            "similarity": pick("similarity", SIMILARITY_CHOICES), "operator": pick("operator", OPERATOR_CHOICES)}


def page_url(form, query):
    """Link to the hits of query with the options of the current form."""
    return "/?" + urlencode({"q": query, "top": form["top"], "similarity": form["similarity"],
                             "operator": form["operator"]})


def site_name(url):
    host = re.sub(r"^www\.", "", urlsplit(url).netloc.lower())
    site = SITE_HOSTS.get(host)
    return SITE_LABELS.get(site, site) if site else host or url


def external_link(url, text, css_class=""):
    """A link that opens in a new tab; a value that is not an http(s) URL is shown as text."""
    if not url or not url.startswith(("http://", "https://")):
        return escape(text)
    return '<a{} href="{}" target="_blank" rel="noopener noreferrer" title="{}">{}</a>'.format(
        ' class="{}"'.format(css_class) if css_class else "", escape(url), escape(url), escape(text))


def source_links(urls):
    """Links to the source pages; pages of one site are numbered, as they would carry the same name."""
    names = [site_name(url) for url in urls]
    repeated = {name for name, count in collections.Counter(names).items() if count > 1}
    seen = collections.Counter()
    links = []
    for url, name in zip(urls, names):
        if name in repeated:
            seen[name] += 1
            name = "{} {}".format(name, seen[name])
        links.append(external_link(url, name, "source"))
    return links


def wiki_article(match):
    """What the linked article is about, from its match ("own name, via box"); "" if that is not known."""
    return WIKI_ARTICLES.get((match or "").split(",")[0].strip(), "")


def number_chips(hit):
    """(text, css class) of the stored numbers of a hit, named like the fields."""
    chips = []
    # A plant can have zone_min without zone_max: then it shows that zone alone.
    zones = [hit[field] for field in ("zone_min", "zone_max") if hit[field] is not None]
    if zones:
        chips.append(("zone " + "–".join(str(zone) for zone in dict.fromkeys(zones)), ""))
    if hit["height_max_cm"] is not None:
        chips.append(("height {:g} m".format(hit["height_max_cm"] / 100), ""))
    if hit["year"] is not None:
        chips.append(("year {}".format(hit["year"]), ""))
    for code in hit["iucn"]:
        chips.append(("iucn " + code.upper(), "threatened" if code in THREATENED else ""))
    if hit["density"] is not None:
        chips.append(("density {} kg/m³".format(hit["density"]), ""))
    if hit["janka"] is not None:
        chips.append(("janka {:,} N".format(hit["janka"]), ""))
    for field in ("edibility", "medicinal"):
        if hit[field] is not None:
            chips.append(("{} {}/5".format(field, hit[field]), ""))
    return chips


def value_pattern(token):
    """Regex that finds the words of a term or phrase token in a stored value; None if it is not highlighted.

    * and ? of a wildcard stand for letters. A fuzzy term finds only its own spelling: the pattern only
    puts the matching values first and in bold, it decides nothing about the hits.

    The pattern is built from the runs of letters and wildcards of the token only, so every \\W+ between
    two runs can match in one way. Then only the stars make the regex backtrack, and with at most
    MAX_HIGHLIGHT_STARS of them in the whole token a search costs at most about L**2 steps per word of
    the value.
    """
    if token.kind == "term":
        text = querycheck.unescape(token.text)
        if text.lower() in querycheck.OPERATOR_WORDS:
            return None
    elif token.kind == "phrase":
        text = querycheck.unescape(token.text[1:-1])
    else:
        return None
    runs = [re.sub(r"\*+", "*", run) for run in re.findall(r"[\w*?]+", text)]
    if (not any(char.isalnum() for run in runs for char in run)
            or sum(run.count("*") for run in runs) > MAX_HIGHLIGHT_STARS):
        return None
    parts = ["".join(r"\w*" if char == "*" else r"\w" if char == "?" else re.escape(char) for char in run)
             for run in runs]
    return re.compile(r"(?<!\w)" + r"\W+".join(parts) + r"(?!\w)", re.IGNORECASE)


def shown_values(values, patterns):
    """([(text, matched)] of at most MATCHED_SHOWN values, number of values left out).

    The values that match a pattern come first, and a long value is cut around its match.
    """
    found = []
    for value in values:
        match = next((match for match in (pattern.search(value) for pattern in patterns) if match), None)
        found.append((value, match))
    ordered = [item for item in found if item[1]] + [item for item in found if not item[1]]
    return ([(excerpt(value, match), match is not None) for value, match in ordered[:MATCHED_SHOWN]],
            max(len(ordered) - MATCHED_SHOWN, 0))


def matched_values(hit, query):
    """[(field, [(text, matched)], values left out)] of the stored values that show why a hit matched.

    Every field the query names that the hit stores a value of, and for the words without a field the
    names, common names and synonyms that the card does not show anyway: a plant found through a synonym
    shows that synonym.
    """
    named, values = querycheck.field_values(querycheck.scan(query))
    patterns = collections.defaultdict(list)
    for field, _operator, token in values:
        pattern = value_pattern(token)
        if pattern is not None and pattern not in patterns[field] and len(patterns[field]) < MAX_HIGHLIGHT_WORDS:
            patterns[field].append(pattern)
    found = []
    for field in named:
        stored = hit.get(field)
        items = stored if isinstance(stored, list) else [] if stored is None else [stored]
        if items:
            found.append((field,) + shown_values([str(item) for item in items], patterns[field]))
    plant_names, common = hit.get("name", []), hit.get("common_name", [])
    visible = plant_names[:1] + common[:COMMON_SHOWN]
    unexplained = [pattern for pattern in patterns[None] if not any(pattern.search(value) for value in visible)]
    for field, unseen in (("name", plant_names[1:]), ("common_name", common[COMMON_SHOWN:]),
                          ("synonym", hit.get("synonym", []))):
        matching = [value for value in unseen if any(pattern.search(value) for pattern in unexplained)]
        if matching and field not in named:
            found.append((field,) + shown_values(matching, unexplained))
    return found


def render_matched(items):
    parts = []
    for field, shown, left_out in items:
        texts = ", ".join("<b>{}</b>".format(escape(text)) if matched else escape(text) for text, matched in shown)
        parts.append("{}: {}{}".format(escape(field), texts,
                                       ' <span class="more">+{} more</span>'.format(left_out) if left_out else ""))
    return '<p class="matched"><span class="label">matched</span>{}</p>'.format(" &middot; ".join(parts))


def render_hit(hit, query=""):
    name = hit["name"][0] if hit["name"] else hit["key"]
    head = ['<span class="rank">{}</span>'.format(hit["rank"]), '<span class="name">{}</span>'.format(escape(name))]
    if hit["authority"]:
        head.append('<span class="author">{}</span>'.format(escape(hit["authority"][0])))
    head.append('<span class="score" title="score">{:.4f}</span>'.format(hit["score"]))
    parts = ['<article class="hit">', '<div class="head">{}</div>'.format("".join(head)), '<div class="card">']

    common = hit["common_name"]
    if common:
        more = len(common) - COMMON_SHOWN
        parts.append('<p class="common">{}{}</p>'.format(
            escape(", ".join(common[:COMMON_SHOWN])),
            ' <span class="more">+{} more</span>'.format(more) if more > 0 else ""))
    kind = [", ".join(values) for values in (hit["family"], hit["plant_type"]) if values]
    if kind:
        parts.append('<p class="kind">{}</p>'.format(" &middot; ".join(escape(text) for text in kind)))
    chips = number_chips(hit)
    if chips:
        parts.append('<ul class="chips">{}</ul>'.format("".join(
            '<li{}>{}</li>'.format(' class="{}"'.format(css) if css else "", escape(text)) for text, css in chips)))
    matched = matched_values(hit, query)
    if matched:
        parts.append(render_matched(matched))

    links = []
    if hit["url"]:
        links.append('<span class="label">sources</span>')
        links.extend(source_links(hit["url"]))
    if hit["wiki_title"]:
        links.append('<span class="label">wikipedia</span>')
        links.append(external_link(hit["wiki_url"], hit["wiki_title"]))
        article = wiki_article(hit["wiki_match"])
        if article:
            links.append('<span class="match">({})</span>'.format(escape(article)))
    if links:
        parts.append('<p class="links">{}</p>'.format(" ".join(links)))
    parts.append("</div></article>")
    return "\n".join(parts)


def render_notes(query):
    notes = querycheck.notes(query)
    if not notes:
        return ""
    return '<ul class="notes">{}</ul>'.format("".join("<li>{}</li>".format(escape(note)) for note in notes))


def no_hits_hint(form):
    """What to try when nothing matches; OR instead of AND only if the query or the operator uses AND."""
    uses_and = form["operator"] == "and" or any(token.kind == "and" for token in querycheck.scan(form["q"]))
    tries = (["OR instead of AND"] if uses_and else []) + ["a fuzzy term (<code>word~</code>)",
                                                           "a wildcard (<code>word*</code>)"]
    return ('<p class="none">No plant matches this query. Try {} or {}. The plant properties are not stemmed: '
            '<code>plant_type:tree</code>, not <code>plant_type:trees</code>.</p>').format(", ".join(tries[:-1]),
                                                                                       tries[-1])


def render_results(form, result):
    total, hits = result["total"], result["hits"]
    summary = ('<p class="summary"><b>{:,}</b> {} <span class="dim">&middot; {} shown &middot; {:.1f} ms &middot; '
               '{} similarity &middot; default operator {}</span></p>').format(
        total, "hit" if total == 1 else "hits", len(hits), result["ms"],
        escape(SIMILARITY_LABELS.get(form["similarity"], form["similarity"])), escape(form["operator"].upper()))
    parsed = '<pre class="parsed"><span class="label">parsed</span>{}</pre>'.format(escape(result["parsed"]))
    head = render_notes(form["q"]) + summary + parsed
    if not hits:
        return head + no_hits_hint(form)
    return head + "\n".join(render_hit(hit, form["q"]) for hit in hits)


def render_error(title, explanation, lucene_message=None, advice=SYNTAX_ADVICE):
    return ('<div class="error"><b>{}</b><p class="explanation">{}</p>{}{}</div>').format(
        escape(title), escape(explanation),
        "<pre>Lucene: {}</pre>".format(escape(lucene_message)) if lucene_message else "",
        "<p>{}</p>".format(escape(advice)) if advice else "")


def render_form(form):
    def select(name, choices):
        options = "".join('<option value="{}"{}>{}</option>'.format(
            escape(value), " selected" if value == form[name] else "", escape(text)) for value, text in choices)
        return '<label>{} <select name="{}">{}</select></label>'.format(name, name, options)

    return ('<form class="search" action="/" method="get">\n'
            '<div class="bar"><input type="search" name="q" value="{}" placeholder="{}" aria-label="query" '
            'autofocus autocomplete="off" autocapitalize="off" spellcheck="false">'
            '<button type="submit">Search</button></div>\n'
            '<div class="opts">{}{}{}</div>\n</form>\n').format(
        escape(form["q"]), escape(PLACEHOLDER), select("top", [(top, top) for top in TOPS]),
        select("similarity", [(name, SIMILARITY_LABELS.get(name, name)) for name in SIMILARITY_CHOICES]),
        select("operator", [(name, name.upper()) for name in OPERATOR_CHOICES]))


def field_groups():
    def text_fields(fields):
        return [(field, "stemmed" if field in ENGLISH_FIELDS else
                 "shown when the query names it" if field in STORED_TEXT_FIELDS else "") for field in fields]

    return (
        ("Words without a field", [(field, "boost {}".format(boost)) for field, boost in DEFAULT_FIELDS]),
        ("Names", [(field, "") for field in documents.NAME_FIELDS]),
        ("Plant properties, searched only through their field and not stemmed",
         [(field, "") for field in documents.TAG_FIELDS]),
        ("Long text", text_fields(documents.LONG_FIELDS)),
        ("Exact terms", [(field, EXACT_HINTS.get(field, "")) for field in documents.EXACT_FIELDS]),
        ("Numbers, for ranges", [(field, NUMBER_HINTS.get(field, "")) for field in documents.NUMBER_FIELDS]),
    )


def render_help(form, opened):
    examples = "\n".join('<tr><td>{}</td><td><a href="{}"><code>{}</code></a></td><td>{}</td></tr>'.format(
        escape(kind), escape(page_url(form, query)), escape(query), escape(note)) for kind, query, note in EXAMPLES)
    syntax = "\n".join('<tr><td><code>{}</code></td><td>{}</td></tr>'.format(escape(code), escape(note))
                       for code, note in SYNTAX)
    fields = "\n".join('<dt>{}</dt><dd><ul>{}</ul></dd>'.format(escape(title), "".join(
        '<li><code>{}</code>{}</li>'.format(escape(field), ' <span>{}</span>'.format(escape(hint)) if hint else "")
        for field, hint in items)) for title, items in field_groups())
    return ('<details class="help"{}>\n<summary>Query help: examples, syntax and fields</summary>\n'
            '<h2>Example queries</h2>\n<table class="examples">\n{}\n</table>\n'
            '<h2>Syntax</h2>\n<table class="syntax">\n{}\n</table>\n'
            '<h2>Searchable fields</h2>\n<dl class="fields">\n{}\n</dl>\n</details>\n').format(
        " open" if opened else "", examples, syntax, fields)


def render_page(engine, form, content="", help_open=None):
    """The whole page; the help is open on the start page (and on an error, which points to it)."""
    title = "{} - plant search".format(excerpt(form["q"], width=TITLE_WIDTH)) if form["q"] else "Plant search"
    if help_open is None:
        help_open = not form["q"]
    return "".join([
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
        '<title>{}</title>\n'.format(escape(title)),
        # An empty icon, so the browser does not ask for /favicon.ico.
        '<link rel="icon" href="data:,">\n<style>', CSS, '</style>\n</head>\n<body>\n<main>\n',
        '<header><h1><a href="/">Plant search</a></h1>\n',
        '<p>{:,} plant entities from NCSU, PFAF, Trees and Shrubs Online and the Wood Database, '
        'linked to Wikipedia</p></header>\n'.format(engine.documents),
        render_form(form), content, "\n", render_help(form, help_open),
        '<footer>vinf-plants &middot; PyLucene {} &middot; index {}</footer>\n'.format(
            escape(lucene.VERSION), escape(engine.index_dir)),
        '</main>\n</body>\n</html>\n'])


def search_page(engine, form):
    """(HTTP status, HTML) of the search page for the form values."""
    if form["length"] > MAX_QUERY_LENGTH:
        return 400, render_page(engine, form, render_error(
            "The query is too long", "it has {:,} characters; at most {:,} are allowed".format(
                form["length"], MAX_QUERY_LENGTH), advice="Shorten it and search again."))
    if not form["q"]:
        return 200, render_page(engine, form)
    result = engine.search(form["q"], int(form["top"]), form["similarity"], form["operator"])
    if "error" not in result:
        return 200, render_page(engine, form, render_results(form, result))
    if result["status"] == 400:
        content = render_error("The query cannot be run", result["error"], result["lucene"])
    else:
        content = render_error("The search failed", result["error"], advice="")
    return result["status"], render_page(engine, form, content, help_open=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        engine = self.server.engine
        url = urlsplit(self.path)
        try:
            if url.path != "/":
                status, content = 404, render_page(engine, form_values({}), (
                    '<div class="error"><b>No page at {}</b><p><a href="/">Back to the search</a></p></div>'
                ).format(escape(excerpt(clean_query(url.path), width=TITLE_WIDTH))))
            else:
                status, content = search_page(engine, form_values(parse_qs(url.query)))
        except Exception:
            # As for an error in the engine: plain words on the page, the traceback in the log.
            traceback.print_exc()
            status, content = 500, "<!doctype html><title>Error</title><p>The search failed: {}.</p>".format(
                escape(INTERNAL_ERROR))
        self.send_page(status, content)

    def send_page(self, status, content):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(engine, host="0.0.0.0", port=DEFAULT_PORT):
    """HTTP server of the search page; port 0 picks a free port (server.server_address[1]).

    A threading server: browsers open spare connections ahead of time, and a single-threaded server
    would wait on such an idle connection while the real request queues behind it.
    """
    server = ThreadingHTTPServer((host, port), Handler)
    server.engine = engine
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Web search page over the PyLucene index of the plant entities")
    parser.add_argument("--port", type=int, default=int(os.environ.get(PORT_ENV) or DEFAULT_PORT),
                        help="default ${} or {}".format(PORT_ENV, DEFAULT_PORT))
    parser.add_argument("--host", default="0.0.0.0",
                        help="default 0.0.0.0, so that the port published by Docker reaches the page")
    parser.add_argument("--index", default=INDEX_DIR)
    args = parser.parse_args(argv)
    if not index_exists(args.index):
        print("error: no Lucene index in {}; build it with {}".format(args.index, BUILD_COMMAND), file=sys.stderr)
        return 2

    engine = Engine(args.index)
    server = make_server(engine, args.host, args.port)
    shown_host = "localhost" if args.host in ("", "0.0.0.0") else args.host
    print("{:,} documents from {}; open http://{}:{}/ (Ctrl+C stops)".format(
        engine.documents, args.index, shown_host, server.server_address[1]), flush=True)
    # docker stop sends SIGTERM: close the server and the index as on Ctrl+C.
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
