"""Run every step after the crawl: extraction, merging, index, idf comparison, coverage.

Usage:
    python -m tools.pipeline

The steps are the same commands as in the README, run one after another so the
records, the entities and the index always come from the same extraction.
"""

import argparse
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
    parser = argparse.ArgumentParser(
        description="Run every step after the crawl, in this order: " + ", ".join(name for name, _, _ in STEPS)
                    + ". Reads and writes data/ in the current directory; stops at the first step that fails.")
    parser.parse_args(argv)
    for name, step, arguments in STEPS:
        print("=== {}".format(name), flush=True)
        code = step(arguments)
        if code:
            # The step has already printed its one-line reason on stderr.
            return code


if __name__ == "__main__":
    sys.exit(main())
