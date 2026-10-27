"""Regex entity extraction for plants.ces.ncsu.edu plant pages.

Every pattern is anchored on a visible text label ("Family:", "Dimensions:",
"Common Name(s):"), not on the position of an element in the DOM.
"""

import html
import re

# "<title> Quercus alba (American White Oak, ...) | North Carolina Extension ..."
TITLE_RE = re.compile(r"<title>\s*(.*?)\s*(?:\||</title>)", re.DOTALL | re.IGNORECASE)

# "<dt>Label:</dt>" followed by one or more "<dd>value</dd>" blocks.
ATTRIBUTE_RE = re.compile(r"<dt>\s*([^<]+?)\s*:?\s*</dt>((?:\s*<dd>.*?</dd>)+)", re.DOTALL | re.IGNORECASE)
DD_RE = re.compile(r"<dd>(.*?)</dd>", re.DOTALL | re.IGNORECASE)

# Lists under the "Common Name(s):" and "Previously known as:" headings.
COMMON_NAMES_RE = re.compile(r"Common Name\(s\):\s*</h\d>\s*<ul[^>]*>(.*?)</ul>", re.DOTALL | re.IGNORECASE)
SYNONYMS_RE = re.compile(r"Previously known as:\s*</h\d>\s*<ul[^>]*>(.*?)</ul>", re.DOTALL | re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

# "Height: 50 ft. 0 in. - 135 ft. 0 in."
LENGTH_RE = re.compile(r"(\d+)\s*ft\.\s*(\d+)\s*in\.")
# "3a, 3b, 4a, ... 9b"
ZONE_RE = re.compile(r"\b(\d{1,2})[ab]?\b")

CM_PER_INCH = 2.54


def clean_text(fragment):
    """Strip tags, decode entities and collapse whitespace."""
    return WHITESPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _list_items(pattern, page_html):
    block = pattern.search(page_html)
    if not block:
        return []
    items = [clean_text(item) for item in LIST_ITEM_RE.findall(block.group(1))]
    return [item for item in items if item]


def extract_attributes(page_html):
    """All label -> [values] pairs of the page; repeated labels are merged."""
    attributes = {}
    for label, dd_block in ATTRIBUTE_RE.findall(page_html):
        values = attributes.setdefault(clean_text(label), [])
        for raw_value in DD_RE.findall(dd_block):
            value = clean_text(raw_value)
            if value and value not in values:
                values.append(value)
    return {label: values for label, values in attributes.items() if values}


def length_range_cm(text):
    """(min_cm, max_cm) from 'Height: 50 ft. 0 in. - 135 ft. 0 in.' or (None, None)."""
    lengths = [round((int(feet) * 12 + int(inches)) * CM_PER_INCH) for feet, inches in LENGTH_RE.findall(text)]
    if not lengths:
        return None, None
    return min(lengths), max(lengths)


def zone_range(text):
    """(min_zone, max_zone) from a USDA hardiness zone list or (None, None)."""
    zones = [int(zone) for zone in ZONE_RE.findall(text) if 1 <= int(zone) <= 13]
    if not zones:
        return None, None
    return min(zones), max(zones)


def extract_plant(page_html):
    """One plant record, or None for a page without a plant name. Missing values stay None / empty."""
    title = TITLE_RE.search(page_html)
    heading = clean_text(title.group(1)) if title else ""
    scientific_name = heading.split(" (", 1)[0].strip()
    if not scientific_name:
        return None

    attributes = extract_attributes(page_html)
    dimensions = attributes.get("Dimensions", [])
    height = next((value for value in dimensions if value.startswith("Height")), "")
    width = next((value for value in dimensions if value.startswith("Width")), "")
    height_min_cm, height_max_cm = length_range_cm(height)
    width_min_cm, width_max_cm = length_range_cm(width)
    zone_min, zone_max = zone_range(" ".join(attributes.get("USDA Plant Hardiness Zone", [])))

    return {
        "scientific_name": scientific_name,
        "authority": None,  # NCSU prints the bare name without an author abbreviation
        "common_names": _list_items(COMMON_NAMES_RE, page_html),
        "synonyms": _list_items(SYNONYMS_RE, page_html),
        "genus": " ".join(attributes.get("Genus", [])),
        "species": " ".join(attributes.get("Species", [])),
        "family": " ".join(attributes.get("Family", [])),
        "height_min_cm": height_min_cm,
        "height_max_cm": height_max_cm,
        "width_min_cm": width_min_cm,
        "width_max_cm": width_max_cm,
        "zone_min": zone_min,
        "zone_max": zone_max,
        "description": " ".join(attributes.get("Description", [])),
        "attributes": attributes,
    }
