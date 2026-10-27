"""Crawl statistics for the wiki report (plain text, no screenshots).

Usage:
    python -m tools.stats --site ncsu
    python -m tools.stats --site ncsu --tokens     # adds tiktoken counts of raw pages and extracted records
"""

import argparse
import json
import os
import sys
from collections import Counter

from crawler import config
from crawler.storage import LOG_COLUMNS

# Bookkeeping fields of a record, not text taken from the page.
NON_TEXT_FIELDS = {"url", "source", "family_raw"}


def read_log(data_dir, site_name):
    with open(os.path.join(data_dir, "state", site_name, "crawl_log.tsv"), encoding="utf-8") as handle:
        next(handle, None)
        for line in handle:
            columns = line.rstrip("\n").split("\t")
            if len(columns) == len(LOG_COLUMNS):
                yield dict(zip(LOG_COLUMNS, columns))


def tiktoken_encoding():
    import tiktoken  # optional dependency, only needed for the bonus statistic

    return tiktoken.get_encoding("cl100k_base")


def count_tokens(paths):
    encoding = tiktoken_encoding()
    total = 0
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            total += len(encoding.encode(handle.read(), disallowed_special=()))
    return total


def record_text(value, field=None):
    """Text values of an extracted record, one per line (field names and JSON syntax left out)."""
    if value is None or field in NON_TEXT_FIELDS:
        return ""
    if isinstance(value, dict):
        return "\n".join(filter(None, (record_text(item, name) for name, item in value.items())))
    if isinstance(value, list):
        return "\n".join(filter(None, (record_text(item) for item in value)))
    return str(value)


def count_record_tokens(path):
    encoding = tiktoken_encoding()
    total = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            total += len(encoding.encode(record_text(json.loads(line)), disallowed_special=()))
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description="Statistics of crawled documents")
    parser.add_argument("--site", required=True, choices=sorted(config.SITES))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--tokens", action="store_true", help="count tokens with tiktoken (slow)")
    args = parser.parse_args(argv)

    site = config.SITES[args.site]
    rows = list(read_log(args.data_dir, site.name))
    # Sitemaps and robots.txt are crawl documents but not plant pages.
    service_urls = set(site.sitemaps) | {site.base_url.rstrip("/") + "/robots.txt"}
    saved = [row for row in rows if row["status"] == "200" and row["file"]]
    files = sorted({row["file"] for row in saved})  # a re-seeded sitemap is logged twice, stored once
    # Keyed by the final URL: a page saved both through a redirect and under its own URL is one plant page.
    plant_rows = {row["final_url"] or row["url"]: row for row in saved
                  if row["url"] not in service_urls and site.relevant.match(row["url"])}
    paths = [os.path.join(args.data_dir, "raw", site.name, name) for name in files]
    plant_paths = [os.path.join(args.data_dir, "raw", site.name, row["file"]) for row in plant_rows.values()]
    disk_bytes = sum(os.path.getsize(path) for path in paths if os.path.exists(path))
    plant_bytes = sum(os.path.getsize(path) for path in plant_paths if os.path.exists(path))
    sizes = sorted(int(row["bytes"]) for row in plant_rows.values()) or [0]
    elapsed = [int(row["elapsed_ms"]) for row in saved if row["elapsed_ms"].isdigit()] or [0]
    # An empty status is a network error (timeout, connection reset) after all retries.
    statuses = Counter(row["status"] or "network error" for row in rows)
    transient = sum(count for status, count in statuses.items()
                    if status in ("network error", "challenge", "429") or status.startswith("5"))
    # One row = one URL; `attempts` is the number of HTTP requests behind it
    # ("robots" rows were never requested and have no attempts).
    requests_made = sum(int(row["attempts"]) for row in rows if row["attempts"].isdigit())
    retried = sum(1 for row in rows if row["attempts"].isdigit() and int(row["attempts"]) > 1)

    print("site\t{}".format(site.name))
    print("log rows (URLs tried)\t{}".format(len(rows)))
    print("HTTP requests incl. retries\t{}".format(requests_made))
    print("rows that needed a retry\t{}".format(retried))
    print("status codes\t{}".format(dict(statuses)))
    print("transient failures (not final, retried later)\t{}".format(transient))
    print("documents saved (incl. sitemaps)\t{}".format(len(files)))
    print("relevant (plant pages)\t{}".format(len(plant_rows)))
    print("size on disk, all / plant pages (decompressed)\t{:.1f} / {:.1f} MB".format(
        disk_bytes / 1e6, plant_bytes / 1e6))
    print("plant page size min / median / max\t{:.0f} / {:.0f} / {:.0f} kB".format(
        sizes[0] / 1e3, sizes[len(sizes) // 2] / 1e3, sizes[-1] / 1e3))
    print("server response time avg (until headers)\t{:.0f} ms".format(sum(elapsed) / len(elapsed)))
    if rows:
        print("first / last request (UTC)\t{} / {}".format(rows[0]["fetched_at_utc"], rows[-1]["fetched_at_utc"]))
    if args.tokens:
        print("tokens of plant pages (tiktoken cl100k_base)\t{}".format(count_tokens(plant_paths)))
        records = os.path.join(args.data_dir, "extracted", site.name + "_plants.jsonl")
        if os.path.exists(records):
            print("tokens of extracted record text (tiktoken cl100k_base)\t{}".format(count_record_tokens(records)))


if __name__ == "__main__":
    sys.exit(main())
