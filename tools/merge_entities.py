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


def record_key(record):
    return entity_key(record.get("scientific_name", "")) or "unparsed:" + record["url"]


def synonym_edges(record, key):
    """(alias key, record key) for every synonym listed on the record, in the listed order."""
    return [(entity_key(synonym), key) for synonym in record.get("synonyms") or []]


def join_synonyms(edges, key_sources):
    """Union-find over (alias, key) edges; returns (groups, number of merges).

    key_sources maps every key that has a record to the set of its sources; an alias
    without a record is ignored. The edges must come in the order of the records and
    their synonyms: which of two conflicting merges wins depends on it.
    """
    groups = UnionFind()
    root_sources = {key: set(sources) for key, sources in key_sources.items()}  # root -> sources in its group
    merges = 0
    for alias, key in edges:
        if not alias or alias not in key_sources:
            continue
        a, b = groups.find(alias), groups.find(key)
        # Never merge two different pages of one site.
        if a == b or root_sources[a] & root_sources[b]:
            continue
        groups.union(a, b)
        root_sources[b] |= root_sources.pop(a)
        merges += 1
    return groups, merges


def entity_member(record, key):
    return key, record.get("scientific_name", ""), record["source"], record["url"]


def build_entity(number, root, members):
    """Entity of one group; members are entity_member() tuples of its records, in any order."""
    keys, names, sources = set(), set(), defaultdict(list)
    for key, name, source, url in members:
        keys.add(key)
        names.add(name)
        sources[source].append(url)
    return {
        "entity_id": number,
        "key": root,
        "aliases": sorted(keys - {root}),
        "scientific_names": sorted(names),
        "sources": {source: sorted(urls) for source, urls in sorted(sources.items())},
        "n_sources": len(sources),
    }


def entity_profile(entity):
    """What the statistics need of an entity: its sources and whether its name was parsed."""
    return tuple(entity["sources"]), entity["key"].startswith("unparsed:")


def merge_stats(documents, profiles, synonym_merges):
    """Statistics from the record counts per source and a Counter of entity profiles."""
    sources = sorted(documents)
    by_n_sources = Counter()
    for (entity_sources, _unparsed), count in profiles.items():
        by_n_sources[len(entity_sources)] += count

    def entities_with(*wanted):
        return sum(count for (entity_sources, _unparsed), count in profiles.items()
                   if all(source in entity_sources for source in wanted))

    return {
        "documents": dict(documents),
        "entities_per_source": {s: entities_with(s) for s in sources},
        "entities": sum(profiles.values()),
        "unparsed_names": sum(count for (_sources, unparsed), count in profiles.items() if unparsed),
        "synonym_merges": synonym_merges,
        "by_n_sources": dict(sorted(by_n_sources.items())),
        "pairs": {"{} & {}".format(a, b): entities_with(a, b) for a, b in combinations(sources, 2)},
    }


def merge(records):
    """Returns (entities, statistics dict)."""
    key_sources = defaultdict(set)
    for record in records:
        record["_key"] = record_key(record)
        key_sources[record["_key"]].add(record["source"])

    edges = [edge for record in records for edge in synonym_edges(record, record["_key"])]
    groups, synonym_merges = join_synonyms(edges, key_sources)

    members = defaultdict(list)
    for record in records:
        members[groups.find(record["_key"])].append(entity_member(record, record["_key"]))
    result = [build_entity(number, root, members[root]) for number, root in enumerate(sorted(members), 1)]

    documents = Counter(record["source"] for record in records)
    profiles = Counter(entity_profile(entity) for entity in result)
    return result, merge_stats(documents, profiles, synonym_merges)


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
