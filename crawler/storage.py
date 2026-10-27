"""Raw page storage and the crawl metadata log (TSV, append-only)."""

import hashlib
import os
import re
import time
from urllib.parse import urlsplit

LOG_COLUMNS = (
    "fetched_at_utc", "url", "final_url", "status", "content_type", "bytes",
    "sha256", "elapsed_ms", "attempts", "depth", "referrer", "file", "error",
)

_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")

# May change on a later run: 401/403 is how WAFs and anti-bot layers block,
# 429 is rate limiting (5xx are handled apart).
NON_FINAL_HTTP_STATUSES = {401, 403, 429}

# Final too: the redirect target is stored under its own URL, or lies outside the allowed URLs.
FINAL_TEXT_STATUSES = {"redirect-duplicate", "redirect-outside"}


def file_name_for(url):
    """Readable, collision-free file name: slug of the path + short URL hash."""
    parts = urlsplit(url)
    slug = _UNSAFE_CHARS_RE.sub("_", (parts.path + ("_" + parts.query if parts.query else "")).strip("/"))[:120]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return "{}__{}.html".format(slug or "index", digest)


class Storage:
    def __init__(self, data_dir, site_name):
        self.raw_dir = os.path.join(data_dir, "raw", site_name)
        self.state_dir = os.path.join(data_dir, "state", site_name)
        self.log_path = os.path.join(self.state_dir, "crawl_log.tsv")
        self.discovered_path = os.path.join(self.state_dir, "discovered.tsv")
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.state_dir, exist_ok=True)
        is_new_log = not os.path.exists(self.log_path)
        self._log = open(self.log_path, "a", encoding="utf-8")
        if is_new_log:
            self._log.write("\t".join(LOG_COLUMNS) + "\n")
            self._log.flush()

    def fetched_urls(self):
        """URLs with a final answer (HTTP < 500 except 401/403/429, or a final redirect status).

        Anything else (network error, 5xx, challenge, robots) is retried by a later run.
        """
        urls = set()
        with open(self.log_path, encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                columns = line.rstrip("\n").split("\t")
                if len(columns) != len(LOG_COLUMNS):
                    continue
                status = columns[3]
                if status in FINAL_TEXT_STATUSES or (
                        status.isdigit() and int(status) < 500 and int(status) not in NON_FINAL_HTTP_STATUSES):
                    urls.add(columns[1])
        return urls

    def save_page(self, url, body, keep_previous=False):
        """Write the body exactly as received; returns (file name, sha256).

        keep_previous adds a UTC timestamp instead of overwriting (a re-read sitemap keeps the first copy).
        """
        name = file_name_for(url)
        if keep_previous and os.path.exists(os.path.join(self.raw_dir, name)):
            name = "{}__{}.html".format(name[:-len(".html")], time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        with open(os.path.join(self.raw_dir, name), "wb") as handle:
            handle.write(body)
        return name, hashlib.sha256(body).hexdigest()

    def save_robots(self, body):
        """Keep the robots.txt in force during this run (proof of politeness)."""
        with open(os.path.join(self.state_dir, "robots.txt"), "wb") as handle:
            handle.write(body)

    def log(self, **row):
        values = [str(row.get(column, "")).replace("\t", " ").replace("\n", " ") for column in LOG_COLUMNS]
        self._log.write("\t".join(values) + "\n")
        self._log.flush()

    def close(self):
        self._log.close()
