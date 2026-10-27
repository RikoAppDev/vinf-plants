"""Field coverage of the extracted records, per source (the table for the report).

Usage:
    python -m tools.coverage

A field counts as covered when it is not None, not an empty string and not an
empty list. Writes data/stats/coverage.md.
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

FIELDS = (
    "scientific_name", "authority", "family", "genus", "common_names", "synonyms",
    "zone_min", "height_max_cm", "description",
    # site-specific typed fields
    "edibility_rating", "medicinal_rating", "habit", "leaf_type",
    "conservation_code", "rhs_hardiness", "distribution",
    "density_kg_m3", "janka_hardness_n", "iucn_status",
)


def covered(value):
    return value not in (None, "", [], {})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Field coverage of extracted records")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    counts, totals, words = {}, Counter(), {}
    for path in sorted(glob.glob(os.path.join(args.data_dir, "extracted", "*_plants.jsonl"))):
        source = os.path.basename(path)[:-len("_plants.jsonl")]
        counts[source] = Counter()
        lengths = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                totals[source] += 1
                lengths.append(len((record.get("description") or "").split()))
                for field in FIELDS:
                    if field in record:
                        counts[source][field] += covered(record[field])
                    else:
                        counts[source][field] = counts[source].get(field)  # field not produced by this extractor
        lengths.sort()
        words[source] = lengths[len(lengths) // 2] if lengths else 0

    sources = sorted(counts)
    lines = ["| field | " + " | ".join("{} (n={})".format(s, totals[s]) for s in sources) + " |",
             "|---|" + "---|" * len(sources)]
    for field in FIELDS:
        cells = []
        for source in sources:
            value = counts[source].get(field)
            cells.append("–" if value is None else "{:.0f} %".format(100.0 * value / totals[source]))
        if any(cell != "–" for cell in cells):
            lines.append("| {} | {} |".format(field, " | ".join(cells)))
    lines.append("| median words of description | {} |".format(" | ".join(str(words[s]) for s in sources)))
    report = "\n".join(lines) + "\n"
    os.makedirs(os.path.join(args.data_dir, "stats"), exist_ok=True)
    with open(os.path.join(args.data_dir, "stats", "coverage.md"), "w", encoding="utf-8") as handle:
        handle.write(report)
    print(report)


if __name__ == "__main__":
    sys.exit(main())
