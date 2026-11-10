#!/bin/bash
# Run one Spark job with spark-submit in the course image (Spark 2.4.3, Java 8, Hadoop 2.9.2).
#
#   ./spark_docker.sh sparkjobs.wiki_pages --dump data/wikipedia/sample_pages.xml --out data/spark/wikipedia_sample
#
# The project is mounted at /vinf, so relative paths mean the same files as on the host.
# fs.defaultFS=file:/// makes plain paths local instead of the image's HDFS; hdfs:// still works.
# The image is amd64; on an ARM Mac Docker emulates it (slower, same results).
set -e
cd "$(dirname "$0")"
IMAGE=iisas/hadoop-spark-pig-hive:2.9.2
MEMORY=${SPARK_DRIVER_MEMORY:-3g}
exec docker run --rm --init --platform linux/amd64 \
  -v "$PWD":/vinf -w /vinf \
  -e PYSPARK_PYTHON=python3 -e PYTHONIOENCODING=utf-8 \
  --entrypoint /usr/local/spark/bin/spark-submit \
  "$IMAGE" \
  --master "local[*]" --driver-memory "$MEMORY" \
  --conf spark.hadoop.fs.defaultFS=file:/// \
  tools/run_module.py "$@"
