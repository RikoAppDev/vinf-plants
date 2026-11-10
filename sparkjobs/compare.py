"""Check that the Spark jobs give the same records and entities, in the same order, as the
single-process run; exits with 1 when anything differs.

Usage:
    python -m sparkjobs.compare
    python -m sparkjobs.compare --spark-dir data/spark --reference data/extracted
"""

import argparse
import json
import os
import sys
from operator import add

from .session import add_arguments, get_spark

SITES = ("ncsu", "pfaf", "tso", "wooddb")


def canonical(line):
    return json.dumps(json.loads(line), sort_keys=True, ensure_ascii=False)


def compare_json_lines(sc, ours, reference):
    """(objects in ours, objects in reference, differing objects, up to 2 of them, lines out of order)."""
    def counted(path):
        return sc.textFile(path).map(lambda line: (canonical(line), 1)).reduceByKey(add)

    def indexed(path):
        return sc.textFile(path).zipWithIndex().map(lambda pair: (pair[1], canonical(pair[0])))

    ours_counts, reference_counts = counted(ours), counted(reference)
    differing = ours_counts.fullOuterJoin(reference_counts).filter(lambda pair: pair[1][0] != pair[1][1])
    out_of_order = indexed(ours).fullOuterJoin(indexed(reference)).filter(lambda pair: pair[1][0] != pair[1][1])
    return (ours_counts.values().sum(), reference_counts.values().sum(), differing.count(), differing.take(2),
            out_of_order.count())


def report(name, result):
    ours, reference, differing, examples, out_of_order = result
    if differing:
        verdict = "{} objects differ".format(differing)
    elif out_of_order:
        verdict = "same objects, {} lines in another order".format(out_of_order)
    else:
        verdict = "identical"
    print("{:10} spark {:>6}  single-process {:>6}  {}".format(name, ours, reference, verdict))
    for line, (count_ours, count_reference) in examples:
        print("    {}x in spark, {}x in single-process: {}".format(count_ours or 0, count_reference or 0, line[:300]))
    return differing == 0 and out_of_order == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare the Spark outputs with the single-process outputs")
    parser.add_argument("--spark-dir", default="data/spark")
    parser.add_argument("--reference", default="data/extracted")
    parser.add_argument("--site", action="append", choices=SITES, help="sites to compare (default all four)")
    add_arguments(parser)
    args = parser.parse_args(argv)

    spark = get_spark("vinf-compare", args.master, args.driver_memory)
    sc = spark.sparkContext
    checks = []
    for site in args.site or SITES:
        checks.append(report(site, compare_json_lines(
            sc, os.path.join(args.spark_dir, "extracted", site, "part-*"),
            os.path.join(args.reference, site + "_plants.jsonl"))))
    checks.append(report("entities", compare_json_lines(
        sc, os.path.join(args.spark_dir, "entities", "part-*"), os.path.join(args.reference, "entities.jsonl"))))
    checks.append(sc.textFile(os.path.join(args.spark_dir, "entities_stats.md")).collect() ==
                  sc.textFile(os.path.join(args.reference, "entities_stats.md")).collect())
    print("{:10} {}".format("report", "identical" if checks[-1] else "DIFFERS"))
    spark.stop()
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
