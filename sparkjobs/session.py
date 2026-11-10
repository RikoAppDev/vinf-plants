"""Spark session and output helpers shared by the jobs; the project packages go to the executors as a zip."""

import atexit
import os
import re
import shutil
import sys
import tempfile
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED_PACKAGES = ("crawler", "extractor", "indexer", "tools", "wikipedia", "sparkjobs")
# "hdfs://host/x", "hdfs:/x", "s3a://b/x"; one letter is a Windows drive ("C:\data").
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
# What a Spark text output folder holds; anything else means the path is not an old output.
SPARK_OUTPUT_RE = re.compile(r"^(?:part-\d+.*|_SUCCESS|_temporary|\..*\.crc)$")


def add_arguments(parser):
    parser.add_argument("--master", help="Spark master, e.g. local[4] or spark://host:7077 (default local[*])")
    parser.add_argument("--driver-memory", default="4g", help="driver memory when started with python -m")


def project_zip():
    """Zip of the project packages (.py and .txt files) in a temporary folder."""
    folder = tempfile.mkdtemp(prefix="vinf-spark-")
    atexit.register(shutil.rmtree, folder, True)
    path = os.path.join(folder, "vinf_plants.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for package in SHIPPED_PACKAGES:
            for folder, _dirs, files in os.walk(os.path.join(PROJECT_ROOT, package)):
                for name in files:
                    if name.endswith((".py", ".txt")):
                        full = os.path.join(folder, name)
                        archive.write(full, os.path.relpath(full, PROJECT_ROOT))
    return path


def is_local(path):
    return not SCHEME_RE.match(path) or path.startswith("file:")


def local_path(path):
    """'file:///tmp/x' -> '/tmp/x'; a plain path stays as it is."""
    return re.sub(r"^file:(?://)?", "", path) if path.startswith("file:") else path


def fresh_output(path):
    """The path, after removing a local output folder of an earlier run (Spark refuses to overwrite one).

    A folder that holds other files stops the job, so a wrong --out ("data", ".") deletes nothing.
    """
    local = local_path(path)
    if is_local(path) and os.path.isdir(local):
        foreign = sorted(name for name in os.listdir(local) if not SPARK_OUTPUT_RE.match(name))
        if foreign:
            raise SystemExit("refusing to replace {}: it is not a Spark output folder (holds {})".format(
                local, ", ".join(foreign[:5])))
        shutil.rmtree(local)
    return path


def save_lines(rdd, path):
    """Write an RDD of strings as a text output folder, like saveAsTextFile.

    A local folder is written by the driver: in the emulated course image Hadoop's `chmod`
    processes never end and saveAsTextFile hangs. HDFS paths keep saveAsTextFile.
    """
    if not is_local(path):
        rdd.saveAsTextFile(path)
        return
    from pyspark import StorageLevel

    local = fresh_output(local_path(path))
    os.makedirs(local)
    rdd = rdd.persist(StorageLevel.MEMORY_AND_DISK)
    expected = rdd.count()
    written = 0
    with open(os.path.join(local, "part-00000"), "w", encoding="utf-8") as handle:
        for line in rdd.toLocalIterator():
            handle.write(line + "\n")
            written += 1
    # Spark 2.4's toLocalIterator does not raise a failed partition, it just ends early.
    if written != expected:
        raise RuntimeError("{}: wrote {} of {} lines".format(local, written, expected))
    open(os.path.join(local, "_SUCCESS"), "w").close()
    rdd.unpersist()


def save_text(sc, path, text):
    """A small result (statistics) as one file: directly when local, as a one-part output on HDFS."""
    if is_local(path):
        with open(local_path(path), "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        sc.parallelize([text], 1).saveAsTextFile(path)


def get_spark(app_name, master=None, driver_memory="4g"):
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name)
    # spark-submit starts the JVM first and passes its port to Python.
    if "PYSPARK_GATEWAY_PORT" not in os.environ:
        builder = builder.master(master or "local[*]").config("spark.driver.memory", driver_memory)
        if (master or "local").startswith("local"):
            # The workers must run this interpreter, not whatever "python3" is first on PATH.
            os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
            # The web UI cannot serve its files from a path with spaces and accents (this folder).
            builder = builder.config("spark.ui.enabled", "false")
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    spark.sparkContext.addPyFile(project_zip())
    return spark
