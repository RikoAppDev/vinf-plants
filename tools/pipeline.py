"""Run every step after the crawl: extraction, merging, index, idf comparison, coverage.

Usage:
    python -m tools.pipeline

The steps are the same commands as in the README, run one after another so the
records, the entities and the index always come from the same extraction.
"""

import sys

from extractor import run as extract
from indexer import build, compare

from . import coverage, merge_entities

STEPS = (
    ("extract", extract.main, ["--site", "all"]),
    ("merge entities", merge_entities.main, []),
    ("build index", build.main, []),
    ("compare idf", compare.main, []),
    ("coverage", coverage.main, []),
)


def main(argv=None):
    for name, step, arguments in STEPS:
        print("=== {}".format(name), flush=True)
        step(arguments)


if __name__ == "__main__":
    sys.exit(main())
