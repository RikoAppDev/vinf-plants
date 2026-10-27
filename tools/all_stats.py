"""Crawl statistics of every site in one run (the table for the report).

Usage:
    python -m tools.all_stats [--tokens]

Runs tools.stats for each crawled site and stores the output in
data/stats/<site>.txt, so the numbers in the report can be traced to a file.
"""

import argparse
import contextlib
import io
import os
import sys

from crawler import config

from . import stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Statistics of all crawled sites")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--tokens", action="store_true", help="also count tiktoken tokens (slow)")
    args = parser.parse_args(argv)

    out_dir = os.path.join(args.data_dir, "stats")
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(config.SITES):
        if not os.path.exists(os.path.join(args.data_dir, "state", name, "crawl_log.tsv")):
            continue
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats.main(["--site", name, "--data-dir", args.data_dir] + (["--tokens"] if args.tokens else []))
        with open(os.path.join(out_dir, name + ".txt"), "w", encoding="utf-8") as handle:
            handle.write(buffer.getvalue())
        print(buffer.getvalue())


if __name__ == "__main__":
    sys.exit(main())
