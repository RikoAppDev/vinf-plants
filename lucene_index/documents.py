"""Lucene documents of the plant entities, as plain dicts; no Lucene in this module.

One document per entity of data/spark/joined/entities. The entity gives the names, the source
pages and the Wikipedia page; its extracted records (data/spark/extracted/<site>, found through
the page URL) give the plant attributes. All merging and normalisation rules live here, so they
are tested without Java; lucene_index.build only turns the dict into Lucene fields.

A document maps every field of FIELDS to a list of strings, or to an int or None for NUMBER_FIELDS.
"""

import glob
import json
import os
import re

from sparkjobs.join_wiki import epithet_variant, without_hybrid_sign
from sparkjobs.wiki_pages import name_key

SITES = ("ncsu", "pfaf", "tso", "wooddb")
ENTITIES_DIR = os.path.join("data", "spark", "joined", "entities")
RECORDS_DIR = os.path.join("data", "spark", "extracted")

# Field groups; lucene_index.build gives every group its Lucene type.
NAME_FIELDS = ("name", "common_name", "synonym", "family", "genus", "authority")
TAG_FIELDS = ("plant_type", "leaf", "light", "soil", "ph", "moisture", "tolerates", "maintenance",
              "flower_color", "attracts", "landscape")
LONG_FIELDS = ("origin", "uses", "text", "wiki", "category")
TEXT_FIELDS = NAME_FIELDS + TAG_FIELDS + LONG_FIELDS
EXACT_FIELDS = ("id", "key", "source", "iucn")
NUMBER_FIELDS = ("year", "zone_min", "zone_max", "height_max_cm", "density", "janka", "edibility", "medicinal",
                 "n_sources")
STORED_FIELDS = ("url", "wiki_title", "wiki_url", "wiki_match")
FIELDS = TEXT_FIELDS + EXACT_FIELDS + NUMBER_FIELDS + STORED_FIELDS

# Match levels of sparkjobs.join_wiki, and the match kinds that can lead to the article of another name.
OWN_NAME, SPECIES, GENUS = 0, 1, 2
OTHER_NAME_VIA = {"redirect", "synonym"}
# A title match found the article under our name, but its box may name the accepted one.
TITLE_VIA = "title"

# Record fields that hold the values of a document field, per site, in this order.
RECORD_FIELDS = {
    "ncsu": {"text": ("description",)},
    "pfaf": {"plant_type": ("habit",), "leaf": ("leaf_type",), "light": ("light",), "soil": ("soil",),
             "ph": ("ph",), "moisture": ("moisture",), "tolerates": ("tolerates",),
             "origin": ("native_range", "range"), "uses": ("edible_uses", "medicinal_uses", "other_uses"),
             "text": ("description", "summary", "cultivation", "habitat", "hazards")},
    "tso": {"origin": ("distribution",), "text": ("description", "habitat")},
    "wooddb": {"plant_type": ("wood_type",), "origin": ("distribution",), "uses": ("common_uses",),
               "text": ("description",)},
}
# Values that only exist on the page as a labelled attribute.
ATTRIBUTE_FIELDS = {
    "ncsu": {"plant_type": ("Plant Type",), "leaf": ("Woody Plant Leaf Characteristics",), "light": ("Light",),
             "soil": ("Soil Texture",), "ph": ("Soil pH",), "moisture": ("Soil Drainage",),
             "tolerates": ("Resistance To Challenges",), "maintenance": ("Maintenance",),
             "flower_color": ("Flower Color",), "attracts": ("Attracts",), "landscape": ("Landscape Theme",),
             "origin": ("Country Or Region Of Origin",), "uses": ("Uses (Ethnobotany)",)},
    "pfaf": {"flower_color": ("Bloom Color",),
             "uses": ("Edible Uses", "Medicinal Uses", "Other Uses", "Special Uses")},
}
# NCSU prose attributes ("Flower Description", "Leaf Description", ...) go to text.
NCSU_TEXT_LABEL_SUFFIX = " Description"
# A Wood Database page may describe several species ("Intsia spp.": Intsia bijuga, Intsia palembanica).
NAME_KEYS = ("scientific_name", "scientific_names", "common_names", "synonyms", "family", "genus", "authority")
NUMBER_KEYS = ("zone_min", "zone_max", "height_max_cm", "density_kg_m3", "janka_hardness_n", "edibility_rating",
               "medicinal_rating")
IUCN_KEYS = ("conservation_status", "conservation_code", "iucn_status", "iucn_category")

# Page fillers and statements that say there is no value, matched on the whole lower-case value, also with a
# PFAF reference: "None known", "Not known in the wild[11].", "Not known 193", and "No flowers" of a fern.
PLACEHOLDER_RE = re.compile(
    r"(?:none(?: known)?|no data available|not available|unknown|not known"
    r"|(?:not known|not found|unknown) (?:in (?:a |the )?(?:truly )?wild(?: situation| state| condition| location)?"
    r"|as a (?:truly )?wild plant)"
    r"|no (?:true )?(?:flowers?|fruits?))(?:\s*\[\d+\]|\s+\d+)?[.,]?")
# NCSU explains a class in brackets ("Full sun (6 or more hours of direct sunlight a day)"); the class is the value.
TRAILING_BRACKETS_RE = re.compile(r"\s*\([^()]*\)\s*$")
# PFAF names the light and soil classes of NCSU differently; the NCSU word is added to the PFAF value,
# so light:"full sun" or soil:sand finds the plants of both sites.
PFAF_ALIASES = {
    "light": {"no shade": "full sun", "semi-shade": "partial shade", "full shade": "deep shade"},
    "soil": {"light": "sand", "medium": "loam", "heavy": "clay"},
}
# PFAF values replaced by their alias: "no shade" would let the query light:shade find plants that need full sun.
PFAF_ALIAS_ONLY = {"light": {"no shade"}}
# TSO has no plant type label, but its descriptions open with it ("A deciduous tree to 25 m", "Shrub or small tree").
TSO_HABIT_RE = re.compile(r"\b(tree|shrub|subshrub|climber|liana|vine)s?\b", re.IGNORECASE)
# The same opening words name the leaf ("A deciduous tree to 25 m", "Evergreen or semi-evergreen tree to 20 m").
# Semi-evergreen is matched first; "sub-evergreen", "partially evergreen" and "semi-deciduous" mean the same.
TSO_LEAF_RE = re.compile(r"\b(?:(?:semi|sub|half|partially|partly|nearly|almost)[- ]?evergreen|semi-?deciduous"
                         r"|evergreen|deciduous)\b", re.IGNORECASE)
TSO_LEAF_WORDS = {"evergreen", "deciduous"}
# A leaf word between "on", "of" or "among" and a plural plant word describes other plants: "growing on
# deciduous trees", "new introductions of evergreen species such as Cornus hongkongensis". A genus page
# describes itself in plural ("Deciduous trees to 15 m"), so a plural alone is not enough.
TSO_OTHER_LEAF_BEFORE_RE = re.compile(r"\b(?:on|over|of|among)\s+(?:[\w-]+\s+)?$", re.IGNORECASE)
TSO_OTHER_LEAF_AFTER_RE = re.compile(r"\s+(?:[\w-]+\s+)?(?:trees|shrubs|species|plants|climbers)\b", re.IGNORECASE)
# The hosts of a climber or a parasite are no habit: "parasitic on various trees", "covering lofty trees",
# "reaching to the tops of lofty trees", "festooning small trees and shrubs" (only plural words are hosts).
TSO_HOST_RE = re.compile(
    r"\b(?:on|over|in|(?:tops?|trunks|branches|forks) of|covering|cover|festooning|enveloping|ascending|clinging to|"
    r"attaching itself to)\s+(?:(?:the|various|lofty|large|small|tall|living|highest|other)\s+)*(?:trees\s+and\s+)?$",
    re.IGNORECASE)
TSO_HABIT_WORDS = 15
FIRST_SENTENCE_RE = re.compile(r"[.;](?:\s|$)")
# Every hardwood and softwood comes from a tree; Monocot (palms, bamboo) does not say.
TREE_WOOD_TYPES = {"hardwood", "softwood"}
# "Flora of China", "Trees of Europe", "Endangered flora of Europe"; not "Garden plants of Europe" (cultivation)
# and not "Trees of Mediterranean climate" (a climate, found on several continents).
PLACE_CATEGORY_RE = re.compile(
    r"^(?:[\w-]+ ){0,3}?(?:flora|trees|shrubs|grasses|bunchgrasses|ferns|orchids) of (?:the )?"
    r"(?!.*\bclimates?$)(.+)$", re.IGNORECASE)
# "Naturalized trees of Alabama" (Melia azedarach) names a place where the plant was brought by people.
NOT_NATIVE_CATEGORY_RE = re.compile(r"\b(?:naturali[sz]ed|introduced|invasive|alien)\b", re.IGNORECASE)
# Wikipedia also files an article under categories about the article itself: "Taxonomy articles created by
# Polbot", "Flora without expected TNC conservation status", "Taxobox binomials not recognized by IUCN".
MAINTENANCE_CATEGORY_RE = re.compile(r"\b(?:articles?|pages?|stubs?|taxobox|wikipedia)\b|\bwithout expected\b",
                                     re.IGNORECASE)
# "Appalachian mountains; widely cultivated in the United States and Europe", "Naturalized in Europe",
# "A casual in Britain", "Occasionally established in Europe", "A garden escape in Britain":
# a list item or sentence with these words says where the plant is grown now, not where it comes from.
NOT_NATIVE_WORDS = r"naturali[sz]ed|cultivated|introduced|escape[sd]?|planted|grown|casual|established|persist(?:s|ing)"
NOT_NATIVE_RE = re.compile(r"\b(?:" + NOT_NATIVE_WORDS + r")\b", re.IGNORECASE)
# Words that open a remark on the whole range, after a comma or in brackets.
ORIGIN_CLAUSE_WORDS = r"but|also|widely|now|often|locally|occasionally|sometimes|extensively|though|although"
# TSO lists countries with their status ("Czechia (naturalised); France"); PFAF writes sentences. A full
# stop or a question mark ends a sentence after a word, a reference or a country in capitals ("China.
# Naturalized", "Europe[50]. Rarely", "VIETNAM. Casuarina", "S. Europe? An occasional escape"), not after
# an initial ("E. Asia", "S. Europe"). A clause after a comma is a remark: "China, Japan, but widely
# cultivated in Asia", "Southeastern United States, though also widely grown on plantations", "Europe,
# Naturalized in Northern N. America", "A cosmopolitan plant, a locally established casual in Britain";
# so is one after "but": "Possibly native to Britain but more common as a garden escape".
ORIGIN_PART_RE = re.compile(r";|(?:(?:(?<=[a-z\])])|(?<=[A-Z]{3}))\.|(?<=[a-z]\?))\s+(?=[A-Z]|an?\s)"
                            r"|,\s+(?=(?i:" + ORIGIN_CLAUSE_WORDS + "|" + NOT_NATIVE_WORDS + r")\b|an?\s)"
                            r"|\s+(?=but\s)")
# A remark in brackets is a part of its own: "Central America (Also grown on plantations)". A bracket with a
# status stays with its place: "Czechia (naturalised)".
ORIGIN_ASIDE_RE = re.compile(r"\s*\(((?i:" + ORIGIN_CLAUSE_WORDS + r")\b[^()]*)\)")

IUCN_CODES = {"lc", "nt", "vu", "en", "cr", "ew", "ex", "dd", "lr"}
# IUCN 3.1 moved LR/lc to LC and both LR/nt and LR/cd to NT; plain "lower risk" names no subcategory.
IUCN_OLD_CODES = {"lr/lc": "lc", "lr/nt": "nt", "lr/cd": "nt"}
IUCN_NAMES = {
    "least concern": "lc", "near threatened": "nt", "vulnerable": "vu", "endangered": "en",
    "critically endangered": "cr", "extinct in the wild": "ew", "extinct": "ex", "data deficient": "dd",
    "conservation dependent": "nt", "lower risk": "lr", "lower risk/least concern": "lc",
    "lower risk/near threatened": "nt", "lower risk/conservation dependent": "nt",
}
# Checked first: "not yet assessed ... listed as Endangered in Ohio" has no IUCN category.
NOT_ASSESSED_RE = re.compile(r"\bnot (?:yet )?(?:been )?(?:assessed|evaluated|listed)\b|\bnot available\b")
# Wikipedia first (checked editorial data), then the sites. PFAF last: it still uses the 1994 categories.
# The article of another name counts only when no site has a status: Abies fansipanensis is critically
# endangered on TSO, the article of Abies delavayi says least concern.
IUCN_SOURCES = (("tso", ("conservation_status", "conservation_code")), ("wooddb", ("iucn_status",)),
                ("pfaf", ("iucn_category",)))
# TSO is a dendrological reference; PFAF writes "Various" for genus pages.
AUTHORITY_SITES = ("tso", "pfaf", "wooddb", "ncsu")
NO_AUTHORITY = {"various"}
# A Wikipedia authority may end in a homonym or source note: "Thunb. 1784 not Raf. 1836" (Acer palmatum),
# "L. 1771, conserved name not Heister 1755", "(L.) Benth. & Hook.f. (1873) Sources: NatureServe, IPNI, GRIN".
AUTHORITY_NOTE_RE = re.compile(r"[\s,–-]*(?:\b(?:not|nor|non)\b|\bSources?:|\bconserved (?:name|spelling)\b).*$")


def read_json_lines(folder):
    """Records of all part-* files of a Spark output folder, in file order."""
    for path in sorted(glob.glob(os.path.join(folder, "part-*"))):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def slim_record(record):
    """The part of a record that the documents use; the full PFAF and NCSU pages would not fit in memory twice."""
    site = record.get("source")
    keys = {"url", "source", "article_type"}
    keys.update(NAME_KEYS, NUMBER_KEYS, IUCN_KEYS)
    for record_keys in RECORD_FIELDS.get(site, {}).values():
        keys.update(record_keys)
    labels = set()
    for attribute_labels in ATTRIBUTE_FIELDS.get(site, {}).values():
        labels.update(attribute_labels)
    attributes = record.get("attributes") or {}
    slim = {key: record[key] for key in keys if key in record}
    slim["attributes"] = {label: values for label, values in attributes.items()
                          if label in labels or (site == "ncsu" and label.endswith(NCSU_TEXT_LABEL_SUFFIX))}
    return slim


def load_records(records_dir=RECORDS_DIR, sites=SITES):
    """{url: slim record} of the extracted records of all sites."""
    records = {}
    for site in sites:
        for record in read_json_lines(os.path.join(records_dir, site)):
            records[record["url"]] = slim_record(record)
    return records


def strings(value):
    """Strings of a field holding a string or a list; numbers, booleans and None give nothing."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def unique(values):
    """Values in order with blanks, fillers and case-insensitive repeats dropped; the first spelling stays."""
    seen, result = set(), []
    for value in values:
        value = " ".join(value.split())
        folded = value.casefold()
        if value and folded not in seen and not PLACEHOLDER_RE.fullmatch(folded):
            seen.add(folded)
            result.append(value)
    return result


def without_brackets(value):
    """'Full sun (6 or more hours of direct sunlight a day)' -> 'Full sun'."""
    return TRAILING_BRACKETS_RE.sub("", value) or value


def pfaf_values(field, value):
    """The PFAF value, followed by the NCSU word for the same class if there is one (PFAF_ALIAS_ONLY: only that)."""
    key = without_brackets(value).lower()
    alias = PFAF_ALIASES.get(field, {}).get(key)
    if not alias:
        return [value]
    return [alias] if key in PFAF_ALIAS_ONLY.get(field, ()) else [value, alias]


def tso_opening(description):
    """The opening words of a TSO description, which name the habit and the leaf; '' for an editorial note."""
    if not description or description.startswith("Editorial Note"):
        return ""
    first = FIRST_SENTENCE_RE.split(description, 1)[0]
    return " ".join(first.split()[:TSO_HABIT_WORDS])


def tso_plant_types(description):
    """['shrub', 'tree'] from the opening words of a TSO description; [] for an editorial note."""
    opening = tso_opening(description)
    return unique(match.group(1).lower() for match in TSO_HABIT_RE.finditer(opening)
                  if not (match.group(0).lower().endswith("s") and TSO_HOST_RE.search(opening[:match.start()])))


def tso_leaf(description):
    """['deciduous', 'semi-evergreen'] from the opening words of a TSO description; [] for an editorial note."""
    opening = tso_opening(description)
    leaves = []
    for match in TSO_LEAF_RE.finditer(opening):
        if (TSO_OTHER_LEAF_BEFORE_RE.search(opening[:match.start()])
                and TSO_OTHER_LEAF_AFTER_RE.match(opening, match.end())):
            continue
        word = match.group(0).lower()
        leaves.append(word if word in TSO_LEAF_WORDS else "semi-evergreen")
    return unique(leaves)


def native_part(value):
    """The list items and sentences of an origin value that do not say where the plant is only grown.

    'E. Asia - China. Naturalized in Europe.' -> 'E. Asia - China';
    'Czechia (naturalised); France; Germany' -> 'France; Germany';
    'Central America (Also grown on plantations)' -> 'Central America'.
    """
    if not NOT_NATIVE_RE.search(value):
        return value
    parts = (part.strip(" ,.") for part in ORIGIN_PART_RE.split(ORIGIN_ASIDE_RE.sub(r"; \1", value)))
    return "; ".join(part for part in parts if part and not NOT_NATIVE_RE.search(part))


def record_values(record, field):
    """Values of one document field from one record, before deduplication."""
    site = record.get("source")
    values = []
    for key in RECORD_FIELDS.get(site, {}).get(field, ()):
        values.extend(strings(record.get(key)))
    attributes = record.get("attributes") or {}
    for label in ATTRIBUTE_FIELDS.get(site, {}).get(field, ()):
        found = strings(attributes.get(label))
        if site == "ncsu" and field in TAG_FIELDS:
            found = [without_brackets(value) for value in found]
        values.extend(found)
    if site == "ncsu" and field == "text":
        for label in sorted(attributes):
            if label.endswith(NCSU_TEXT_LABEL_SUFFIX):
                values.extend(strings(attributes[label]))
    if site == "pfaf" and field in PFAF_ALIASES:
        values = [alias for value in values for alias in pfaf_values(field, value)]
    if field == "origin":
        values = [native_part(value) for value in values]
    if field == "plant_type" and site == "tso":
        values.extend(tso_plant_types(record.get("description")))
    if field == "leaf" and site == "tso":
        values.extend(tso_leaf(record.get("description")))
    if field == "plant_type" and site == "wooddb":
        values.extend("tree" for value in strings(record.get("wood_type")) if value.lower() in TREE_WOOD_TYPES)
    return values


def iucn_code(value):
    """Lower-case IUCN code of a code ('VU') or a category text ('Status: Vulnerable A1cd'); None if none."""
    text = " ".join(str(value or "").lower().split())
    if not text or NOT_ASSESSED_RE.search(text):
        return None
    if text in IUCN_CODES:
        return text
    if text in IUCN_OLD_CODES:
        return IUCN_OLD_CODES[text]
    # The earliest category named wins, the longest at one position: "critically endangered", not "endangered".
    found = [(text.find(name), -len(name), code) for name, code in IUCN_NAMES.items() if name in text]
    return min(found)[2] if found else None


def entity_iucn(own_wiki, records, own_article=True):
    """IUCN code by source priority: Wikipedia, TSO, Wood Database, PFAF; an article about another name
    (own_article False) comes after the sites."""
    wiki_code = iucn_code(own_wiki.get("iucn_status")) if own_wiki else None
    if wiki_code and own_article:
        return wiki_code
    for site, keys in IUCN_SOURCES:
        for record in records:
            if record.get("source") != site:
                continue
            for key in keys:
                code = iucn_code(record.get(key))
                if code:
                    return code
    return wiki_code


def without_authority_note(authority):
    """'Thunb. 1784 not Raf. 1836' -> 'Thunb. 1784'; '' if nothing but a note is left."""
    return AUTHORITY_NOTE_RE.sub("", authority or "").strip()


def entity_authority(name_wiki, records):
    """Wikipedia authority, else the first record authority in AUTHORITY_SITES order; None if none."""
    authority = without_authority_note(name_wiki.get("authority")) if name_wiki else ""
    if authority:
        return authority
    for site in AUTHORITY_SITES:
        for record in records:
            authority = (record.get("authority") or "").strip()
            if record.get("source") == site and authority and authority.lower() not in NO_AUTHORITY:
                return authority
    return None


def category_places(categories):
    """'Flora of Southeast Europe' -> 'Southeast Europe', for the origin field."""
    places = []
    for category in categories or []:
        match = PLACE_CATEGORY_RE.match(category)
        if match and not NOT_NATIVE_CATEGORY_RE.search(category):
            places.append(match.group(1))
    return places


def wikipedia_url(title):
    path = title.strip().replace(" ", "_")
    for char, code in (("%", "%25"), ("?", "%3F"), ("#", "%23")):
        path = path.replace(char, code)
    return "https://en.wikipedia.org/wiki/" + path


def extreme(values, pick):
    """min or max of the numbers among values, rounded to int; None if there is none."""
    numbers = [int(round(value)) for value in values
               if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return pick(numbers) if numbers else None


def entity_records(entity, records_by_url):
    """Records of the entity's pages in SITES order; a page without a record is skipped."""
    found = []
    for site in SITES:
        for url in (entity.get("sources") or {}).get(site, []):
            if url in records_by_url:
                found.append(records_by_url[url])
    return found


def entity_urls(entity):
    return [url for site in SITES for url in (entity.get("sources") or {}).get(site, [])]


def name_forms(key):
    """A name key and the forms the join takes for the same name: no hybrid sign, no epithet ending."""
    return {form for form in (key, without_hybrid_sign(key), epithet_variant(key)) if form}


def edit_distance(first, second):
    """Levenshtein distance of two strings."""
    previous = list(range(len(second) + 1))
    for i, char in enumerate(first, 1):
        current = [i]
        for j, other in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1]


def spelling_variant(first, second):
    """True for two spellings of one name ('melia azederach' / 'azedarach', 'hypochoeris' / 'hypochaeris',
    'non-scripta' / 'nonscripta'): the genus one letter apart at most, an epithet one, or two from 8 letters.
    Two letters in a short epithet already make another name: 'ephedra ciliata' / 'foliata'."""
    words = without_hybrid_sign(first).replace("-", "").split()
    others = without_hybrid_sign(second).replace("-", "").split()
    if len(words) < 2 or len(words) != len(others):
        return False
    return all(edit_distance(word, other) <= (2 if position and min(len(word), len(other)) >= 8 else 1)
               for position, (word, other) in enumerate(zip(words, others)))


def is_own_article(wiki, entity, records):
    """False if a redirect, a synonym or a title led to an article whose name is none of the entity's names.

    Such a link goes from our name to the article of the accepted name ("Alnus rugosa" -> "Alnus incana",
    "Mimulus luteus" -> "Erythranthe lutea"): the article's authority and year belong to that name.
    A title is our name, but the box can still name the accepted one ("Lycopodium annotinum" -> Spinulum
    annotinum); a title without a binomial (a genus) is ours. Another spelling of our name ("Gymnocladus
    dioica" -> "Gymnocladus dioicus", "Melia azederach" -> "Melia azedarach") still is our name.
    """
    via = (wiki.get("match") or {}).get("via")
    if via == TITLE_VIA:
        theirs = name_key(wiki.get("binomial"))
        if not theirs:
            return True
    elif via in OTHER_NAME_VIA:
        theirs = name_key(wiki.get("binomial")) or name_key(wiki.get("title"))
        if not theirs:
            return False
    else:
        return True
    names = strings(entity.get("scientific_names")) + [name for record in records
                                                        for name in strings(record.get("scientific_name"))]
    keys = [key for key in [entity.get("key")] + list(entity.get("aliases") or []) + [name_key(name) for name in names]
            if key]
    ours = set().union(*(name_forms(key) for key in keys)) if keys else set()
    return bool(name_forms(theirs) & ours) or any(spelling_variant(key, theirs) for key in keys)


def name_words(name):
    """'Anemone x hybrida' and 'Anemone × hybrida' -> ['anemone', 'hybrida']: lower case, no hybrid sign."""
    return [word for word in name.casefold().split() if word not in ("x", "×")]


def starts_with_name(name, prefix):
    """True if the words of name begin with all words of prefix: a cultivar or variety of that species."""
    words, first = name_words(name), name_words(prefix)
    return bool(first) and words[:len(first)] == first


def single_tso_zone(record):
    """True for a TSO record with one zone ("7"): the coldest zone the plant survives, not a range."""
    return (record.get("source") == "tso" and record.get("zone_min") is not None
            and record.get("zone_min") == record.get("zone_max"))


def entity_document(entity, records_by_url):
    """The document of one entity (see the module docstring)."""
    records = entity_records(entity, records_by_url)
    wiki = entity.get("wikipedia") or None
    level = (wiki.get("match") or {}).get("level", GENUS) if wiki else None
    # A genus article describes the whole genus: only its lead text is used for a species.
    # A species article also gives its cultivars common names and places, but its IUCN status belongs to the
    # wild plant (own_wiki) and its name, authority and year to the published name (name_wiki, the article
    # of our name).
    species_wiki = wiki if wiki and level <= SPECIES else None
    own_wiki = wiki if wiki and level == OWN_NAME else None
    name_wiki = own_wiki if own_wiki and is_own_article(own_wiki, entity, records) else None

    def from_records(field):
        return [value for record in records for value in record_values(record, field)]

    def from_record_key(key):
        return [value for record in records for value in strings(record.get(key))]

    def from_wiki(key):
        return strings(species_wiki.get(key)) if species_wiki else []

    own_names = unique(strings(entity.get("scientific_names")) + from_record_key("scientific_name"))
    # The binomial of another article is another name: as a name, the species would make "acer palmatum" rank
    # the cultivars above the species, the accepted name "alnus incana" would find Alnus rugosa. It is a synonym,
    # unless our name already starts with it ("Acer palmatum 'Atropurpureum'").
    if name_wiki:
        names, other_names = unique(own_names + from_wiki("binomial")), []
    else:
        names = own_names
        other_names = [binomial for binomial in from_wiki("binomial")
                       if not any(starts_with_name(name, binomial) for name in own_names)]
    name_set = {name.casefold() for name in names}
    doc = {field: [] for field in FIELDS if field not in NUMBER_FIELDS}
    doc.update({
        "id": [str(entity["entity_id"])],
        "key": [entity["key"]],
        "source": [site for site in SITES if site in (entity.get("sources") or {})],
        "name": names,
        "common_name": unique(from_record_key("common_names") + from_wiki("common_names")),
        "synonym": [synonym for synonym in unique(from_record_key("synonyms") + from_record_key("scientific_names") +
                                                  other_names + from_wiki("synonyms"))
                    if synonym.casefold() not in name_set],
        "family": unique(from_record_key("family")),
        "genus": unique(from_record_key("genus")),
        "category": [category for category in unique(from_wiki("categories"))
                     if not MAINTENANCE_CATEGORY_RE.search(category)],
        "wiki": unique(strings(wiki.get("lead"))) if wiki else [],
        "url": entity_urls(entity),
    })
    for field in TAG_FIELDS + ("uses", "text"):
        doc[field] = unique(from_records(field))
    origin = unique(from_records("origin"))
    places = category_places(from_wiki("categories"))
    if own_wiki and not name_wiki and origin:
        # The places of the accepted name only stand in for a missing origin: Alnus rugosa, a North American
        # alder, would get Europe and Asia from the article of Alnus incana.
        places = []
    doc["origin"] = unique(origin + places)
    authority = entity_authority(name_wiki, records)
    doc["authority"] = [authority] if authority else []
    iucn = entity_iucn(own_wiki, records, own_article=bool(name_wiki))
    doc["iucn"] = [iucn] if iucn else []
    if wiki and (wiki.get("title") or "").strip():
        match = wiki.get("match") or {}
        doc["wiki_title"] = [wiki["title"]]
        doc["wiki_url"] = [wikipedia_url(wiki["title"])]
        doc["wiki_match"] = ["{}, via {}".format(match.get("level_name", "?"), match.get("via", "?"))]

    def numbers(key):
        return [record.get(key) for record in records]

    doc.update({
        "year": extreme([name_wiki.get("year_described")], max) if name_wiki else None,
        # A plant is as hardy as its hardiest record says and as tall as its tallest. A single TSO zone
        # ("7") is only the coldest zone the plant survives: it says nothing about the warmest.
        "zone_min": extreme(numbers("zone_min"), min),
        "zone_max": extreme([record.get("zone_max") for record in records if not single_tso_zone(record)], max),
        "height_max_cm": extreme(numbers("height_max_cm"), max),
        "density": extreme(numbers("density_kg_m3"), max),
        "janka": extreme(numbers("janka_hardness_n"), max),
        "edibility": extreme(numbers("edibility_rating"), max),
        "medicinal": extreme(numbers("medicinal_rating"), max),
        "n_sources": len(doc["source"]),
    })
    return doc


def read_documents(entities_dir=ENTITIES_DIR, records_dir=RECORDS_DIR):
    """Documents of all entities, in entity order."""
    records_by_url = load_records(records_dir)
    for entity in read_json_lines(entities_dir):
        yield entity_document(entity, records_by_url)
