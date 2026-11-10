import os
import shutil
import tempfile
import unittest

from sparkjobs import session


class PathTest(unittest.TestCase):
    def test_local_and_remote_paths(self):
        self.assertTrue(session.is_local("data/spark/joined"))
        self.assertTrue(session.is_local("file:///tmp/x"))
        self.assertTrue(session.is_local("C:\\data\\x"))
        self.assertFalse(session.is_local("hdfs://namenode:8020/user/x"))
        self.assertFalse(session.is_local("hdfs:/user/x"))
        self.assertEqual(session.local_path("file:///tmp/x"), "/tmp/x")
        self.assertEqual(session.local_path("file:/tmp/x"), "/tmp/x")
        self.assertEqual(session.local_path("data/x"), "data/x")


class FreshOutputTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="vinf-test-")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def make(self, *names):
        for name in names:
            path = os.path.join(self.folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()

    def test_an_old_spark_output_is_removed(self):
        self.make("out/part-00000", "out/_SUCCESS", "out/.part-00000.crc")
        out = os.path.join(self.folder, "out")
        self.assertEqual(session.fresh_output(out), out)
        self.assertFalse(os.path.exists(out))

    def test_a_folder_with_other_files_is_kept(self):
        # "--out data" must not delete the crawl.
        self.make("data/raw/page.html", "data/part-00000")
        with self.assertRaises(SystemExit):
            session.fresh_output(os.path.join(self.folder, "data"))
        self.assertTrue(os.path.exists(os.path.join(self.folder, "data", "raw", "page.html")))


if __name__ == "__main__":
    unittest.main()
