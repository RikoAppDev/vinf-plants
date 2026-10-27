"""Merge extracted records of the same plant from several sites into entities.

Usage:
    python -m tools.merge_entities

Reads data/extracted/<site>_plants.jsonl, writes data/extracted/entities.jsonl
and data/extracted/entities_stats.md.

Entity key = normalised scientific name: "genus epithet", plus the
infraspecific rank or the cultivar name when the page is about one
("quercus robur", "quercus robur 'fastigiata'"). Synonyms listed on a page are
aliases: a PFAF page "Ficaria verna" joins the NCSU page "Ranunculus ficaria"
that lists "Ficaria verna" as a former name. Two different pages of the same
site are never merged, so an ambiguous synonym cannot collapse two plants.
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations

from extractor.normalize import BINOMIAL_RE, species_key

GENUS_RE = re.compile(r"^\s*(?:[x×]\s+)?([A-Z][a-z]{2,})\b")

# Everything that only changes how a qualifier is typed, not which plant it is.
QUALIFIER_NOISE_RE = re.compile(r"[®™'‘’\"().,]+")


def entity_key(name):
    """Species (or genus) key plus the qualifier that follows it; "" when the name has no genus.

    The qualifier (variety, cultivar, group, trade series, second hybrid parent) is part of the
    identity: "Brassica oleracea Kale Group" is another plant than "Brassica oleracea". The
    authority is a separate record field, so the remainder is never an author name.
    """
    name = (name or "").replace("×", " × ")
    base = species_key(name)
    match = BINOMIAL_RE.match(name)
    if not base:
        # Genus-level pages: "Abelia 'Edward Goucher'", "Acer Group X", "Hosta".
        match = GENUS_RE.match(name)
        if not match:
            return ""
        base = match.group(1).lower()
    rest = name[match.end():]
    rest = " ".join(QUALIFIER_NOISE_RE.sub(" ", rest).lower().split())
    rest = re.sub(r"\bssp\b", "subsp", rest)
    return base + (" " + rest if rest else "")


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def load_records(extracted_dir):
    records = []
    for path in sorted(glob.glob(os.path.join(extracted_dir, "*_plants.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            records.extend(json.loads(line) for line in handle)
    return records


def merge(records):
    """Returns (entities, statistics dict)."""
    key_sources = defaultdict(lambda: defaultdict(set))  # key -> source -> urls
    for record in records:
        key = entity_key(record.get("scientific_name", "")) or "unparsed:" + record["url"]
        record["_key"] = key
        key_sources[key][record["source"]].add(record["url"])

    groups = UnionFind()
    root_sources = {key: set(sources) for key, sources in key_sources.items()}  # root -> sources in its group

    synonym_merges = 0
    for record in records:
        for synonym in record.get("synonyms") or []:
            alias = entity_key(synonym)
            if not alias or alias not in key_sources:
                continue
            a, b = groups.find(alias), groups.find(record["_key"])
            # Never merge two different pages of one site.
            if a == b or root_sources[a] & root_sources[b]:
                continue
            groups.union(a, b)
            root_sources[b] |= root_sources.pop(a)
            synonym_merges += 1

    entities = defaultdict(lambda: {"keys": set(), "names": set(), "sources": defaultdict(list)})
    for record in records:
        entity = entities[groups.find(record["_key"])]
        entity["keys"].add(record["_key"])
        entity["names"].add(record.get("scientific_name", ""))
        entity["sources"][record["source"]].append(record["url"])

    result = []
    for number, (root, entity) in enumerate(sorted(entities.items()), 1):
        result.append({
            "entity_id": number,
            "key": root,
            "aliases": sorted(entity["keys"] - {root}),
            "scientific_names": sorted(entity["names"]),
            "sources": {source: sorted(urls) for source, urls in sorted(entity["sources"].items())},
            "n_sources": len(entity["sources"]),
        })

    documents = Counter(record["source"] for record in records)
    by_n_sources = Counter(entity["n_sources"] for entity in result)
    sources = sorted(documents)
    pairs = {(a, b): sum(1 for e in result if a in e["sources"] and b in e["sources"])
             for a, b in combinations(sources, 2)}
    stats = {
        "documents": dict(documents),
        "entities_per_source": {s: sum(1 for e in result if s in e["sources"]) for s in sources},
        "entities": len(result),
        "unparsed_names": sum(1 for e in result if e["key"].startswith("unparsed:")),
        "synonym_merges": synonym_merges,
        "by_n_sources": dict(sorted(by_n_sources.items())),
        "pairs": {"{} & {}".format(a, b): n for (a, b), n in pairs.items()},
    }
    return result, stats


def stats_markdown(stats):
    lines = ["# Entities after merging", "",
             "| source | documents (records) | entities containing the source |", "|---|---|---|"]
    for source, count in sorted(stats["documents"].items()):
        lines.append("| {} | {} | {} |".format(source, count, stats["entities_per_source"][source]))
    lines += ["| **all** | **{}** | **{}** unique entities |".format(sum(stats["documents"].values()), stats["entities"]),
              "", "Entities found in exactly k sources:", ""]
    lines += ["- {} source(s): {}".format(k, n) for k, n in stats["by_n_sources"].items()]
    lines += ["", "Pairwise overlaps (entities in both sources):", ""]
    lines += ["- {}: {}".format(pair, n) for pair, n in stats["pairs"].items()]
    lines += ["", "Merges through a listed synonym: {}".format(stats["synonym_merges"]),
              "Records whose name is not a binomial (kept as their own entity): {}".format(stats["unparsed_names"])]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Merge plant records of all sites into entities")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    extracted_dir = os.path.join(args.data_dir, "extracted")
    entities, stats = merge(load_records(extracted_dir))
    with open(os.path.join(extracted_dir, "entities.jsonl"), "w", encoding="utf-8") as handle:
        for entity in entities:
            handle.write(json.dumps(entity, ensure_ascii=False) + "\n")
    report = stats_markdown(stats)
    with open(os.path.join(extracted_dir, "entities_stats.md"), "w", encoding="utf-8") as handle:
        handle.write(report)
    print(report)


if __name__ == "__main__":
    sys.exit(main())
