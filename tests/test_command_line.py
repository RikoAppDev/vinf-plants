"""Command line entry points without data: one line on stderr, exit code 2, nothing written."""

import contextlib
import io
import os
import sys
import tempfile
import unittest

from indexer import compare, search
from tools import all_stats, coverage, merge_entities, pipeline


def run_main(main, argv):
    """(exit code, stdout, stderr) of main(argv); SystemExit counts as an exit code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class EmptyDataTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.argv = ["--data-dir", self.folder.name]

    def assert_one_line(self, result, *words):
        code, out, err = result
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertNotIn("Traceback", err)
        for word in words:
            self.assertIn(word, err)

    def assert_nothing_written(self):
        self.assertEqual(os.listdir(self.folder.name), [])

    def test_search_without_index(self):
        self.assert_one_line(run_main(search.main, ["oak"] + self.argv),
                             "no complete index", "python -m indexer.build")
        self.assert_nothing_written()

    def test_compare_without_index(self):
        self.assert_one_line(run_main(compare.main, self.argv),
                             "no complete index", "python -m indexer.build")
        self.assert_nothing_written()

    def test_index_still_raises_as_a_library(self):
        with self.assertRaises(FileNotFoundError):
            search.Index(os.path.join(self.folder.name, "index"))

    def test_merge_entities_without_records(self):
        self.assert_one_line(run_main(merge_entities.main, self.argv),
                             "_plants.jsonl", "python -m extractor.run --site all")
        self.assert_nothing_written()

    def test_coverage_without_records(self):
        self.assert_one_line(run_main(coverage.main, self.argv),
                             "no extracted records", "python -m extractor.run --site all")
        self.assert_nothing_written()

    def test_all_stats_without_crawl_logs(self):
        self.assert_one_line(run_main(all_stats.main, self.argv + ["--tokens"]),
                             "no crawl logs", "python -m crawler.crawl")
        self.assert_nothing_written()


class PipelineTest(unittest.TestCase):
    def test_help_does_not_run_the_steps(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = os.getcwd()
            os.chdir(folder)
            try:
                code, out, _ = run_main(pipeline.main, ["--help"])
                self.assertEqual(code, 0)
                self.assertIn("merge entities", out)
                self.assertNotIn("===", out)
                self.assertEqual(os.listdir(folder), [])
            finally:
                os.chdir(previous)

    def test_stops_with_the_message_of_the_failing_step(self):
        calls = []

        def failing(argv):
            calls.append("failing")
            print("no input", file=sys.stderr)
            return 2

        def never(argv):
            calls.append("never")

        original = pipeline.STEPS
        pipeline.STEPS = (("first", failing, []), ("second", never, []))
        self.addCleanup(setattr, pipeline, "STEPS", original)
        code, _, err = run_main(pipeline.main, [])
        self.assertEqual(code, 2)
        self.assertEqual(err, "no input\n")
        self.assertEqual(calls, ["failing"])


if __name__ == "__main__":
    unittest.main()
