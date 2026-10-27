"""URL extraction from raw HTML / XML using regular expressions only."""

import html
import re
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

# href value in double quotes, single quotes or unquoted, on any <a ...> tag.
HREF_RE = re.compile(
    r"""<a\b[^>]*?\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""",
    re.IGNORECASE,
)

SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)

_SKIPPED_SCHEMES = ("mailto:", "javascript:", "tel:", "data:", "#")


def normalize_url(raw_url, base_url):
    """Return an absolute, fragment-free URL or None when it is not crawlable."""
    candidate = html.unescape(raw_url).strip()
    if not candidate or candidate.lower().startswith(_SKIPPED_SCHEMES):
        return None
    absolute, _fragment = urldefrag(urljoin(base_url, candidate))
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    # Scheme and host are case-insensitive, the path is not.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def extract_links(page_html, base_url):
    """All distinct absolute URLs found in <a href> attributes, in page order."""
    found = []
    seen = set()
    for match in HREF_RE.finditer(page_html):
        raw = match.group(1) or match.group(2) or match.group(3) or ""
        url = normalize_url(raw, base_url)
        if url and url not in seen:
            seen.add(url)
            found.append(url)
    return found


def extract_sitemap_urls(sitemap_xml):
    """All <loc> URLs of a sitemap, in document order."""
    return [html.unescape(url) for url in SITEMAP_LOC_RE.findall(sitemap_xml)]
