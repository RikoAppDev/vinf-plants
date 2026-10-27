"""Batch extraction over crawled pages.

Usage:
    python -m extractor.run --site ncsu
    python -m extractor.run --site all

Writes data/extracted/<site>_plants.jsonl (full records) and
data/extracted/<site>_plants.tsv (flat key fields, multi-values joined by " | ").
"""

import argparse
import importlib
import json
import os
import sys
from collections import Counter

from crawler import config
from crawler.crawl import canonicalize
from crawler.storage import LOG_COLUMNS

from .normalize import family_mapping

# Site -> module with extract_plant(page_html) -> dict | None
EXTRACTORS = {
    "ncsu": "extractor.ncsu",
    "pfaf": "extractor.pfaf",
    "tso": "extractor.tso",
    "wooddb": "extractor.wooddb",
}

TSV_COLUMNS = (
    "url", "source", "scientific_name", "authority", "family", "genus", "common_names", "synonyms",
    "height_min_cm", "height_max_cm", "zone_min", "zone_max", "attribute_count", "description_words",
)


def saved_pages(data_dir, site):
    """(url, file path) of every saved relevant page, from the crawl log.

    A page that was reached through a redirect whose target was also saved is
    skipped: it is the same document under a second URL (5 such pages on NCSU).
    """
    log_path = os.path.join(data_dir, "state", site.name, "crawl_log.tsv")
    rows = []
    with open(log_path, encoding="utf-8") as handle:
        next(handle, None)
        for line in handle:
            row = dict(zip(LOG_COLUMNS, line.rstrip("\n").split("\t")))
            if row.get("status") == "200" and row.get("file") and site.relevant.match(row["url"]):
                rows.append(row)
    saved_urls = {row["url"] for row in rows}
    skipped = 0
    for row in rows:
        final_url = canonicalize(site, row.get("final_url") or row["url"])
        if final_url != row["url"] and final_url in saved_urls:
            skipped += 1
            continue
        yield row["url"], os.path.join(data_dir, "raw", site.name, row["file"])
    if skipped:
        print("{}: {} redirect duplicates skipped".format(site.name, skipped))


def flatten(record):
    flat = {column: record.get(column) for column in TSV_COLUMNS}
    flat["common_names"] = " | ".join(record.get("common_names") or [])
    flat["synonyms"] = " | ".join(record.get("synonyms") or [])
    flat["attribute_count"] = len(record.get("attributes") or {})
    flat["description_words"] = len((record.get("description") or "").split())
    return ["" if flat[column] is None else str(flat[column]).replace("\t", " ") for column in TSV_COLUMNS]


def extract_site(site, data_dir):
    module = importlib.import_module(EXTRACTORS[site.name])
    records, not_plants = [], 0
    for url, path in saved_pages(data_dir, site):
        with open(path, encoding="utf-8", errors="replace") as handle:
            record = module.extract_plant(handle.read())
        if record is None:
            not_plants += 1  # soft 404, empty or non-species page
            continue
        records.append({"url": url, "source": site.name, **record})

    # Family names are normalised over the whole site at once, because a typo
    # is recognised by being rare next to a frequent, almost identical name.
    mapping = family_mapping([record.get("family") or "" for record in records])
    changed = Counter()
    for record in records:
        raw = record.get("family") or ""
        record["family_raw"] = raw or None
        record["family"] = mapping.get(raw)
        if raw and record["family"] != raw:
            changed[(raw, record["family"])] += 1

    out_dir = os.path.join(data_dir, "extracted")
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, site.name + "_plants.jsonl")
    tsv_path = os.path.join(out_dir, site.name + "_plants.tsv")
    # Written to a temporary file and renamed, so a reader (the indexer) never
    # sees a half-written file.
    with open(jsonl_path + ".tmp", "w", encoding="utf-8") as jsonl, open(tsv_path + ".tmp", "w", encoding="utf-8") as tsv:
        tsv.write("\t".join(TSV_COLUMNS) + "\n")
        for record in records:
            jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
            tsv.write("\t".join(flatten(record)) + "\n")
    os.replace(jsonl_path + ".tmp", jsonl_path)
    os.replace(tsv_path + ".tmp", tsv_path)

    families = {record["family"] for record in records if record["family"]}
    print("{}: {} plant records, {} non-plant pages skipped, {} families ({} raw spellings rewritten) -> {}".format(
        site.name, len(records), not_plants, len(families), sum(changed.values()), jsonl_path))
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Regex extraction of plant records from crawled pages")
    parser.add_argument("--site", required=True, choices=sorted(EXTRACTORS) + ["all"])
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--show-family-fixes", action="store_true", help="print every rewritten family spelling")
    args = parser.parse_args(argv)

    for name in (sorted(EXTRACTORS) if args.site == "all" else [args.site]):
        if not os.path.exists(os.path.join(args.data_dir, "state", name, "crawl_log.tsv")):
            print("{}: not crawled yet (no crawl_log.tsv), skipped".format(name))
            continue
        changed = extract_site(config.SITES[name], args.data_dir)
        if args.show_family_fixes:
            for (raw, fixed), count in changed.most_common():
                print("   {:>4}x  {!r} -> {!r}".format(count, raw, fixed))


if __name__ == "__main__":
    sys.exit(main())
