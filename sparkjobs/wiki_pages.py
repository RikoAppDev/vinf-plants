"""Spark job: select the Wikipedia pages that can belong to our plants from the whole dump.

Usage:
    python -m sparkjobs.wiki_pages         # -> data/spark/wikipedia/pages/, stats.json
    python -m sparkjobs.wiki_pages --dump data/wikipedia/sample_pages.xml --out data/spark/wikipedia_sample
"""

import argparse
import json
import os
import re
import sys
import time
import zlib

from extractor.normalize import species_key
from tools.merge_entities import entity_key

from .session import add_arguments, get_spark, save_lines, save_text

DUMP = "data/wikipedia/enwiki-20261001-pages-articles.xml.bz2"
ENTITIES = "data/spark/entities"

# "Aucuba (plant)", "Acacia (plant)": a disambiguator is not part of the name.
DISAMBIGUATOR_RE = re.compile(r"\s*\([^)]*\)\s*$")


def name_key(name):
    """Our entity key of a Wikipedia title or Latin name; "" when it is not a plant name."""
    return entity_key(DISAMBIGUATOR_RE.sub("", name or ""))


def our_names(entities):
    """(keys, genera) of our entities: keys, aliases and the species of each name; genera lower-case."""
    keys = set()
    for entity in entities:
        keys.update(key for key in [entity["key"]] + list(entity.get("aliases") or []) if not key.startswith("unparsed:"))
        keys.update(filter(None, (species_key(name) for name in entity.get("scientific_names") or [])))
    return keys, {key.split()[0] for key in keys}


def is_wanted(page, keys, genera):
    """True for a taxobox article whose genus, binomial, title or synonym is ours, or a redirect from one."""
    if page.get("redirect"):
        key = name_key(page["title"])
        return bool(key) and (key in keys or key in genera)
    if not page.get("box"):
        return False
    for genus in (page.get("genus"), page.get("taxon")):
        if genus and genus.lower() in genera:
            return True
    for name in [page.get("binomial"), page["title"]] + list(page.get("synonyms") or []):
        key = name_key(name)
        if key and (key in keys or key in genera):
            return True
    return False


COUNT_NAMES = ("records", "articles", "redirects", "box_articles", "kept_articles", "kept_redirects")


def record_id(record):
    """Identity of a record, to recognise one that was read at the end of a split and again at the start of the next."""
    data = record.encode("utf-8")
    return [len(data), zlib.crc32(data)]


def keep_pages(records, keys, genera, parse_page):
    """The pages of one partition that are kept, the plant articles held back as possible redirect
    targets ({"_candidate": title, "page": page}) and, last, one item
    {"_stats": counts, "_first": [record id, counted names], "_last": [record id, counted names]}."""
    counts = dict.fromkeys(COUNT_NAMES, 0)
    first, last_record, last_hit = None, None, None
    for record in records:
        hit = ["records"]
        page = parse_page(record)
        if page is not None:
            redirect = bool(page.get("redirect"))
            hit.append("redirects" if redirect else "articles")
            if not redirect and page.get("box"):
                hit.append("box_articles")
            if is_wanted(page, keys, genera):
                hit.append("kept_redirects" if redirect else "kept_articles")
                yield page
            elif not redirect and page.get("box") and page.get("plant_hint"):
                yield {"_candidate": page["title"], "page": page}
        for name in hit:
            counts[name] += 1
        if first is None:
            first = [record_id(record), hit]
        last_record, last_hit = record, hit
    last = [record_id(last_record), last_hit] if last_record is not None else None
    yield {"_stats": counts, "_first": first, "_last": last}


def seam_duplicates(stats_items):
    """(number of records read twice, their counts) from the "_stats" items in partition order.

    Hadoop 2.9 reads the first record of the next split twice when a split ends in the delimiter (HADOOP-18321).
    """
    duplicates = dict.fromkeys(COUNT_NAMES, 0)
    seams = 0
    for left, right in zip(stats_items, stats_items[1:]):
        if left["_last"] and right["_first"] and left["_last"][0] == right["_first"][0]:
            seams += 1
            for name in left["_last"][1]:
                duplicates[name] += 1
    return seams, duplicates


def page_counts(stats_items):
    """Page counts of the whole dump, each record counted once."""
    totals = dict.fromkeys(COUNT_NAMES, 0)
    for item in stats_items:
        for name, value in item["_stats"].items():
            totals[name] += value
    seams, duplicates = seam_duplicates(stats_items)
    for name in COUNT_NAMES:
        totals[name] -= duplicates[name]
    totals["seam_duplicates"] = seams
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(description="Select the Wikipedia pages of our plants from the dump")
    parser.add_argument("--dump", default=DUMP, help="dump file (.xml or .xml.bz2), local path or hdfs://")
    parser.add_argument("--entities", default=ENTITIES, help="output of tools.merge_entities or sparkjobs.merge_entities")
    parser.add_argument("--out", default="data/spark/wikipedia")
    add_arguments(parser)
    args = parser.parse_args(argv)

    started = time.time()
    spark = get_spark("vinf-wiki-pages", args.master, args.driver_memory)
    sc = spark.sparkContext
    # About 20 000 short strings: collected on the driver and sent to every executor once.
    keys, genera = our_names(sc.textFile(args.entities).filter(lambda line: line.strip()).map(json.loads).collect())
    names = sc.broadcast((keys, genera))
    print("our names: {} keys, {} genera".format(len(keys), len(genera)))

    pages = sc.newAPIHadoopFile(
        args.dump,
        "org.apache.hadoop.mapreduce.lib.input.TextInputFormat",
        "org.apache.hadoop.io.LongWritable",
        "org.apache.hadoop.io.Text",
        # Spark 2.4 builds this conf from a fresh core-site.xml, so the session's fs.defaultFS is passed on.
        conf={"textinputformat.record.delimiter": "</page>",
              "fs.defaultFS": sc._jsc.hadoopConfiguration().get("fs.defaultFS")},
    ).values()

    def partition(records):
        from wikipedia.wikitext import parse_page

        wanted_keys, wanted_genera = names.value
        return keep_pages(records, wanted_keys, wanted_genera, parse_page)

    from pyspark import StorageLevel

    # Persisted so the dump is scanned once for the pages, the held-back articles and the counts.
    items = pages.mapPartitions(partition).persist(StorageLevel.MEMORY_AND_DISK)
    totals = page_counts(items.filter(lambda item: "_stats" in item).collect())
    wanted = items.filter(lambda item: "_stats" not in item and "_candidate" not in item)
    targets = sc.broadcast(set(wanted.filter(lambda page: page.get("redirect"))
                               .map(lambda page: page["redirect"]).collect()))
    extra = items.filter(lambda item: "_candidate" in item and item["_candidate"] in targets.value) \
        .map(lambda item: item["page"])
    selected = wanted.union(extra).map(lambda page: (page["page_id"], page)).reduceByKey(lambda a, b: a) \
        .sortByKey().values().persist(StorageLevel.MEMORY_AND_DISK)
    kinds = selected.map(lambda page: "kept_redirects" if page.get("redirect") else "kept_articles").countByValue()
    totals["kept_articles"] = kinds.get("kept_articles", 0)
    totals["kept_redirects"] = kinds.get("kept_redirects", 0)
    totals["kept_redirect_targets"] = extra.map(lambda page: page["page_id"]).distinct().count()
    save_lines(selected.map(lambda page: json.dumps(page, ensure_ascii=False)), os.path.join(args.out, "pages"))
    totals["partitions"] = pages.getNumPartitions()
    totals["seconds"] = round(time.time() - started, 1)
    save_text(sc, os.path.join(args.out, "stats.json"), json.dumps(totals, indent=2))
    print(json.dumps(totals, indent=2))
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
