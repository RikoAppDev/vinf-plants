"""Spark job: merge the extracted records of all sites into entities, the Spark form of tools/merge_entities.py.

Usage:
    python -m sparkjobs.merge_entities     # -> data/spark/entities/, data/spark/entities_stats.md
    python -m sparkjobs.merge_entities --input data/spark/extracted --out data/spark/entities
"""

import argparse
import json
import os
import sys
import time

from tools.merge_entities import (build_entity, entity_member, entity_profile, join_synonyms, merge_stats,
                                  record_key, stats_markdown, synonym_edges)

from .session import add_arguments, get_spark, save_lines, save_text


def numbered_record(row):
    """((site, part file, line number), record) of a (file path, line number, line) row."""
    path, number, line = row
    site, part = path.rstrip("/").split("/")[-2:]
    return (site, part, number), json.loads(line)


def read_numbered_records(spark, input_dir):
    """Records of <input_dir>/<site>/part-* with their position (Spark does not keep the line order).

    Part files are cut into lines in the JVM: whole files of several MB in Python failed with
    "No buffer space available" on macOS.
    """
    from pyspark.sql.functions import input_file_name, posexplode, split

    # Without this Spark 4 looks for _spark_metadata under the literal glob and logs a stack trace.
    spark.conf.set("spark.sql.streaming.fileStreamSink.ignoreMetadata", "true")
    rows = (spark.read.text(os.path.join(input_dir, "*", "part-*"), wholetext=True)
            .select(input_file_name(), posexplode(split("value", "\n"))))
    return rows.rdd.filter(lambda row: row[2]).map(numbered_record)


def keyed_edges(position, key, record):
    """(alias, (position of the synonym, record key)) for the listed synonyms that have a key."""
    return [(alias, (position + (index,), key))
            for index, (alias, _key) in enumerate(synonym_edges(record, key)) if alias]


def by_record_key(joined):
    alias, ((position, key), alias_sources) = joined
    return key, (position, alias, alias_sources)


def edge_with_sources(joined):
    key, ((position, alias, alias_sources), sources) = joined
    return position, alias, alias_sources, key, sources


def resolve_synonyms(edges):
    """({key: root} of merged keys, merges); edges (position, alias, sources, key, sources) are sorted first."""
    key_sources = {}
    for _position, alias, alias_sources, key, sources in edges:
        key_sources[alias] = alias_sources
        key_sources[key] = sources
    ordered = sorted(edges, key=lambda edge: edge[0])
    groups, merges = join_synonyms([(alias, key) for _position, alias, _a, key, _k in ordered], key_sources)
    roots = {key: groups.find(key) for key in key_sources}
    return {key: root for key, root in roots.items() if root != key}, merges


def numbered_entity(indexed):
    (root, members), index = indexed
    return build_entity(index + 1, root, members)


def merge(spark, input_dir):
    """(RDD of entity dicts in entity_id order, statistics dict)."""
    sc = spark.sparkContext
    keyed = (read_numbered_records(spark, input_dir)
             .map(lambda item: (item[0], record_key(item[1]), item[1]))
             .persist())
    key_sources = keyed.map(lambda item: (item[1], {item[2]["source"]})).reduceByKey(lambda a, b: a | b)

    # The joins keep edges whose alias has a record: 966 on the full data, few enough for the
    # sequential union-find on the driver.
    edges = (keyed.flatMap(lambda item: keyed_edges(*item))
             .join(key_sources)
             .map(by_record_key)
             .join(key_sources)
             .map(edge_with_sources)
             .collect())
    roots, merges = resolve_synonyms(edges)
    root_of = sc.broadcast(roots)

    entities = (keyed.map(lambda item: (root_of.value.get(item[1], item[1]), entity_member(item[2], item[1])))
                .groupByKey()
                .sortByKey()
                .zipWithIndex()
                .map(numbered_entity)
                .persist())
    documents = keyed.map(lambda item: item[2]["source"]).countByValue()
    profiles = entities.map(entity_profile).countByValue()
    keyed.unpersist()
    print("{} synonym edges collected on the driver, {} merges".format(len(edges), merges))
    return entities, merge_stats(documents, profiles, merges)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spark merge of the plant records of all sites into entities")
    parser.add_argument("--input", default="data/spark/extracted", help="folder with <site>/part-* record files")
    parser.add_argument("--out", default="data/spark/entities", help="entities go to <out>/, the report to <out>_stats.md")
    add_arguments(parser)
    args = parser.parse_args(argv)

    started = time.time()
    spark = get_spark("vinf-merge-entities", args.master, args.driver_memory)
    sc = spark.sparkContext
    entities, stats = merge(spark, args.input)
    out = args.out.rstrip("/")
    save_lines(entities.map(lambda entity: json.dumps(entity, ensure_ascii=False)), out)
    report = stats_markdown(stats)
    # save_text ends the file with a newline; the report already has one.
    save_text(sc, out + "_stats.md", report.rstrip("\n"))
    print(report)
    print("merge done in {:.1f} s".format(time.time() - started))
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
