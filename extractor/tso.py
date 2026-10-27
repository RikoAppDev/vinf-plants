"""Regex entity extraction for Trees and Shrubs Online (treesandshrubsonline.org) article pages.

Fields are anchored on their visible labels: the sidebar headings ("Family", "Genus",
"Common Names", "Synonyms") and the bold labels of the article header ("Distribution",
"Habitat", "USDA Hardiness Zone", "RHS Hardiness Rating", "Conservation status", "Awards", ...).
The article prose has no label, so the description needs a structural anchor: the main
column (class tso-col-main) and the image caption cards inside it (class tso-caption).
"""

import html
import re

# Hidden off-canvas glossary panel. Its definitions mention "IUCN", "Endangered",
# "Distribution" ..., so it is removed before anything else is matched.
GLOSSARY_RE = re.compile(r"<div id=offcanvas-glossary\b.*?</dl>", re.DOTALL)
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)

CANONICAL_RE = re.compile(r"<link rel=canonical href=[\"']?([^\"'\s>]+)", re.IGNORECASE)
# The first <h1> is the page title; "From New Trees" sections inside the text add a second one.
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
# The H1 prints "Genus species Authority" on one line; the site wraps the authority in
# span.authors, the only reliable boundary (authorities may contain italics, e.g. "<i>ex</i>").
AUTHORS_RE = re.compile(r"<span class=[\"']?authors[\"']?>(.*)</span>", re.DOTALL)
TRADE_MARK_RE = re.compile(r"<span class=[\"']?trade\b")

# Sidebar block: "<h3>Family</h3><ul ...><li>Pinaceae</ul>". The <li> elements are not closed.
SIDEBAR_TEMPLATE = r"<h3[^>]*>\s*{}\s*</h3>\s*<ul[^>]*>(.*?)</ul>"
LI_SPLIT_RE = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
# Left column: "<h2>Credits</h2><p>Tom Christian (2021)<p><b>Recommended citation</b>".
CREDITS_RE = re.compile(r"<h2>\s*Credits\s*</h2>(.*?)<b>\s*Recommended citation", re.DOTALL)

# Main column of the article, up to the page footer.
MAIN_COLUMN_RE = re.compile(r"class=[\"'][^\"']*\btso-col-main\b[^\"']*[\"']>(.*?)"
                            r"<div class=[\"'][^\"']*\btso-footer\b", re.DOTALL)
# Start of the article prose; everything before it is the header with the labelled fields.
MAIN_TEXT_RE = re.compile(r"<div class=[\"']?tso-main-text[\"']?>")
# Image caption cards: figure captions are not prose.
CAPTION_RE = re.compile(r"<div class=[\"'][^\"']*\btso-caption\b[^\"']*[\"']>.*?</div>", re.DOTALL)
# Boxed "Editorial Note" at the top of some articles; skipped when looking for the plant's height.
EDITORIAL_NOTE_RE = re.compile(r"<h3>\s*Editorial Note\s*</h3>.*?</div>", re.DOTALL)

# Bold labels of the article header. Revised articles print "<p><b>Habitat&ensp;</b>value",
# texts taken from New Trees print them inline: "... <b>Habitat</b> value. <b>USDA Hardiness Zone</b> 7."
# (83 pages use <strong> instead of <b>). A whitelist keeps bold cultivar names in the prose
# from being read as labels.
HEADER_LABEL_RE = re.compile(
    r"<(?:b|strong)>\s*(Distribution|Habitat|USDA\s*Hardi\s*ness\s*Zone|RHS Hardiness(?: Rating)?|"
    r"Conservation status|Taxonomic note|Awards|Illustration|Cross-references?|Season)"
    r"\s*(?:&ensp;|&nbsp;|&thinsp;|\s)*</(?:b|strong)>")
VALUE_END_RE = re.compile(r"<p\b|</div>", re.IGNORECASE)
ENSP_RE = re.compile(r"&ensp;|&#8194;|\u2002")

FRACTION_RE = re.compile(r"<span class=[\"']?fnum[\"']?>(\d+)</span>\s*⁄\s*<span class=[\"']?fden[\"']?>(\d+)</span>")
# Tags are matched with their quoted attributes: caption anchors carry data-caption="<p>...</p>",
# so a plain <[^>]+> would stop inside the attribute and leak the caption into the text.
TAG_BODY = r"(?:[^>\"']|\"[^\"]*\"|'[^']*')*"
BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|dl|dt|dd|h[1-6]|hr|table|tr|td|th|sup|sub|blockquote)\b"
                          + TAG_BODY + ">", re.IGNORECASE)
TAG_RE = re.compile(r"<" + TAG_BODY + ">")
WHITESPACE_RE = re.compile(r"\s+")
# Zero-width spaces and soft hyphens ("bristle&shy;like") would split or glue words.
INVISIBLE_RE = re.compile("[\u200b\u00ad]")
TRADE_SIGN_RE = re.compile(r"\s+([™®])")

# Name of a synonym: leading italic parts, quoted cultivar epithets, trade names, hybrid signs and
# rank words ("<i>Abies alba </i>subsp. <i>apennina</i> Brullo ..."); the rest of the item is the authority.
SYNONYM_NAME_RE = re.compile(
    r"^(?:\s|<i>.*?</i>|'[^'<]+'|‘[^’<]+’|<span class=[\"']?trade[\"']?>.*?</span>|×|\+|"
    r"[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*\s+(?:Group|Hybrids|Series)\b|"  # "<i>Hydrangea aspera</i> Villosa Group"
    r"(?:subsp|ssp|var|f|forma|nothosubsp|nothovar|subvar|lusus)\.?(?=\s*<i>))+", re.DOTALL)
# Hybrid formula with authors between the parents: "<i>Senecio laxifolius</i> Buchanan × <i>S. compactus</i> Kirk".
# (Words before the "×" are required, so "<i>B</i>. × <i>irwinii</i>" stays a plain nothospecies name.)
FORMULA_REST_RE = re.compile(r"^[^×]*[A-Za-z][^×]*×\s*\(?\s*<i>")
ITALIC_SPLIT_RE = re.compile(r"(<i>.*?</i>)", re.DOTALL)
# Remarks after which italics are other names, not part of the formula ("Hort., not <i>S. greyi</i>").
REMARK_WORD_RE = re.compile(r"\b(?:not|non|nec|sensu|auct|excl|incl|fide)\b|\[")
# A synonym needs an epithet: junk like "D. 0", "Gard. Chron" (a journal) or "S. Cantab" is dropped.
# (Old hyphenated epithets may be capitalised: "Amygdalus Amygdalo-Persica".)
EPITHET_RE = re.compile(r"\s[a-z][a-z-]+|\s[A-Z][a-z]+-[A-Za-z][a-z]+|['‘]|\b(?:Group|Hybrids|Series|Cultivars)\b")
# Fallback for items printed without italics: "A. canadensis var. japonica Miq.", "Acer 'Red Flamingo'".
PLAIN_NAME_RE = re.compile(
    r"^[A-Z][a-z]*\.?(?:\s*×)?\s+(?:[a-z][a-z-]+(?:\s+(?:subsp|ssp|var|f|forma)\.\s+[a-z][a-z-]+)?|['‘][^'’]+['’])")
# Nomenclatural remarks and stray authorities that are sometimes printed inside the italics:
# "<i>Fraxinus longicuspis sensu</i>", "<i>Annona triloba L</i>", "<i>Cynoxylon kousa (</i>".
QUALIFIER_RE = re.compile(r"\s+(?:sensu|sens\.?|smsu|sec\.?|auct\.?|non|not|nom\.|in part|orthog\.|p\.\s?p\.|"
                          r"pro parte|s\.\s?l\.|s\.\s?str\.|emend\.?|ex|fide)(?:\s.*)?$")
# Capitalised words after a lowercase epithet are an authority ("Salix spaethii Koopmann",
# "Rosa pteragonis W. Krause"), unless the item is a trade designation ("Acer davidii Viper").
TRAILING_AUTHORITY_RE = re.compile(r"^(.*?\s[a-z][a-z-]+)(\s+[A-Z][a-z]*\.?(?:\s+(?:[A-Z][a-z]*\.?|f\.|&|ex|et))*)$")
# Items that are an authority or a remark, not a name: "(Ronniger) Ronniger", "fide Rehd. & Wils.".
REMARK_RE = re.compile(r"^(?:\(|(?:fide|sensu|non|not|auct)\b)")
ABBREVIATED_GENUS_RE = re.compile(r"^([A-Z])(?:\.\s*|\s+)(?=[a-z×])")
GENUS_WORD_RE = re.compile(r"^[×+]?([A-Z][a-z-]{2,})\b")

# Article type from the H1 text.
GROUP_RE = re.compile(r"\b(?:Group|Hybrids?|hybrids?|Series|Cultivars?|cultivars?)\b")
CULTIVAR_RE = re.compile(r"['‘][^'’]+['’]")
SPECIES_RE = re.compile(r"^[×+]?[A-Z][a-z]+(?: [×+])? [a-z][a-z-]+"
                        r"(?: (?:subsp|ssp|var|f|forma|nothosubsp|nothovar)\. [a-z][a-z-]+)?$")

# "4-7", "8b-9a", "(9–)10." -> every zone number counts.
ZONE_NUMBER_RE = re.compile(r"(?<!\d)(\d{1,2})[ab]?(?!\d)")
RHS_RE = re.compile(r"^H\d")

# IUCN Red List categories as printed on the page ("Least concern (LC)", "Not evaluated.").
CONSERVATION_RE = re.compile(
    r"^(extinct in the wild|extinct|critically endangered|endangered|vulnerable|near threatened|"
    r"lower risk(?:/near threatened)?|least concern|data deficient|not evaluated)\b(?:\s*\(([A-Z]{2})\))?",
    re.IGNORECASE)
IUCN_CODES = {
    "extinct in the wild": "EW", "extinct": "EX", "critically endangered": "CR", "endangered": "EN",
    "vulnerable": "VU", "near threatened": "NT", "lower risk": "LR", "lower risk/near threatened": "LR",
    "least concern": "LC", "data deficient": "DD", "not evaluated": "NE",
}

# RHS awards inside the free-text "Awards" field: "AM 1973 (foliage); FCC 1979", "RHS AGM", "AGM 1993".
AWARD_RE = re.compile(
    r"\b(AGM|AM|FCC|PC|Award of Garden Merit|Award of Merit|First Class Certificate|Preliminary Commendation|"
    r"Plants for [Pp]ollinators)\b(?:\s*\(?(?:in\s+)?(\d{4})\b)?")

# Height from the first clause of the botanical description, only after a habit word:
# "Tree to 60 m tall", "A deciduous tree 40 to 60 ft high".
FIRST_CLAUSE_RE = re.compile(r"^(.*?)(?:;|\.\s+(?=[A-Z])|$)", re.DOTALL)
HABIT_RE = re.compile(r"\b(?:tree|treelet|shrub|subshrub|sub-shrub|undershrub|shrubby|bush|climber|liana|vine|"
                      r"mallee|palm|plant)s?\b", re.IGNORECASE)
# 2, 2.5, 1 1/2 (Bean's fractions, see clean_text) or 1/2.
NUMBER = r"\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+"
HEIGHT_RE = re.compile(
    r"(?<![\d/.,×])(?:(?:c\.|ca\.|about|~)\s*)?(?:\((?P<low>" + NUMBER + r")\s*[–-]\)\s*)?"
    r"(?P<a>" + NUMBER + r")(?:\s*(?:–|-|to|or)\s*(?P<b>" + NUMBER + r"))?"
    r"(?:\s*\(\s*[–-]\s*(?P<high>" + NUMBER + r")\s*\))?(?:\s+or more)?"
    r"\s*(?P<unit>m|cm|ft|in\.|metres?|meters?|feet|foot|inches)(?![a-zA-Z])(?:\s+or more)?"
    r"(?!\s*(?:long|in length|wide|in width|across|broad|spread|through|round|apart|diameter|in diameter|"
    r"circumference|in circumference|girth|in girth|dbh|thick|deep|asl|a\.s\.l|above sea|altitude|elevation))")
# Not a height when announced before the number: altitudes ("found at 3000 m", "ascends to 4500 ft")
# and trunk sizes ("when arborescent dbh typically <40 cm", "trunk to 1.3 m").
NOT_HEIGHT_BEFORE_RE = re.compile(r"\b(?:at|ascends?\s+to|altitudes?\s+(?:of|up\s+to)|elevations?\s+(?:of|up\s+to))\s*$"
                                  r"|\b(?:dbh|girth|diameter|trunk|bole)\b[^,;()]*$")
CM_PER_UNIT = {"m": 100.0, "metre": 100.0, "metres": 100.0, "meter": 100.0, "meters": 100.0, "cm": 1.0,
               "ft": 30.48, "feet": 30.48, "foot": 30.48, "in.": 2.54, "inches": 2.54}


def clean_text(fragment):
    """Strip tags, decode entities and collapse whitespace.

    Block tags and <sup>/<sub> become a space ("30<sup>0</sup>C" must not read "300C"); inline
    tags are removed without one, so "<i>f</i><i>oggii</i>" stays one word. Trade mark
    signs are re-attached ("FLUTTERBY<sup>™</sup>" -> "FLUTTERBY™").
    """
    fragment = FRACTION_RE.sub(r" \1/\2", fragment)
    fragment = TAG_RE.sub("", BLOCK_TAG_RE.sub(" ", fragment))
    text = WHITESPACE_RE.sub(" ", INVISIBLE_RE.sub("", html.unescape(fragment))).strip()
    return TRADE_SIGN_RE.sub(r"\1", text)


def _sidebar_items(label, page_html):
    """Non-empty <li> items (HTML) under a sidebar heading, or [] if the heading is missing."""
    block = re.search(SIDEBAR_TEMPLATE.format(re.escape(label)), page_html, re.DOTALL | re.IGNORECASE)
    if not block:
        return []
    return [item for item in LI_SPLIT_RE.split(block.group(1))[1:] if clean_text(item)]


def _unique(values):
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def expand_genus(name, genera):
    """'A. polymorphum' -> 'Acer polymorphum'.

    Botanical convention: an abbreviated genus stands for the last genus written out with that
    initial (the page genus or an earlier synonym). Without such a genus the name stays as printed.
    """
    match = ABBREVIATED_GENUS_RE.match(name)
    if match:
        for genus in reversed(genera):
            if genus and genus.startswith(match.group(1)):
                return genus + " " + name[match.end():]
    return name


def tidy_name(name):
    """Normalise a printed name: doubtful '?' mark, 'incl.', hybrid / graft sign, repeated name."""
    name = re.sub(r"^(?:\?\s*|incl\.\s+)", "", name).rstrip(" (,;:")
    name = re.sub(r"^([A-Z][a-z]+) x (?=[a-z])", "\\1 × ", name)
    name = re.sub(r"^([×+]) (?=[A-Z])", r"\1", name)
    # A few names are printed twice ("Gaultheria mucronata Gaultheria mucronata").
    return re.sub(r"^(.+) \1$", r"\1", name)


def hybrid_formula(item_html, genera):
    """Parents of a hybrid formula without the authors printed between them.

    '<i>Senecio</i> (<i>compactus</i> Kirk × <i>greyi</i> Hook.f.) × <i>S. greyi</i> Hook.f.'
    -> 'Senecio (compactus × greyi) × Senecio greyi'. Only italics, '×' and brackets are kept.
    """
    parts = []
    for chunk in ITALIC_SPLIT_RE.split(item_html):
        if chunk.startswith("<i>"):
            parts.append(clean_text(chunk))
        elif REMARK_WORD_RE.search(chunk):
            break
        else:
            parts.append(re.sub(r"[^×()]", " ", chunk))
    text = WHITESPACE_RE.sub(" ", " ".join(parts))
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s*\)", ")", re.sub(r"\(\s*", "(", text)).strip()
    return " × ".join(expand_genus(parent, genera) for parent in text.split(" × "))


def synonym_names(items_html, genus, accepted=None):
    """Names of the sidebar synonyms without their authorities, genus abbreviations expanded.

    A synonym equal to the accepted name (a homonym printed with another authority) is dropped.
    """
    names, genera = [], [genus]
    for item_html in items_html:
        match = SYNONYM_NAME_RE.match(item_html)
        name = clean_text(match.group(0)) if match else ""
        if match and FORMULA_REST_RE.search(item_html[match.end():]):
            names.append(hybrid_formula(item_html, genera))
            continue
        if len(name.split()) < 2:
            # No italics (or only a genus, as in hybrid formulas): fall back to the plain text.
            text = clean_text(item_html)
            plain = PLAIN_NAME_RE.match(text)
            name = plain.group(0) if plain else text
        name = expand_genus(QUALIFIER_RE.sub("", tidy_name(name)), genera)
        tail = TRAILING_AUTHORITY_RE.match(name)
        if tail and not TRADE_MARK_RE.search(item_html) and not GROUP_RE.search(tail.group(2)):
            name = tail.group(1)
        name = tidy_name(name)
        written_out = GENUS_WORD_RE.match(name)
        if written_out:
            genera.append(written_out.group(1))
        if REMARK_RE.match(name) or not (EPITHET_RE.search(name) or TRADE_MARK_RE.search(item_html)):
            continue
        names.append(name)
    return [name for name in _unique(names) if name != accepted]


def parse_heading(h1_html, genus):
    """(scientific_name, authority) from the H1."""
    authors = AUTHORS_RE.search(h1_html)
    name = clean_text(h1_html[:authors.start()] if authors else h1_html)
    authority = clean_text(authors.group(1)) if authors else ""
    # "A wilsonii" (genus abbreviated in the H1), "Rhododendron x candelabrum", "× Kalmiothamnus ..."
    name = expand_genus(tidy_name(name), [genus])
    # Some authorities repeat the name ("Callistemon salignus (Sm.) Colvill ex Sweet").
    if authority.startswith(name + " "):
        authority = authority[len(name):].strip()
    return name, authority or None


def article_type(name, h1_html, canonical_url):
    """'species' | 'cultivar' | 'group' | 'other' from the H1 text (and the 'for-deletion' slug)."""
    if "for-deletion" in canonical_url:
        return "other"
    if GROUP_RE.search(name):
        return "group"
    if CULTIVAR_RE.search(name) or TRADE_MARK_RE.search(h1_html):
        return "cultivar"
    if SPECIES_RE.match(name):
        return "species"
    return "other"


def header_fields(header_html):
    """([(label, value_html)], header_html without the labelled fields)."""
    matches = list(HEADER_LABEL_RE.finditer(header_html))
    fields, rest, position = [], [], 0
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(header_html)
        value = header_html[match.end():end]
        stop = VALUE_END_RE.search(value)
        if stop:
            value = value[:stop.start()]
        # One page prints "USDA Hardi ness Zone"; the label is stored as shown on the other pages.
        label = "USDA Hardiness Zone" if match.group(1).startswith("USDA") else match.group(1)
        fields.append((label, value))
        rest.append(header_html[position:match.start()])
        position = match.end() + len(value)
    rest.append(header_html[position:])
    return fields, "".join(rest)


def distribution_text(value_html):
    """Country entries are separated by en spaces on the page; keep them apart with '; '."""
    entries = [clean_text(entry).rstrip(" .") for entry in ENSP_RE.split(value_html)]
    return "; ".join(entry for entry in entries if entry)


def zone_range(text):
    """(min_zone, max_zone) from a USDA hardiness zone string or (None, None)."""
    zones = [int(zone) for zone in ZONE_NUMBER_RE.findall(text) if 1 <= int(zone) <= 13]
    if not zones:
        return None, None
    return min(zones), max(zones)


def conservation(text):
    """(category, code) from 'Least concern (LC)' / 'Not evaluated (IUCN), but ...' or (None, None)."""
    match = CONSERVATION_RE.match(text)
    if not match:
        return None, None
    category = match.group(1).lower()
    return category[0].upper() + category[1:], match.group(2) or IUCN_CODES[category]


def awards(text):
    """['AM 1973', 'FCC 1979', ...] from the free-text Awards field."""
    found = []
    for name, year in AWARD_RE.findall(text):
        found.append(name + (" " + year if year else ""))
    return _unique(found)


def _number(text):
    """'2.5' -> 2.5, '1 1/2' -> 1.5, '3/4' -> 0.75."""
    total = 0.0
    for part in text.split():
        numerator, _, denominator = part.partition("/")
        total += float(numerator) / float(denominator) if denominator else float(numerator)
    return total


def _height_bounds(match):
    """(min_cm, max_cm) of one height measurement.

    Only a printed range gives a minimum ("6–15 m", "Tree to 20–30 m"); a single value is
    the size the plant reaches ("to 60 m", "to 10(–18) m" with an exceptional maximum).
    """
    numbers = [match.group(key) for key in ("low", "a", "b", "high") if match.group(key)]
    values = [round(_number(number) * CM_PER_UNIT[match.group("unit")]) for number in numbers]
    if match.group("b") is None and match.group("low") is None:
        return None, max(values)
    return min(values), max(values)


def height_range_cm(text):
    """(min_cm, max_cm) of the plant height stated in the first clause of a botanical description.

    Only measurements after a habit word count, and not those followed by 'long', 'wide',
    'dbh', 'girth' ... or preceded by '×' (the width in "35 m × 2 m"). Several heights in the
    clause ("10 to 15 ft high in gardens, ... a tree 30 to 40 ft high in China") are combined.
    """
    clause = FIRST_CLAUSE_RE.match(text).group(1)
    habit = HABIT_RE.search(clause)
    if not habit:
        return None, None
    lows, highs = [], []
    for match in HEIGHT_RE.finditer(clause, habit.end()):
        before = clause[:match.start("a")]
        if before.rstrip(" <>~").endswith("×") or NOT_HEIGHT_BEFORE_RE.search(before):
            continue
        low, high = _height_bounds(match)
        lows += [low] if low is not None else []
        highs += [high] if high is not None else []
    return (min(lows) if lows else None), (max(highs) if highs else None)


def extract_plant(page_html):
    """One plant record, or None for a page that is not a TSO article. Missing values are None / []."""
    page_html = GLOSSARY_RE.sub("", SCRIPT_RE.sub("", page_html))
    h1 = H1_RE.search(page_html)
    main = MAIN_COLUMN_RE.search(page_html)
    family_items = _sidebar_items("Family", page_html)
    if not (h1 and main and family_items):
        return None

    attributes = {}
    family = clean_text(family_items[0])
    genus_items = _sidebar_items("Genus", page_html)
    genus = clean_text(genus_items[0]) if genus_items else None
    synonym_items = _sidebar_items("Synonyms", page_html)
    for label, items in (("Family", family_items), ("Genus", genus_items),
                         ("Common Names", _sidebar_items("Common Names", page_html)), ("Synonyms", synonym_items)):
        if items:
            attributes[label] = _unique(clean_text(item) for item in items)

    scientific_name, authority = parse_heading(h1.group(1), genus)
    canonical = CANONICAL_RE.search(page_html)
    credits = CREDITS_RE.search(page_html)
    if credits and clean_text(credits.group(1)):
        attributes["Credits"] = [clean_text(credits.group(1))]

    # Main column: header (labelled fields + botanical description) and the article prose.
    main_html = CAPTION_RE.sub(" ", main.group(1))
    split = MAIN_TEXT_RE.search(main_html)
    header_html, body_html = (main_html[:split.start()], main_html[split.end():]) if split else ("", main_html)
    fields, header_prose = header_fields(header_html)
    typed = {}
    for label, value_html in fields:
        value = distribution_text(value_html) if label == "Distribution" else clean_text(value_html)
        # Inline labels end their value with a sentence full stop ("<b>USDA Hardiness Zone</b> 7.").
        value = re.sub(r"(?<!\.)\.$", "", value).strip()
        if value:
            attributes.setdefault(label, [])
            if value not in attributes[label]:
                attributes[label].append(value)
            typed.setdefault(label, value)

    description = WHITESPACE_RE.sub(" ", clean_text(header_prose) + " " + clean_text(body_html)).strip()
    zone_text = typed.get("USDA Hardiness Zone")
    zone_min, zone_max = zone_range(zone_text or "")
    rhs = typed.get("RHS Hardiness Rating") or typed.get("RHS Hardiness") or ""
    conservation_status, conservation_code = conservation(typed.get("Conservation status", ""))
    # The botanical description opens the header (revised articles) or the prose (Bean's texts).
    # Some empty headers hold only a placeholder dash.
    botanical = clean_text(EDITORIAL_NOTE_RE.sub(" ", header_prose))
    if not re.search(r"[A-Za-z]{3}", botanical):
        botanical = clean_text(body_html)
    height_min_cm, height_max_cm = height_range_cm(botanical)

    return {
        "scientific_name": scientific_name,
        "authority": authority,
        "family": family or None,
        "genus": genus or None,
        "common_names": list(attributes.get("Common Names", [])),
        "synonyms": synonym_names(synonym_items, genus, scientific_name),
        "zone_min": zone_min,
        "zone_max": zone_max,
        "height_min_cm": height_min_cm,
        "height_max_cm": height_max_cm,
        "description": description,
        "attributes": attributes,
        "article_type": article_type(scientific_name, h1.group(1), canonical.group(1) if canonical else ""),
        "rhs_hardiness": rhs if RHS_RE.match(rhs) else None,
        "conservation_status": conservation_status,
        "conservation_code": conservation_code,
        "distribution": typed.get("Distribution"),
        "habitat": typed.get("Habitat"),
        "awards": awards(typed.get("Awards", "")),
        "zone_text": zone_text,
    }
