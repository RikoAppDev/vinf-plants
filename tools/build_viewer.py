"""Build a self-contained HTML viewer of the extracted plant records.

Usage:
    python -m tools.build_viewer --site ncsu
    -> data/viewer/index.html + data/viewer/chunks/NNN.js
       (open index.html directly from disk, no server needed)

The page embeds only a light record per plant (what the list and the filters
need). The full attribute sets live in chunk files that the page loads with a
<script src> tag the first time a plant from that chunk is opened - fetch()
is blocked for file:// pages, script tags are not.
"""

import argparse
import glob
import json
import os
import statistics
import sys
from datetime import datetime

from crawler import config
from crawler.storage import file_name_for

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "viewer_template.html")

# (attribute label on the source page, label shown in the filter panel)
FACETS = (
    ("Plant Type", "Plant type"),
    ("Light", "Light"),
    ("Woody Plant Leaf Characteristics", "Woody plant leaves"),
    ("Soil Texture", "Soil texture"),
    ("Soil Drainage", "Soil drainage"),
    ("Maintenance", "Maintenance"),
    ("Growth Rate", "Growth rate"),
    ("Resistance To Challenges", "Resistant to"),
    ("Attracts", "Attracts"),
)
# Attribute labels kept in the light record for the TSV export only.
EXTRA_LIST_FIELDS = ("Soil pH",)
LIST_FIELDS = tuple(key for key, _label in FACETS) + EXTRA_LIST_FIELDS

CHUNK_SIZE = 500
LIGHT_KEYS = ("url", "scientific_name", "common_names", "synonyms", "genus", "species", "family",
              "height_min_cm", "height_max_cm", "width_min_cm", "width_max_cm", "zone_min", "zone_max")


def load_records(jsonl_path):
    with open(jsonl_path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def light_record(record):
    """The part of a record the list, the filters and the export need."""
    light = {key: record.get(key) for key in LIGHT_KEYS}
    light["file"] = file_name_for(record["url"])
    light["facets"] = {key: record["attributes"][key] for key in LIST_FIELDS if key in record["attributes"]}
    light["attr_count"] = len(record["attributes"])
    return light


def build_meta(records, site, extracted_at):
    return {
        "site": site.name,
        "source_host": site.base_url.split("//", 1)[-1],
        "extracted_at": extracted_at,
        "count": len(records),
        "families": len({record["family"] for record in records if record["family"]}),
        "genera": len({record["genus"] for record in records if record["genus"]}),
        "median_attributes": int(statistics.median(len(record["attributes"]) for record in records)) if records else 0,
        "raw_dir": "../raw/{}/".format(site.name),
        "facets": [{"key": key, "label": label} for key, label in FACETS],
        "list_fields": list(LIST_FIELDS),
        "chunk_size": CHUNK_SIZE,
        "chunk_count": (len(records) + CHUNK_SIZE - 1) // CHUNK_SIZE,
        "chunks_dir": "chunks/",
    }


def embed_json(value):
    # "</script>" inside a string value would terminate the script element.
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def build_html(template, records, meta):
    return (template
            .replace("__PLANT_DATA__", embed_json([light_record(record) for record in records]))
            .replace("__PLANT_META__", embed_json(meta)))


def chunk_name(number):
    return "{:03d}.js".format(number)


def chunk_js(number, records):
    """One chunk: the full attribute sets, delivered through a JSONP-style callback."""
    return "window.__plantChunk({}, {});\n".format(number, embed_json([record["attributes"] for record in records]))


def write_viewer(template, records, meta, out_dir):
    chunks_dir = os.path.join(out_dir, meta["chunks_dir"])
    os.makedirs(chunks_dir, exist_ok=True)
    for stale in glob.glob(os.path.join(chunks_dir, "*.js")):
        os.remove(stale)  # derived files only, never crawled data
    for number in range(meta["chunk_count"]):
        batch = records[number * CHUNK_SIZE:(number + 1) * CHUNK_SIZE]
        with open(os.path.join(chunks_dir, chunk_name(number)), "w", encoding="utf-8") as handle:
            handle.write(chunk_js(number, batch))
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(build_html(template, records, meta))
    return index_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the HTML viewer of extracted plant records")
    parser.add_argument("--site", required=True, choices=sorted(config.SITES))
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    site = config.SITES[args.site]
    jsonl_path = os.path.join(args.data_dir, "extracted", site.name + "_plants.jsonl")
    records = load_records(jsonl_path)
    extracted_at = datetime.fromtimestamp(os.path.getmtime(jsonl_path)).strftime("%d %b %Y")
    with open(TEMPLATE_PATH, encoding="utf-8") as handle:
        template = handle.read()

    meta = build_meta(records, site, extracted_at)
    index_path = write_viewer(template, records, meta, os.path.join(args.data_dir, "viewer"))
    print("{} records -> {} ({:.1f} MB) + {} chunk files".format(
        len(records), index_path, os.path.getsize(index_path) / 1e6, meta["chunk_count"]))


if __name__ == "__main__":
    sys.exit(main())
