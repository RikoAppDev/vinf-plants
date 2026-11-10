"""Spark job: extract the plant records from the crawled pages, the Spark form of extractor/run.py.

Usage:
    python -m sparkjobs.extract_sites      # -> data/spark/extracted/<site>/
    python -m sparkjobs.extract_sites --site pfaf --data-dir data --out data/spark
"""

import argparse
import importlib
import io
import json
import os
import sys
import time
from urllib.parse import unquote

from crawler import config
from extractor.normalize import family_mapping
from extractor.run import EXTRACTORS, select_pages

from .session import add_arguments, get_spark, is_local, local_path, save_lines


def files_by_name(pages):
    """File name -> [(position in the crawl log, url)] of the selected (url, file name) pages."""
    selected = {}
    for position, (url, name) in enumerate(pages):
        selected.setdefault(name, []).append((position, url))
    return selected


def page_text(content):
    """The page as extractor.run reads it: text mode also turns \\r\\n and \\r into \\n."""
    return io.TextIOWrapper(io.BytesIO(content), encoding="utf-8", errors="replace").read()


def read_pages(spark, folder):
    """RDD of (file URI, bytes) of the files in folder, the bytes exactly as stored.

    Whole-file text read in about 5 s; sc.binaryFiles took 300 s and sc.wholeTextFiles (160 s)
    decodes malformed UTF-8 differently from Python.
    """
    from pyspark.sql.functions import col, input_file_name

    return spark.read.text(folder, wholetext=True).select(input_file_name(), col("value").cast("binary")).rdd


def page_records(pages, module_name, source, selected):
    """(position, record) for the selected files among (URI, bytes) pairs; record None = not a plant."""
    extractor = importlib.import_module(module_name)
    for path, content in pages:
        targets = selected.get(unquote(path.rsplit("/", 1)[-1]))
        if not targets:
            continue
        record = extractor.extract_plant(page_text(content))
        for position, url in targets:
            yield position, None if record is None else {"url": url, "source": source, **record}


def families_in_order(counts):
    """Raw family list for family_mapping from (raw, (count, first position)) pairs.

    Same counts and first-occurrence order, so the same mapping as all records in crawl log order.
    """
    families = []
    for raw, (count, _first) in sorted(counts, key=lambda item: item[1][1]):
        families.extend([raw] * count)
    return families


def with_family(item, mapping):
    position, record = item
    raw = record.get("family") or ""
    record["family_raw"] = raw or None
    record["family"] = mapping.get(raw)
    return position, record


def extract_site(spark, site, data_dir, out_dir):
    started = time.time()
    sc = spark.sparkContext
    source, module_name = site.name, EXTRACTORS[site.name]
    log_lines = sc.textFile(os.path.join(data_dir, "state", source, "crawl_log.tsv")).collect()
    pages, skipped = select_pages(site, log_lines)
    if skipped:
        print("{}: {} redirect duplicates skipped".format(source, skipped))
    selected = sc.broadcast(files_by_name(pages))

    found = (read_pages(spark, os.path.join(data_dir, "raw", source))
             .mapPartitions(lambda files: page_records(files, module_name, source, selected.value))
             .persist())
    found_count = found.count()
    if found_count != len(pages):
        raise RuntimeError("{}: {} of the {} saved pages in the crawl log are missing in {}".format(
            source, len(pages) - found_count, len(pages), os.path.join(data_dir, "raw", source)))
    plants = found.filter(lambda item: item[1] is not None)

    # Family names are normalised over the whole site at once (see extractor.run).
    counts = (plants.map(lambda item: (item[1].get("family") or "", (1, item[0])))
              .reduceByKey(lambda a, b: (a[0] + b[0], min(a[1], b[1])))
              .collect())
    mapping = family_mapping(families_in_order(counts))
    shared_mapping = sc.broadcast(mapping)

    out_path = os.path.join(out_dir, "extracted", source)
    save_lines(plants.map(lambda item: with_family(item, shared_mapping.value))
               .sortByKey(numPartitions=sc.defaultParallelism)
               .map(lambda item: json.dumps(item[1], ensure_ascii=False)), out_path)
    found.unpersist()

    records = sum(count for _raw, (count, _first) in counts)
    families = {mapping[raw] for raw, _counts in counts if mapping.get(raw)}
    rewritten = sum(count for raw, (count, _first) in counts if raw and mapping.get(raw) != raw)
    print("{}: {} plant records, {} non-plant pages skipped, {} families ({} raw spellings rewritten) -> {} ({:.1f} s)"
          .format(source, records, len(pages) - records, len(families), rewritten, out_path, time.time() - started),
          flush=True)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spark extraction of plant records from crawled pages")
    parser.add_argument("--site", default="all", choices=sorted(EXTRACTORS) + ["all"])
    parser.add_argument("--data-dir", default="data", help="folder with raw/ and state/, local path or hdfs://")
    parser.add_argument("--out", default="data/spark", help="records go to <out>/extracted/<site>/")
    add_arguments(parser)
    args = parser.parse_args(argv)

    started = time.time()
    spark = get_spark("vinf-extract-sites", args.master, args.driver_memory)
    for name in (sorted(EXTRACTORS) if args.site == "all" else [args.site]):
        log_path = os.path.join(args.data_dir, "state", name, "crawl_log.tsv")
        if is_local(log_path) and not os.path.exists(local_path(log_path)):
            print("{}: not crawled yet (no crawl_log.tsv), skipped".format(name))
            continue
        extract_site(spark, config.SITES[name], args.data_dir, args.out)
    print("extraction done in {:.1f} s".format(time.time() - started))
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
