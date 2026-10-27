"""Regex entity extraction for pfaf.org (Plants For A Future) plant pages.

Patterns are anchored on visible labels: the rows of the summary table
("<b>Family</b>"), the section headings ("<h2>Edible Uses</h2>") and labels inside
the text ("Suitable pH:"). Where the page shows no label, two structural anchors
remain: the ASP.NET id of the page heading and the glossary links that mark the use
categories. Short labelled values go to `attributes`; the long prose sections become
their own fields (edible_uses, cultivation, ...) and are joined into `description`.
"""

import html
import re

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
# Commented-out markup (an old book banner, a QR-code block with its own <h2>)
# is not visible on the page, so it is removed first.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# "<h1><span id=...lbldisplatinname>Ribes odoratum - H.L.Wendl.</span></h1>": the
# heading has no visible label, so its id is the anchor. Soft 404s and the sitemap
# test entries ("harishtest") render the same template with this span empty.
HEADING_RE = re.compile(r'<span id="ContentPlaceHolder1_lbldisplatinname"[^>]*>(.*?)</span>', re.DOTALL)
# "Ribes odoratum - H.L.Wendl." / "Fragaria - ." / "Santalum freycinetianum -"
NAME_AUTHORITY_RE = re.compile(r"^(?P<name>.+?)\s+-(?:\s+(?P<authority>.*))?$")
# "Cimicifuga racemosa (Actaea racemosa)": the bracketed name is an alternative name.
BRACKETED_NAME_RE = re.compile(r"\s*\(([A-Z][a-z]+ [a-z][a-z-]+)\)")

# Summary table row: "<td><b>Family</b></td><td>...value...</td>". The label cell
# may carry an "(info)" link; a value cell with a nested table (the "Care" row) is
# left to CARE_RE.
TABLE_ROW_RE = re.compile(
    r"<td[^>]*>\s*<b>\s*([^<]+?)\s*</b>\s*(?:<a\b[^>]*>.*?</a>\s*)?</td>\s*<td[^>]*>((?:(?!<table|</td>).)*)</td>",
    re.DOTALL | re.IGNORECASE)
# The "Care" row shows icons; their title text ("Full sun", "Moist Soil") is the value.
CARE_RE = re.compile(r"<b>\s*Care\s*</b>.*?<table\b[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
ICON_TITLE_RE = re.compile(r"""\btitle=['"]([^'"]+)['"]""")
RATING_RE = re.compile(r"\((\d)\s+of\s+5\)")

# Section heading followed by its value span; the tempered dot stops at the next
# heading so an empty or missing section never borrows the next one's text.
SECTION_TEMPLATE = r"<h([23])[^>]*>\s*{label}\s*</h\1>(?:(?!<h[1-6][\s>]).)*?<span\b[^>]*>(.*?)</span>"
# "Botanical References" is left out on purpose: the site concatenates the
# reference numbers without separators ("43200235" for [43], [200], [235]).
SECTION_LABELS = (
    "Summary", "Physical Characteristics", "Synonyms", "Plant Habitats", "Edible Uses",
    "Medicinal Uses", "Other Uses", "Special Uses", "Cultivation details", "Plant Propagation",
    "Other Names", "Native Range", "Weed Potential", "Conservation Status", "Author",
)
SECTION_RES = {
    label: re.compile(SECTION_TEMPLATE.format(label=re.escape(label)), re.DOTALL | re.IGNORECASE)
    for label in SECTION_LABELS
}

# Use categories are glossary links ("Search_Use.aspx?glossary=Tea") in front of
# the prose of the uses sections.
GLOSSARY_LINK_RE = re.compile(r"""<a\b[^>]*href=['"]Search_Use\.aspx\?glossary=[^'"]*['"][^>]*>(.*?)</a>""",
                              re.DOTALL | re.IGNORECASE)
EDIBLE_PARTS_RE = re.compile(r"Edible Parts:(.*?)(?:<br|$)", re.DOTALL | re.IGNORECASE)
EDIBLE_USES_RE = re.compile(r"Edible Uses:(.*?)(?:<br|$)", re.DOTALL | re.IGNORECASE)
EDIBLE_LABEL_RE = re.compile(r"Edible (?:Parts|Uses):", re.IGNORECASE)
PARAGRAPH_BREAK_RE = re.compile(r"<br\s*/?>\s*<br\s*/?>", re.IGNORECASE)
# Boilerplate repeated on hundreds of pages; only noise for full-text search.
MEDICINAL_DISCLAIMER_RE = re.compile(r"<i>\s*Plants For A Future can not take any responsibility.*?</i>",
                                     re.DOTALL | re.IGNORECASE)
HEAT_ZONE_NOTE_RE = re.compile(r"\(Plant Hardiness Zones show how well plants withstand.*?through 1\.\)", re.DOTALL)
POLYCULTURE_NOTE_RE = re.compile(
    r"For polyculture design as well as the above-ground architecture.*?given here if available\.", re.DOTALL)
# "None known" stays in the fields as printed but is left out of the description.
NONE_KNOWN_RE = re.compile(r"^(?:Other Uses:?\s*)?None known\.?$", re.IGNORECASE)
# "Coming soon" (USDA hardiness, Native Range) means the database has no value
# yet; sometimes the real value follows it ("Coming Soon NORTHERN AMERICA: ...").
COMING_SOON_RE = re.compile(r"^Coming soon\b\.?\s*", re.IGNORECASE)
# Older records keep common names and synonyms in a 100-character column: 257
# synonym fields are exactly 100 characters long and end in a cut word
# ("Rehsonia floribu", "Virginia strawber"). The item running into the cut is dropped.
LEGACY_FIELD_WIDTH = 100

# Labelled lists inside prose: "Bloom Color: Pink, White." (Summary),
# "Landscape Uses:Border, Container." (Cultivation details).
INLINE_LIST_LABELS = {"Summary": ("Bloom Color", "Main Bloom Time", "Form"),
                      "Cultivation details": ("Landscape Uses",)}
# The list ends at a full stop or, when the site forgot it, at the next label
# ("Bloom Color: Red Main Bloom Time: Early spring.").
INLINE_LIST_TEMPLATE = (r"\b{label}:\s*((?:(?!\b(?:Bloom Color|Main Bloom Time|Form|Landscape Uses|Special Features"
                        r"|UPDATE)\b)[^.])+)")
INLINE_LIST_RES = {label: re.compile(INLINE_LIST_TEMPLATE.format(label=re.escape(label)))
                   for labels in INLINE_LIST_LABELS.values() for label in labels}

# "IUCN Red List of Threatened Plants Status : Status: Least Concern"
IUCN_LABEL_RE = re.compile(r"^IUCN Red List of Threatened Plants Status\s*:\s*", re.IGNORECASE)
IUCN_NOT_ASSESSED_RE = re.compile(
    r"^(?:This taxon has not yet been assessed|Not (?:yet )?(?:listed|assessed|available)|No (?:data|assessment)"
    r"|None available)", re.IGNORECASE)
IUCN_CATEGORY_RE = re.compile(
    r"\b(Extinct in the Wild|Extinct|Critically Endangered|Endangered|Vulnerable|Near Threatened|Least Concern"
    r"|Data Deficient|Lower Risk/(?:least concern|near threatened|conservation dependent))\b", re.IGNORECASE)

# Physical Characteristics statement, a fixed sentence template:
# "Ribes odoratum is a deciduous Shrub growing to 2.5 m (8ft) by 2.5 m (8ft) at a fast rate."
HABIT_RE = re.compile(
    r"\bis an? (?:(?P<leaf>deciduous|evergreen)\s+)?(?P<habit>[A-Za-z][A-Za-z/ ]*?)??\s*"
    r"(?:growing to (?P<height>\d+(?:\.\d+)?) m\b[^.]*?)?"
    r"(?:\s+by (?P<width>\d+(?:\.\d+)?) m\b[^.]*?)?"
    r"(?:\s+at an? (?P<rate>slow|medium|fast) rate)?\s*\.")
UK_ZONE_RE = re.compile(r"hardy to UK zone (\d+)")
FROST_RE = re.compile(r"\bis (not )?frost tender\b")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
MONTH = "(" + "|".join(MONTHS) + ")"
FLOWERING_RE = re.compile(r"in flower (?:from " + MONTH + " to " + MONTH + "|in " + MONTH + ")")
SOIL_RE = re.compile(r"Suitable for:\s*([^.]*?)\s+soils?\b([^.]*)\.")
PH_RE = re.compile(r"Suitable pH:\s*([^.]*?)\s+soils?\b([^.]*)\.")
CAN_GROW_IN_RE = re.compile(r"can grow in ([^.]*?) soils?\b")
SHADE_RE = re.compile(r"It (?:can grow in ([^.]*?\bshade\b[^.]*)|(cannot grow in the shade))\.")
SHADE_ITEM_RE = re.compile(r"(full shade \(deep woodland\)|semi-shade \(light woodland\)|no shade)")
MOISTURE_RE = re.compile(r"It prefers ([^.]*?) soil")
MOISTURE_ITEM_RE = re.compile(r"\b(dry|moist|wet)\b")
WATER_RE = re.compile(r"\bcan grow in water\b")
TOLERATE_RE = re.compile(r"\bcan tolerates? (drought|maritime exposure|strong winds|atmospheric pollution)\b")
LIST_SPLIT_RE = re.compile(r",\s*|\s+and\s+")

# Synonyms come in two styles: abbreviated genera with authorities in their own
# chunks ("R. aureum. non Pursh. R. fragrans.") and full names with authorities
# ("Vitex allasia Planch. Vitex ..."). An authority may stand before a rank marker
# ("Trifolium repens L. var. atropurpureum"). Authority particles and English words
# ("No synonyms are recorded for this name.") are not epithets.
NOT_EPITHET = (
    r"(?:ex|non|nec|auct|nom|illeg|sensu|sec|et|al|in|pro|parte|emend|hort|sp|spp|de|van|von|la|le|du|di|da"
    r"|and|or|is|are|a|an|the|of|as|to|on|by|for|with|from|this|that|see|also|part|name|names|synonym|synonyms"
    r"|variant|unresolved|unplaced|recorded|known|misspelt|published)\b(?!-)")
# "(?!\.[a-z])": not the first part of a lowercase abbreviation chain ("nom.illeg.").
EPITHET = r"(?!" + NOT_EPITHET + r")[a-z][a-z-]+\b(?!\.[a-z])"
SYNONYM_RE = re.compile(
    r"(?<![\w'])(?P<genus>[A-Z][a-z]+|[A-Z]\.)\s+(?P<hybrid>[x×]\.?\s+)?(?P<epithet>" + EPITHET + r")"
    r"(?P<infra>(?:\s+(?:(?:[A-Z(]\S*\s+){0,3}?(?:subsp|ssp|var|f)\.\s*)?" + EPITHET + r")*)")
INFRA_TOKEN_RE = re.compile(r"^(?:(?:subsp|ssp|var|f)\.|[a-z][a-z-]+)$")

# Prose sections joined into the description, in page order.
DESCRIPTION_FIELDS = ("summary", "physical_characteristics", "edible_uses", "medicinal_uses", "other_uses",
                      "cultivation", "propagation")


def clean_text(fragment):
    """Strip tags, decode entities and collapse whitespace."""
    return WHITESPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def _or_none(text):
    return text if text else None


def field_text(fragment):
    """Cleaned value of a table cell or section, without the "Coming soon" placeholder."""
    return COMING_SOON_RE.sub("", clean_text(fragment))


def is_cut(fragment):
    """True if the field filled the old 100-character column, i.e. its end may be cut off."""
    return len(html.unescape(TAG_RE.sub("", fragment)).strip()) == LEGACY_FIELD_WIDTH


def unique(items):
    """Items in first-seen order without duplicates and empty strings."""
    return list(dict.fromkeys(item for item in items if item))


def split_list(text, separators=r"[,;](?![^()]*\))", strip=" ."):
    """'Buffalo Currant, Golden Currant,' -> ['Buffalo Currant', 'Golden Currant'].

    By default a comma inside brackets does not split: "Annatto (Lipstick Plant, Urucum)".
    """
    return unique(item.strip(strip) for item in re.split(separators, text))


def split_heading(heading):
    """('Ribes odoratum', 'H.L.Wendl.') from 'Ribes odoratum - H.L.Wendl.'.

    A bare '.' is no authority, and neither is the name repeated after the dash
    ('Gluta usitata - Gluta usitata'), as the site prints on a few pages.
    """
    match = NAME_AUTHORITY_RE.match(heading)
    if not match:
        return heading, None
    name = match.group("name").strip()
    authority = (match.group("authority") or "").strip()
    if not authority.strip(".") or authority.rstrip(".") == name:
        return name, None
    return name, authority


def extract_table(page_html):
    """Label -> raw cell HTML of the summary table at the top of the page."""
    return {clean_text(label): cell for label, cell in TABLE_ROW_RE.findall(page_html)}


def extract_sections(page_html):
    """Section heading -> raw HTML of its value span (only sections that exist)."""
    sections = {}
    for label, pattern in SECTION_RES.items():
        match = pattern.search(page_html)
        if match:
            sections[label] = match.group(2)
    return sections


def rating(cell):
    """3 from '(3 of 5)', None when the cell has no rating."""
    match = RATING_RE.search(clean_text(cell or ""))
    return int(match.group(1)) if match else None


def zone_range(text):
    """(min_zone, max_zone) from '4-8'; (None, None) for 'Coming soon'."""
    zones = [int(zone) for zone in re.findall(r"\b\d{1,2}\b", text) if 1 <= int(zone) <= 13]
    if not zones:
        return None, None
    return min(zones), max(zones)


def month_span(first, last):
    """['November', 'December', 'January'] for ('November', 'January'), wrapping the year."""
    start, end = MONTHS.index(first), MONTHS.index(last)
    return [MONTHS[(start + step) % 12] for step in range((end - start) % 12 + 1)]


def glossary_tags(fragment):
    """Texts of the glossary links ("Tea", "Fruit") in a fragment."""
    return unique(clean_text(tag) for tag in GLOSSARY_LINK_RE.findall(fragment))


def split_uses(section_html):
    """(tags, prose) of a uses section: glossary tag lines first, then the prose.

    The tag block ends with the first blank line ("<br><br>"); it only counts as a
    tag block if nothing but tags, tag labels and the disclaimer stands before it.
    """
    body = MEDICINAL_DISCLAIMER_RE.sub("", section_html)
    parts = PARAGRAPH_BREAK_RE.split(body, 1)
    prose_html = body
    if len(parts) == 2 and not clean_text(EDIBLE_LABEL_RE.sub("", GLOSSARY_LINK_RE.sub("", parts[0]))):
        prose_html = parts[1]
    return glossary_tags(body), clean_text(prose_html)


def edible_lists(section_html):
    """(edible parts, edible use tags) from the "Edible Parts:" / "Edible Uses:" lines."""
    parts = EDIBLE_PARTS_RE.search(section_html)
    uses = EDIBLE_USES_RE.search(section_html)
    return (glossary_tags(parts.group(1)) if parts else [], glossary_tags(uses.group(1)) if uses else [])


def parse_synonyms(text, genus, cut=False):
    """Names from the Synonyms field, authorities removed, abbreviated genera expanded.

    An initial ("R.") stands for the last genus spelled out with that letter, or
    for the page's own genus; an initial nothing explains is kept as printed.
    With cut=True a name that runs up to the end of the text is incomplete.
    """
    known = {genus[0]: genus} if genus else {}
    names = []
    for match in SYNONYM_RE.finditer(text):
        if cut and match.end() == len(text):
            break
        name_genus = match.group("genus")
        if name_genus.endswith("."):
            name_genus = known.get(name_genus[0], name_genus)
        else:
            known[name_genus[0]] = name_genus
        words = [name_genus] + (["x"] if match.group("hybrid") else []) + [match.group("epithet")]
        words += [token for token in match.group("infra").split() if INFRA_TOKEN_RE.match(token)]
        names.append(" ".join(words))
    return unique(names)


def parse_physical(statement):
    """Typed values from the Physical Characteristics statement."""
    facts = {"habit": None, "leaf_type": None, "height_cm": None, "width_cm": None, "growth_rate": None,
             "uk_hardiness_zone": None, "frost_tender": None, "flowering_months": [], "soil": [], "ph": [],
             "light": [], "moisture": [], "tolerates": []}
    habit = HABIT_RE.search(statement)
    if habit:
        # The site prints the habit either capitalised or upper case ("Shrub", "PERENNIAL").
        facts["habit"] = habit.group("habit").strip().title() if habit.group("habit") else None
        facts["leaf_type"] = habit.group("leaf")
        facts["growth_rate"] = habit.group("rate")
        for key, group in (("height_cm", "height"), ("width_cm", "width")):
            metres = float(habit.group(group)) if habit.group(group) else 0
            # "growing to 0 m" is a placeholder in the database, not a measurement.
            facts[key] = round(metres * 100) if metres > 0 else None
    zone = UK_ZONE_RE.search(statement)
    facts["uk_hardiness_zone"] = int(zone.group(1)) if zone else None
    frost = FROST_RE.search(statement)
    facts["frost_tender"] = None if not frost else frost.group(1) is None
    flowering = FLOWERING_RE.search(statement)
    if flowering:
        first, last, single = flowering.groups()
        facts["flowering_months"] = month_span(first, last) if first else [single]
    soil = SOIL_RE.search(statement)
    ph = PH_RE.search(statement)
    for key, match in (("soil", soil), ("ph", ph)):
        if match:
            facts[key] = split_list(match.group(1), LIST_SPLIT_RE)
            tolerance = CAN_GROW_IN_RE.search(match.group(2))
            if tolerance:
                facts["tolerates"] += split_list(tolerance.group(1), LIST_SPLIT_RE)
    shade = SHADE_RE.search(statement)
    if shade:
        # "It cannot grow in the shade." is how the site prints the "no shade" class
        # alone (these pages all show the "Full sun" Care icon).
        facts["light"] = SHADE_ITEM_RE.findall(shade.group(1)) if shade.group(1) else ["no shade"]
    moisture = MOISTURE_RE.search(statement)
    if moisture:
        facts["moisture"] = MOISTURE_ITEM_RE.findall(moisture.group(1))
    if WATER_RE.search(statement):
        facts["moisture"].append("water")
    facts["tolerates"] = unique(facts["tolerates"] + TOLERATE_RE.findall(statement))
    return facts


def iucn(status_text):
    """(status text after the label, IUCN category or None)."""
    text = IUCN_LABEL_RE.sub("", status_text).strip()
    if not text:
        return None, None
    category = None
    if not IUCN_NOT_ASSESSED_RE.match(text):
        match = IUCN_CATEGORY_RE.search(text)
        if match:
            category = match.group(1)
            category = category[0].upper() + category[1:] if "/" in category else category.title()
            category = category.replace(" In The ", " in the ")
    return text, category


def extract_plant(page_html):
    """One plant record, or None for soft 404s and test entries. Missing values stay None / empty."""
    page_html = COMMENT_RE.sub("", page_html)
    heading_match = HEADING_RE.search(page_html)
    heading = clean_text(heading_match.group(1)) if heading_match else ""
    if not heading:
        return None
    name, authority = split_heading(heading)
    alternative_names = BRACKETED_NAME_RE.findall(name)
    scientific_name = BRACKETED_NAME_RE.sub("", name).strip()
    first_word = scientific_name.split()[0]
    genus = first_word if re.match(r"^[A-Z][a-z]+$", first_word) else None

    table = extract_table(page_html)
    sections = extract_sections(page_html)
    text = {label: field_text(value) for label, value in sections.items()}
    row = {label: field_text(cell) for label, cell in table.items()}

    synonyms_cut = is_cut(sections.get("Synonyms", ""))
    synonyms = unique(alternative_names + parse_synonyms(text.get("Synonyms", ""), genus, synonyms_cut))
    synonyms = [synonym for synonym in synonyms if synonym != scientific_name]
    common_names = split_list(row.get("Common Name", ""))
    if common_names and is_cut(table.get("Common Name", "")) and not row["Common Name"].endswith((",", ";", ".")):
        common_names.pop()

    statement = text.get("Physical Characteristics", "")
    facts = parse_physical(statement)
    zone_min, zone_max = zone_range(row.get("USDA hardiness", ""))

    edible_parts, edible_tags = edible_lists(sections.get("Edible Uses", ""))
    _, edible_prose = split_uses(sections.get("Edible Uses", ""))
    medicinal_tags, medicinal_prose = split_uses(sections.get("Medicinal Uses", ""))
    other_tags, other_prose = split_uses(sections.get("Other Uses", ""))
    special_tags = glossary_tags(sections.get("Special Uses", ""))

    cultivation = POLYCULTURE_NOTE_RE.sub("", HEAT_ZONE_NOTE_RE.sub("", text.get("Cultivation details", "")))
    iucn_text, iucn_category = iucn(text.get("Conservation Status", ""))
    weed_text = _or_none(text.get("Weed Potential", ""))

    attributes = {}

    def add(label, values):
        values = unique(attributes.get(label, []) + list(values))
        if values:
            attributes[label] = values

    add("Common Name", common_names)
    for label in ("Family", "USDA hardiness", "Known Hazards", "Habitats", "Range", "Weed Potential"):
        add(label, [row.get(label, "")])
    # The table labels the rating row "Other Uses", like the section, so it is
    # stored as "Other Uses Rating".
    for label, key in (("Edibility Rating", "Edibility Rating"), ("Other Uses", "Other Uses Rating"),
                       ("Medicinal Rating", "Medicinal Rating")):
        value = rating(table.get(label))
        add(key, ["{} of 5".format(value)] if value is not None else [])
    care = CARE_RE.search(page_html)
    add("Care", ICON_TITLE_RE.findall(care.group(1)) if care else [])
    add("Synonyms", [text.get("Synonyms", "")])
    # "Woodland Garden&nbsp;Sunny Edge;&nbsp;South Wall. By." - items are separated
    # by the non-breaking space; the trailing dots belong to the item ("By." = by a wall).
    habitats_html = sections.get("Plant Habitats", "").replace("&nbsp;", ";")
    add("Plant Habitats", split_list(clean_text(habitats_html), strip=" "))
    add("Edible Parts", edible_parts)
    add("Edible Uses", edible_tags)
    add("Medicinal Uses", medicinal_tags)
    add("Other Uses", other_tags)
    add("Special Uses", special_tags)
    add("Other Names", split_list(text.get("Other Names", "")))
    add("Native Range", [text.get("Native Range", "")])
    # The "Weed Potential" section is the long form of the Yes/No table row of the
    # same name, so both values go under one label.
    add("Weed Potential", [weed_text])
    add("Conservation Status", [iucn_text])
    add("Author", [text.get("Author", "")])
    add("Suitable for", facts["soil"])
    add("Suitable pH", facts["ph"])
    for section, labels in INLINE_LIST_LABELS.items():
        for label in labels:
            match = INLINE_LIST_RES[label].search(text.get(section, ""))
            add(label, split_list(match.group(1)) if match else [])

    record = {
        "scientific_name": scientific_name,
        "authority": authority,
        "family": _or_none(row.get("Family")),
        "genus": genus,
        "common_names": common_names,
        "synonyms": synonyms,
        "zone_min": zone_min,
        "zone_max": zone_max,
        # PFAF states one size, "growing to 2.5 m": a maximum, the minimum is unknown.
        "height_min_cm": None,
        "height_max_cm": facts["height_cm"],
        "width_min_cm": None,
        "width_max_cm": facts["width_cm"],
        "habit": facts["habit"],
        "leaf_type": facts["leaf_type"],
        "growth_rate": facts["growth_rate"],
        "uk_hardiness_zone": facts["uk_hardiness_zone"],
        "frost_tender": facts["frost_tender"],
        "flowering_months": facts["flowering_months"],
        "light": facts["light"],
        "soil": facts["soil"],
        "ph": facts["ph"],
        "moisture": facts["moisture"],
        "tolerates": facts["tolerates"],
        "edibility_rating": rating(table.get("Edibility Rating")),
        "medicinal_rating": rating(table.get("Medicinal Rating")),
        "other_uses_rating": rating(table.get("Other Uses")),
        "edible_parts": edible_parts,
        "summary": _or_none(text.get("Summary", "")),
        "physical_characteristics": _or_none(statement),
        "edible_uses": _or_none(edible_prose),
        "medicinal_uses": _or_none(medicinal_prose),
        "other_uses": _or_none(other_prose),
        "cultivation": _or_none(WHITESPACE_RE.sub(" ", cultivation).strip()),
        "propagation": _or_none(text.get("Plant Propagation", "")),
        "hazards": _or_none(row.get("Known Hazards")),
        "range": _or_none(row.get("Range")),
        "habitat": _or_none(row.get("Habitats")),
        "native_range": _or_none(text.get("Native Range", "")),
        "weed_potential": _or_none(row.get("Weed Potential")),
        "weed_potential_text": weed_text,
        "iucn_status": iucn_text,
        "iucn_category": iucn_category,
        "attributes": attributes,
    }
    record["description"] = "\n\n".join(
        record[field] for field in DESCRIPTION_FIELDS if record[field] and not NONE_KNOWN_RE.match(record[field]))
    return record
