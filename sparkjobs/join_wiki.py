"""Spark job: join our plant entities with the Wikipedia pages selected by sparkjobs.wiki_pages.

Usage:
    python -m sparkjobs.join_wiki          # -> data/spark/joined/entities/, join_stats.md
    python -m sparkjobs.join_wiki --pages data/spark/wikipedia_sample/pages --out data/spark/joined_sample
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata

from extractor.normalize import species_key
from tools.merge_entities import entity_key

from .session import add_arguments, get_spark, save_lines, save_text
from .wiki_pages import name_key

ENTITIES = "data/spark/entities"
PAGES = "data/spark/wikipedia/pages"
RECORDS = "data/spark/extracted"

OWN_NAME, SPECIES, GENUS = 0, 1, 2
LEVELS = {OWN_NAME: "own name", SPECIES: "species of a cultivar or variety", GENUS: "genus"}
# Lower is more trusted: an editor made the redirect on purpose; hybrid, variant and synonym are guesses.
WIKI_RANK = {"box": 0, "title": 0, "genus": 0, "redirect": 1, "genus_title": 1, "hybrid": 2, "variant": 3,
             "synonym": 4}
# The kind reported when one page is reached through several kinds with the same score.
KIND_ORDER = {via: position for position, via in enumerate(
    ("box", "genus", "title", "redirect", "genus_title", "hybrid", "variant", "synonym"))}
SPECIES_RANKS = ("species", "infraspecies")
# Fallback keys only meet fallback keys of the other side.
HYBRID_PREFIX, VARIANT_PREFIX = "~", "="
# Gender and spelling variants of one epithet: japonica / japonicus, armandi / armandii, viridis / viride.
EPITHET_ENDING_RE = re.compile(r"(?:ii|i|us|um|a|is|e)$")
# A page titled with a rank between genus and species ("Populus sect. Tacamahaca") is not a species article.
SECTION_TITLE_RE = re.compile(r"\b(?:subg|subgen|sect|subsect|ser|subser)\b")
AUTHOR_PART_RE = re.compile(r"\s+(?:ex|in)\s+")
AUTHOR_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
WIKI_FIELDS = ("page_id", "title", "binomial", "rank", "authority", "year_described", "iucn_status",
               "synonyms", "common_names", "categories", "lead")


def without_hybrid_sign(key):
    """'quercus × hispanica' -> 'quercus hispanica'."""
    return " ".join(word for word in key.split() if word != "×")


def epithet_variant(key):
    """'styrax japonica' -> 'styrax japonic'; "" for a genus or a short epithet."""
    words = without_hybrid_sign(key).split()
    if len(words) < 2:
        return ""
    stem = EPITHET_ENDING_RE.sub("", words[1])
    return " ".join([words[0], stem] + words[2:]) if len(stem) >= 3 else ""


def fallback_keys(key):
    """The prefixed fallback keys of a binomial key (see HYBRID_PREFIX)."""
    pairs = []
    if " " in key:
        pairs.append((HYBRID_PREFIX + without_hybrid_sign(key), "hybrid"))
        variant = epithet_variant(key)
        if variant:
            pairs.append((VARIANT_PREFIX + variant, "variant"))
    return pairs


def entity_keys(entity):
    """[(key, level)] of one entity, each key once with its lowest level.

    Not our sites' synonyms: some are misapplied (TSO lists Quercus palustris under Quercus coccinea).
    """
    found = {}

    def add(key, level):
        if key and not key.startswith("unparsed:") and level < found.get(key, 99):
            found[key] = level

    for key in [entity["key"]] + list(entity.get("aliases") or []):
        add(key, OWN_NAME)
    for name in entity.get("scientific_names") or []:
        add(species_key(name), SPECIES)
    for key, level in list(found.items()):
        for fallback, _via in fallback_keys(key):
            add(fallback, level)
    genus = entity["key"].split()[0]
    if " " in entity["key"] and not genus.startswith("unparsed:"):
        add(genus, GENUS)
    return sorted(found.items())


def is_alias(key, entity):
    """True for a key of an alias or of a species, False for the entity's own key and its fallbacks."""
    own = entity["key"]
    return key.lstrip(HYBRID_PREFIX + VARIANT_PREFIX) not in (own, without_hybrid_sign(own), epithet_variant(own))


def article_keys(page):
    """[(key, via)] under which an article can be found."""
    pairs = []
    if page.get("binomial"):
        pairs.append((name_key(page["binomial"]), "box"))
    taxon = page.get("taxon") or page.get("genus")
    title_key = name_key(page["title"])
    if page.get("rank") == "genus" and taxon:
        # name_key drops the hybrid sign of a nothogenus ("× Sorbaronia"), as the entity keys do.
        pairs.append((name_key(taxon), "genus"))
    elif title_key and " " not in title_key and title_key == (page.get("genus") or "").lower():
        # "Kalopanax" is the article of the only species of its genus, the genus fallback lands there.
        pairs.append((title_key, "genus_title"))
    pairs.append((title_key, "title"))
    for key, via in list(pairs):
        if via in ("box", "title"):
            pairs.extend(fallback_keys(key))
    genus = (page.get("genus") or taxon or "").lower()
    for name in page.get("synonyms") or []:
        key = name_key(name)
        if genus and key.split(" ")[0] == genus:
            pairs.append((key, "synonym"))
    seen = set()
    return [(key, via) for key, via in pairs if key and not ((key, via) in seen or seen.add((key, via)))]


def allowed(level, via, plant=True, rank=None):
    """Which entity level (own name, species of a cultivar, genus) may meet which kind of Wikipedia key."""
    if level == GENUS:
        # Only a plant genus article (Dracaena is also a lizard, Oenanthe a bird) or a redirect to one.
        return plant and (via in ("genus", "genus_title") or (via == "redirect" and rank == "genus"))
    if via == "genus":
        # An entity that is itself a genus page ("Hosta").
        return plant and level == OWN_NAME
    if via == "genus_title":
        return False
    if via == "synonym":
        return level == OWN_NAME
    return True


def author_names(authority):
    """'(L.) Mill.' -> {'l', 'mill'}: the first surname of every author part, lower case without accents."""
    text = re.sub(r"\d{4}", " ", authority or "")
    parts = re.findall(r"\(([^)]*)\)", text) + [re.sub(r"\([^)]*\)", " ", text)]
    names = set()
    for part in parts:
        for piece in AUTHOR_PART_RE.split(part):
            word = AUTHOR_WORD_RE.search(piece)
            if word:
                folded = unicodedata.normalize("NFKD", word.group()).encode("ascii", "ignore").decode().lower()
                if folded:
                    names.add(folded)
    return names


def same_author(ours, theirs):
    """True unless both authorities are known and name different people ('Miq.' vs 'Dippel')."""
    mine, other = author_names(ours), author_names(theirs)
    if not mine or not other:
        return True
    for a in mine:
        for b in other:
            if (a == b) if min(len(a), len(b)) == 1 else (a.startswith(b) or b.startswith(a)):
                return True
    return False


def candidate(pair, authorities=None):
    """(key, ((entity_id, level, alias), (page_id, via, plant, rank, title_key, author)))
    -> [(entity_id, (score, page ids, detail))]."""
    key = pair[0]
    (entity_id, level, alias), hit = pair[1]
    page_id, via, plant = hit[:3]
    rank, title_key, author = (tuple(hit[3:]) + (None, None, None))[:3]
    name = key.lstrip(HYBRID_PREFIX + VARIANT_PREFIX)
    binomial = " " in name
    section = rank is None and bool(title_key) and bool(SECTION_TITLE_RE.search(title_key))
    if level != GENUS and binomial and (rank in ("genus", "higher") or section):
        # A species name leading to a genus or section article ("Hosta nigrescens" -> Hosta) is a genus fallback.
        level = GENUS
    if not allowed(level, via, plant, rank):
        return []
    if via == "synonym" and authorities and not all_compatible(authorities.get(name), author):
        # The same binomial by another author is another plant (a later homonym or a misapplied name).
        return []
    rank_fit = 0 if (rank in SPECIES_RANKS if binomial else rank == "genus") else 1
    title_fit = 0 if title_key == name else 1
    # Own key beats an alias with its own article (Campanula punctata); a page whose rank and title
    # fit beats a section or vernacular page of the same taxon (Sorbus vs Rowan); then plant pages.
    score = (level, alias, WIKI_RANK[via], rank_fit, title_fit, 0 if plant else 1)
    return [(entity_id, (score, frozenset([page_id]), (page_id, via, level)))]


def all_compatible(ours, theirs):
    """The synonym's author agrees with one of the authorities on our records (or one side has none)."""
    return not ours or not theirs or any(same_author(authority, theirs) for authority in ours)


def article_hits(page):
    """[(key, (page_id, via, plant, rank, title key, author of the synonym))] of one article."""
    plant, rank, title_key = bool(page.get("plant_hint")), page.get("rank"), name_key(page["title"])
    authors = dict((name_key(name), author) for name, author in (page.get("synonym_authors") or {}).items())
    return [(key, (page["page_id"], via, plant, rank, title_key, authors.get(key) if via == "synonym" else None))
            for key, via in article_keys(page)]


def match_class(key, wiki):
    """'species', 'genus entity' (our entity is a genus), 'genus' (only the genus fallback) or None."""
    if not wiki:
        return None
    if wiki["match"]["level"] == GENUS:
        return "genus"
    return "species" if " " in key else "genus entity"


def better(a, b):
    """Of two candidates (score, page ids at that score, detail), the one with the lower score."""
    if a[0] < b[0]:
        return a
    if b[0] < a[0]:
        return b
    detail = min(a[2], b[2], key=lambda item: (item[0], KIND_ORDER[item[1]]))
    return a[0], a[1] | b[1], detail


def share(count, total):
    return "{} ({:.1f} %)".format(count, 100.0 * count / max(total, 1))


def stats_markdown(stats):
    total, classes = stats["entities"], stats["classes"]
    lines = ["# Join of the plant entities with English Wikipedia", "",
             "Entities: {}. Joined to an article about the plant or its species: {}; entities that are a genus, "
             "joined to the genus article: {}; only to the genus article (fallback): {}; not joined: {}.".format(
                 total, share(classes["species"], total), share(classes["genus entity"], total),
                 share(classes["genus"], total), share(total - stats["joined"], total)),
             "Unique Wikipedia pages joined: {} (articles about the plant or its species: {}). "
             "Ambiguous matches: {}.".format(stats["unique_pages"], stats["unique_species_pages"], stats["ambiguous"]),
             "", "| entity side | Wikipedia side | entities |", "|---|---|---|"]
    for (level, via), count in sorted(stats["by_match"].items()):
        lines.append("| {} | {} | {} |".format(LEVELS[level], via, count))
    lines += ["", "| source | entities | plant or species article | genus entity | only genus article |",
              "|---|---|---|---|---|"]
    for source, counts in sorted(stats["by_source"].items()):
        lines.append("| {} | {} | {} | {} | {} |".format(
            source, counts["entities"], share(counts["species"], counts["entities"]),
            share(counts["genus entity"], counts["entities"]), share(counts["genus"], counts["entities"])))
    lines += ["", "Field coverage of the joined pages (entities joined to an article about the plant or its "
              "species, {}):".format(classes["species"]), "", "| field | entities | share |", "|---|---|---|"]
    for field, count in stats["coverage"]:
        lines.append("| {} | {} | {:.1f} % |".format(field, count, 100.0 * count / max(classes["species"], 1)))
    lines += ["", "Run time: {} s".format(stats["seconds"])]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Join plant entities with Wikipedia pages")
    parser.add_argument("--entities", default=ENTITIES, help="output of tools.merge_entities or sparkjobs.merge_entities")
    parser.add_argument("--pages", default=PAGES, help="output of sparkjobs.wiki_pages")
    parser.add_argument("--records", default=RECORDS,
                        help="output of sparkjobs.extract_sites (a folder per site), for the authorities of our names")
    parser.add_argument("--out", default="data/spark/joined")
    add_arguments(parser)
    args = parser.parse_args(argv)

    started = time.time()
    spark = get_spark("vinf-join-wiki", args.master, args.driver_memory)
    sc = spark.sparkContext

    entities = sc.textFile(args.entities).filter(lambda line: line.strip()).map(json.loads) \
        .map(lambda entity: (entity["entity_id"], entity)).persist()
    keyed_entities = entities.flatMap(lambda item: [(key, (item[0], level, is_alias(key, item[1])))
                                                    for key, level in entity_keys(item[1])])
    # Our authorities by name key (about 12 000 short strings), broadcast to check synonym authors.
    authorities = sc.broadcast(dict(
        sc.textFile(os.path.join(args.records, "*")).filter(lambda line: line.strip()).map(json.loads)
        .filter(lambda record: record.get("authority"))
        .map(lambda record: (entity_key(record.get("scientific_name") or ""), record["authority"]))
        .filter(lambda pair: pair[0]).groupByKey().mapValues(lambda values: sorted(set(values))).collect()))

    pages = sc.textFile(args.pages).filter(lambda line: line.strip()).map(json.loads).persist()
    articles = pages.filter(lambda page: not page.get("redirect"))
    by_title = articles.map(lambda page: (page["title"], (page["page_id"], bool(page.get("plant_hint")),
                                                          page.get("rank"), name_key(page["title"]))))
    redirect_keys = pages.filter(lambda page: page.get("redirect")) \
        .map(lambda page: (page["redirect"].split("#")[0], name_key(page["title"]))).filter(lambda pair: pair[1])
    wiki_keys = articles.flatMap(article_hits).union(redirect_keys.join(by_title).map(
        lambda pair: (pair[1][0], (pair[1][1][0], "redirect") + pair[1][1][1:] + (None,))))

    best = keyed_entities.join(wiki_keys).flatMap(lambda pair: candidate(pair, authorities.value)) \
        .reduceByKey(better) \
        .map(lambda item: (item[1][2][0], (item[0], item[1][2][1], item[1][2][2], len(item[1][1]))))
    page_fields = articles.map(lambda page: (page["page_id"], {field: page.get(field) for field in WIKI_FIELDS}))
    matches = best.join(page_fields).map(lambda item: (item[1][0][0], dict(
        item[1][1], match={"via": item[1][0][1], "level": item[1][0][2], "level_name": LEVELS[item[1][0][2]],
                           "ambiguous_pages": item[1][0][3]})))
    # Sorted by entity id, so the output does not depend on the number of cores.
    joined = entities.leftOuterJoin(matches).sortByKey() \
        .map(lambda item: dict(item[1][0], wikipedia=item[1][1])).persist()
    save_lines(joined.map(lambda entity: json.dumps(entity, ensure_ascii=False)), os.path.join(args.out, "entities"))

    rows = joined.map(lambda entity: (sorted(entity["sources"]), entity["key"], entity["wikipedia"])).collect()
    stats = {"entities": len(rows), "joined": 0, "ambiguous": 0, "by_match": {}, "by_source": {},
             "classes": {"species": 0, "genus entity": 0, "genus": 0}, "coverage": []}
    pages_joined, species_pages = set(), set()
    coverage = dict((field, 0) for field in ("authority", "year_described", "iucn_status", "synonyms",
                                             "common_names", "categories", "lead"))
    for sources, key, wiki in rows:
        kind = match_class(key, wiki)
        for source in sources:
            counts = stats["by_source"].setdefault(source, {"entities": 0, "species": 0, "genus entity": 0, "genus": 0})
            counts["entities"] += 1
            if kind:
                counts[kind] += 1
        if not wiki:
            continue
        stats["joined"] += 1
        stats["classes"][kind] += 1
        pages_joined.add(wiki["page_id"])
        match = wiki["match"]
        stats["ambiguous"] += 1 if match["ambiguous_pages"] > 1 else 0
        stats["by_match"][(match["level"], match["via"])] = stats["by_match"].get((match["level"], match["via"]), 0) + 1
        if kind == "species":
            species_pages.add(wiki["page_id"])
            for field in coverage:
                coverage[field] += 1 if wiki.get(field) else 0
    stats["unique_pages"] = len(pages_joined)
    stats["unique_species_pages"] = len(species_pages)
    stats["coverage"] = sorted(coverage.items())
    stats["seconds"] = round(time.time() - started, 1)
    report = stats_markdown(stats)
    save_text(sc, os.path.join(args.out, "join_stats.md"), report.rstrip("\n"))
    print(report)
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
