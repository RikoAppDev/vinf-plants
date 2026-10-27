"""Regex entity extraction for wood-database.com wood species pages.

Every profile field starts a paragraph with a bold visible label ("Janka Hardness:"),
so the article text is cut into lines and each value runs from its label to the next
known label; nothing depends on the position of an element in the DOM. Numbers are
printed in imperial units with the metric value in brackets ("42 lbs/ft3 (675 kg/m3)");
the typed fields keep the metric number, the raw string stays in "attributes".
"""

import html
import re

# Structural anchor: the WordPress article body. It leaves out the site header,
# the sidebar and the visitor comment thread below the article, whose text may
# repeat the labels ("what is its Janka Hardness: ...").
BODY_RE = re.compile(r'<div class="entry-content[^"]*"[^>]*>(.*?)<!--\s*\.entry-content', re.DOTALL | re.IGNORECASE)

# Blocks without visible prose: ad/slider scripts, styles, lazy-load fallbacks
# and image figures (their captions only repeat the wood name).
HIDDEN_BLOCK_RE = re.compile(r"<(script|style|noscript|figure)\b.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
# Hover tooltips are hidden text, not part of a value: the help text of the data
# labels in the newest layout ("WEIGHT TIERS Extremely Low: 0+ kg/m3 ...") and the
# citation previews in the prose with their "[1]" markers. A tooltip may hold one
# nested <span>.
TOOLTIP_RE = re.compile(
    r'<span\b[^>]*class="(?:tooltip-content|footnote_tooltip)"[^>]*>(?:<span\b[^>]*>.*?</span>|(?!</span>).)*?</span>'
    r'|<sup\b[^>]*class="footnote_plugin_tooltip_text"[^>]*>.*?</sup>',
    re.DOTALL | re.IGNORECASE,
)
# Paragraph-level tags end a line; <br> only wraps a line, so it becomes a space.
BLOCK_TAG_RE = re.compile(
    r"</?(?:p|div|td|th|tr|table|tbody|thead|li|ul|ol|blockquote|h[1-6]|section|article|figcaption)\b[^>]*>",
    re.IGNORECASE,
)
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
# Inline tags are removed without a space: "lb<sub>f</sub>" -> "lbf", "kg/m<sup>3</sup>" -> "kg/m3".
TAG_RE = re.compile(r"<[^>]+>")
SPACES_RE = re.compile(r"[ \t\r\f\v\u00a0\u2009\u200b]+")  # incl. no-break, thin and zero-width spaces

# "English Oak | The Wood Database (Hardwood)"
TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.DOTALL | re.IGNORECASE)
TITLE_PARTS_RE = re.compile(r"^(?P<name>.*?)\s*\|\s*The Wood Database(?:\s*\((?P<type>[^)]+)\))?\s*$")

# Fields of the data table at the top of a profile.
DATA_LABELS = (
    "Common Name(s)", "Scientific Name", "Botanical Designation", "Distribution", "Tree Size",
    "Average Dried Weight", "Specific Gravity (Basic, 12% MC)", "Janka Hardness",
    "Modulus of Rupture", "Elastic Modulus", "Crushing Strength", "Shrinkage", "Board-foot weight",
    "IUCN Status", "CITES Status",
)
# Prose sections below the table.
PROSE_LABELS = (
    "Color/Appearance", "Grain/Texture", "Endgrain", "Rot Resistance", "Workability", "Odor",
    "Allergies/Toxicity", "Pricing/Availability", "Sustainability", "Common Uses", "Comments",
    "Note", "Notes", "Identification", "Porosity", "Arrangement", "Vessels", "Parenchyma", "Rays",
    "Resin canals", "Tracheid diameter", "Earlywood to latewood transition", "Grain contrast",
    "Lookalikes/Substitutes",
)
# Labels of the media / navigation part of the page: they only end the
# previous value and are not kept.
END_LABELS = ("Related Species", "Related Articles", "Related Content", "Scans/Pictures", "Images")

# Short endgrain anatomy fields of the newer layout ("Parenchyma: none
# visible"); in the description they keep their label to stay readable.
ANATOMY_LABELS = (
    "Porosity", "Arrangement", "Vessels", "Parenchyma", "Rays", "Resin canals", "Tracheid diameter",
    "Earlywood to latewood transition", "Grain contrast",
)
# Prose that makes up the description, in this order after "Comments". Left
# out: "Note" (the "truncated profile page" notice) and "Identification" (a
# pointer to the anatomy article).
DESCRIPTION_LABELS = (
    "Color/Appearance", "Grain/Texture", "Endgrain", "Porosity", "Arrangement", "Vessels",
    "Parenchyma", "Rays", "Resin canals", "Tracheid diameter", "Earlywood to latewood transition",
    "Grain contrast", "Rot Resistance", "Workability", "Odor", "Allergies/Toxicity",
    "Pricing/Availability", "Sustainability", "Common Uses", "Notes", "Lookalikes/Substitutes",
)

_ALL_LABELS = DATA_LABELS + PROSE_LABELS + END_LABELS
# Canonical spelling, so "Resin Canals :" and "Resin canals:" share one key.
_CANONICAL = {label.lower(): label for label in _ALL_LABELS}
# A known label at the start of a line: "Janka Hardness:", "Resin canals :".
LABEL_RE = re.compile(
    r"^[ \t]*(" + "|".join(re.escape(label) for label in sorted(_ALL_LABELS, key=len, reverse=True))
    + r")[ \t]*:[ \t]*",
    re.MULTILINE | re.IGNORECASE,
)
# Taxonomy breadcrumb of the newer layout: "> Hardwoods > Fabaceae > Acacia > catenulata".
# A second copy heads the related species list, so it also ends a value.
BREADCRUMB_RE = re.compile(r"^[ \t]*>[ \t]*(Hardwoods|Softwoods|Monocots?)[ \t]*>(.*)$", re.MULTILINE | re.IGNORECASE)
# Taxonomy box of the newest layout, one rank per line:
# "Rosaceae (Family)", "Prunus (Genus)", "serotina (Species)", "Ehrh. (Authority)".
TAXON_LINE_RE = re.compile(r"^[ \t]*(.+?)[ \t]*\((Wood Type|Family|Genus|Species|Authority)\)[ \t]*$", re.MULTILINE)
# Link texts that sit between the data table and the prose ("More images | Identification").
FURNITURE_LINE_RE = re.compile(r"^(?:More images|Identification)(?:\s*\|\s*(?:More images|Identification))*$", re.IGNORECASE)
# Footnotes below the data table: "*Estimated hardness based on specific gravity",
# on their own line or after a <br> in the same paragraph ("T/R Ratio: ~1.6* *Shrinkage values are ...").
FOOTNOTE_LINE_RE = re.compile(r"^[*†]")
INLINE_FOOTNOTE_RE = re.compile(r"\s+(?=\*+[A-Za-z])")

# "1,120", "97.1", ".6"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
# Metric part of a measurement: "(675 kg/m3)", "(4,980 N)", "( 11.42 GPa)". A
# range ("485 to 610 kg/m3") is captured too, so that it can be rejected.
METRIC_RE = {
    unit: re.compile(r"\(\s*(" + NUMBER + r")\s*(?:(?:-|–|to)\s*(" + NUMBER + r")\s*)?" + re.escape(unit) + r"\s*\)")
    for unit in ("kg/m3", "N", "MPa", "GPa")
}
# Tree size: "100-130 ft (30-40 m) tall, 3-5 ft (1-1.5 m) trunk diameter".
SIZE_METRIC = r"\(\s*(" + NUMBER + r")(?:\s*[-–]\s*(" + NUMBER + r"))?\s*(cm|m)\s*\)"
HEIGHT_RE = re.compile(SIZE_METRIC + r"\s*\*?\s*tall")
TRUNK_RE = re.compile(SIZE_METRIC + r"\s*\*?\s*(?:trunk\s+)?diameter")
# "Radial: 4.7%, Tangential: 8.4%, Volumetric: 13.0%, T/R Ratio: 1.8" ("~9%" = approximate).
SHRINKAGE_RE = {
    field: re.compile(label + r"\s*:\s*~?(" + NUMBER + r")", re.IGNORECASE)
    for field, label in (("shrinkage_radial_pct", "Radial"), ("shrinkage_tangential_pct", "Tangential"),
                         ("shrinkage_volumetric_pct", "Volumetric"), ("shrinkage_tr_ratio", r"T/R Ratio"))
}

# Comma or semicolon that is not inside parentheses:
# "Tambootie (variously spelled as: Tambuti, Tambotie, etc.), Sandalo".
LIST_SEPARATOR_RE = re.compile(r"[,;]\s*(?![^()]*\))")
LEADING_AND_RE = re.compile(r"^(?:and|or)\s+", re.IGNORECASE)
# "Common Uses" written as sentences ("... is used for heavy construction, such
# as: bridges, beams, ... It's also used for ...") is not a plain list.
PROSE_LIST_RE = re.compile(r"[.:;]\s+\S")
NONE_VALUE_RE = re.compile(r"^(?:none|n/a)\.?$", re.IGNORECASE)

# One Latin name: a full or abbreviated genus ("Quercus", "Q."), then an epithet
# or "spp.", optionally a hybrid sign ("Juglans x paradox", "Swietenia
# macrophylla × mahogani") and an infraspecific rank ("Zelkova serrata var. tarokoensis").
NAME_RE = re.compile(
    r"\b(?P<genus>[A-Z][a-z]+(?=\s)|[A-Z]\.)\s*"
    r"(?P<rest>(?:[x×]\s+)?[a-z][a-z-]+\.?"
    r"(?:\s+(?:var|subsp|ssp)\.\s+[a-z][a-z-]+)?"
    r"(?:\s+[x×]\s+[a-z][a-z-]+)?)"
)
# A capitalised word directly before "genus"/"genera"/"spp.": also a genus,
# used to expand later abbreviations ("Millettia genus under older synonyms M. leucantha").
GENUS_MENTION_RE = re.compile(r"\b([A-Z][a-z]+)\s+(?:genus|genera|spp\.?)(?![a-z])")
# English words that can follow a capitalised word in this field ("Hundreds of
# species", "Dutch Elm is a ...", "Handroanthus species"); never an epithet.
NOT_EPITHET = {
    "and", "or", "of", "the", "is", "are", "was", "as", "in", "from", "among", "with", "by", "also",
    "genus", "genera", "species", "family", "hybrid", "var", "subsp", "ssp", "under", "see",
}
# Parts of the Scientific Name line: the text in and around parentheses and between ";".
CLAUSE_SPLIT_RE = re.compile(r"[();]")
# Clause words that turn a name into a synonym: "(syn. Cedrela toona)", "(= C. glaucophylla)",
# "older synonym Tabebuia ochracea".
SYNONYM_CUE_RE = re.compile(
    r"\bsyn\.|\bsynonyms?\b|=|\bformerly\b|\bpreviously\b|\bolder\b|\bobsolete\b|\bwritten as\b"
    r"|\bspelled\b|\btreat(?:ed)?\b|\blisted (?:as|under)\b",
    re.IGNORECASE,
)
# "(commonly mislabeled as Swartzia arborescens)": a different wood, not a synonym.
MISLABEL_CUE_RE = re.compile(r"\bmislabell?ed\b", re.IGNORECASE)
# "(hybrid of Tilia platyphyllos and T. cordata)", "(J. hindsii x J. regia)": parents of a hybrid.
HYBRID_CUE_RE = re.compile(r"\bhybrid\b|\b[a-z][a-z-]+\s+[x×]\s+[A-Z]", re.IGNORECASE)

# Sentence boundary that is not an abbreviated genus ("A. anthotheca"), "spp." or "syn.".
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?<!\b[A-Z]\.)(?<!\bspp\.)(?<!\bsyn\.)\s+(?=[A-Z(])")
IUCN_CATEGORY = (r"(critically endangered|endangered|vulnerable|near threatened|least concern|data deficient"
                 r"|conservation dependent|extinct in the wild|lower risk)")
# A category the IUCN actually assigned, stated in one sentence, one example per alternative:
#   "reported by the IUCN as being a species of least concern"
#   "listed as being of least concern by the IUCN"
#   "the IUCN reports that Schinopsis balansae is a species of least concern"
#   "is also listed on the IUCN Red List as vulnerable"
IUCN_POSITIVE_RE = re.compile(
    r"\b(?:reported|assessed|rated|listed|evaluated|classified)\s+by\s+(?:the\s+)?IUCN\s+as\s+(?:being\s+)?"
    r"(?:an?\s+)?(?:species\s+of\s+|of\s+)?" + IUCN_CATEGORY
    + r"|\b(?:listed|rated|reported|assessed)\s+as\s+(?:being\s+)?(?:an?\s+)?(?:species\s+of\s+|of\s+)?"
    + IUCN_CATEGORY + r"\s+by\s+(?:the\s+)?IUCN"
    + r"|\bIUCN\s+reports\s+that\b.*?\b(?:is|are)\s+(?:an?\s+)?(?:species\s+of\s+)?" + IUCN_CATEGORY
    + r"|\bon\s+the\s+(?:IUCN\s+)?Red\s+List\s+(?:of\s+Threatened\s+Species\s+)?as\s+" + IUCN_CATEGORY,
    re.IGNORECASE,
)
# "but is on the IUCN Red List. It is listed as vulnerable due to ...": the
# category follows the Red List statement, in the same or the next sentence.
IUCN_RED_LIST_RE = re.compile(r"\b(?:is|are)\s+(?:also\s+)?(?:listed\s+)?on\s+the\s+IUCN\s+Red\s+List\b", re.IGNORECASE)
IUCN_LISTED_AS_RE = re.compile(r"\blisted\s+as\s+(?:being\s+)?(?:an?\s+)?(?:species\s+of\s+)?" + IUCN_CATEGORY, re.IGNORECASE)
# Negative statements; a category word after them ("However, it is listed as
# vulnerable under Australia's EPBC Act") is not an IUCN category.
IUCN_NEGATIVE_RE = re.compile(
    r"\bor\s+on\s+the\s+IUCN\s+Red\s+List"
    r"|\bnot\s+(?:currently\s+|yet\s+)?(?:been\s+)?(?:evaluated\s+|included\s+|listed\s+)?(?:by|on|in)\s+(?:the\s+)?(?:IUCN|Red\s+List)"
    r"|\bunevaluated\s+status\s+by\s+the\s+IUCN"
    r"|\bnot\s+qualify\s+to\s+be\s+evaluated\s+by\s+the\s+IUCN",
    re.IGNORECASE,
)
# "listed in CITES Appendix II", "is in CITES Appendix I", "is CITES-listed in Appendix II".
CITES_POSITIVE_RE = re.compile(r"\bCITES\b.*?\bAppendix\s+(III|II|I)\b", re.IGNORECASE)
# "not listed in the CITES Appendices".
CITES_NEGATIVE_RE = re.compile(r"\bnot\s+(?:listed\s+)?(?:in|on)\s+(?:the\s+)?CITES\b|\bnot\s+CITES-listed\b", re.IGNORECASE)
# Values of the "IUCN Status:" / "CITES Status:" fields of the newest layout:
# "Least Concern", "Appendix II", "Unlisted".
IUCN_STATUS_RE = re.compile(IUCN_CATEGORY, re.IGNORECASE)
CITES_STATUS_RE = re.compile(r"\bAppendix\s+(III|II|I)\b", re.IGNORECASE)
CITES_UNLISTED_RE = re.compile(r"\bunlisted\b|\bnot\s+listed\b", re.IGNORECASE)


def clean_text(fragment):
    """Strip tags, decode entities and collapse whitespace."""
    return SPACES_RE.sub(" ", html.unescape(TAG_RE.sub("", BR_RE.sub(" ", fragment)))).strip()


def article_lines(page_html):
    """Visible text of the article body, one paragraph per line, or None."""
    body = BODY_RE.search(page_html)
    if not body:
        return None
    fragment = TOOLTIP_RE.sub(" ", HIDDEN_BLOCK_RE.sub(" ", body.group(1)))
    fragment = BLOCK_TAG_RE.sub("\n", BR_RE.sub(" ", fragment))
    text = html.unescape(TAG_RE.sub("", fragment))
    lines = (SPACES_RE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def split_fields(text):
    """{canonical label: [value, footnote, ...]} for every known label in the article text.

    A value runs to the next label, breadcrumb or taxonomy box. Data fields may
    wrap over several paragraphs ("tall," / "3-5 ft (1-1.5 m) trunk diameter");
    their footnotes ("*Estimated hardness ...") are kept as extra values.
    Only the first occurrence of a label counts.
    """
    stops = [(m.start(), m.end(), _CANONICAL[m.group(1).lower()]) for m in LABEL_RE.finditer(text)]
    stops += [(m.start(), m.start(), None) for m in BREADCRUMB_RE.finditer(text)]
    stops += [(m.start(), m.start(), None) for m in TAXON_LINE_RE.finditer(text)]
    stops.sort(key=lambda stop: stop[0])
    fields = {}
    for index, (_, value_start, label) in enumerate(stops):
        if label is None or label in END_LABELS or label in fields:
            continue
        value_end = stops[index + 1][0] if index + 1 < len(stops) else len(text)
        lines = [line.strip() for line in text[value_start:value_end].split("\n")]
        if label in DATA_LABELS:
            main, notes = [], []
            for line in lines:
                if not line or FURNITURE_LINE_RE.match(line):
                    continue
                if FOOTNOTE_LINE_RE.match(line):
                    notes.append(line)
                    continue
                head, *footnote = INLINE_FOOTNOTE_RE.split(line, maxsplit=1)
                main.append(head)
                notes.extend(footnote)
            values = [" ".join(main)] + notes
        else:
            values = [" ".join(line for line in lines if line and line != ">")]
        values = [SPACES_RE.sub(" ", value).strip() for value in values]
        # Unfilled template fields print a literal "None." (Huanghuali "Comments: None.").
        values = [value for value in values if value and not NONE_VALUE_RE.match(value)]
        if values:
            fields[label] = values
    return fields


def taxonomy(text):
    """{rank: name} from the breadcrumb ("> Hardwoods > Fagaceae > Quercus > robur")
    or the taxonomy box ("Fagaceae (Family)", "L. (Authority)")."""
    ranks = {}
    for name, rank in TAXON_LINE_RE.findall(text):
        ranks.setdefault(rank, name.strip())
    crumb = BREADCRUMB_RE.search(text)
    if crumb:
        ranks.setdefault("Wood Type", crumb.group(1))
        parts = [part.strip() for part in crumb.group(2).split(">") if part.strip()]
        for rank, name in zip(("Family", "Genus", "Species"), parts):
            ranks.setdefault(rank, name)
    return ranks


def metric_value(value, unit):
    """The single metric number of a measurement ("42 lbs/ft3 (675 kg/m3)" -> 675.0);
    None if it is missing, a range or printed more than once."""
    matches = METRIC_RE[unit].findall(value or "")
    if len(matches) != 1 or matches[0][1]:
        return None
    return float(matches[0][0].replace(",", ""))


def _size_cm(match):
    if not match:
        return None, None
    low, high, unit = match.groups()
    factor = 100 if unit == "m" else 1
    low_cm = round(float(low) * factor)
    high_cm = round(float(high) * factor) if high else low_cm
    return low_cm, high_cm


def tree_size_cm(value):
    """(height_min, height_max, trunk_min, trunk_max) in cm from the metric part of "Tree Size"."""
    height = _size_cm(HEIGHT_RE.search(value or ""))
    trunk = _size_cm(TRUNK_RE.search(value or ""))
    return height + trunk


def split_list(value):
    """Comma separated list -> items, without "and"/"or" and the final full stop."""
    items = []
    for item in LIST_SEPARATOR_RE.split((value or "").strip().rstrip(".")):
        item = LEADING_AND_RE.sub("", item.strip()).strip()
        if item and item not in items:
            items.append(item)
    return items


def common_uses(value):
    """Items of a plain "Common Uses" list; a value written as sentences stays one item."""
    value = (value or "").strip()
    if not value:
        return []
    if PROSE_LIST_RE.search(value.rstrip(".")):
        return [value]
    return split_list(value)


def scientific_names(value):
    """(main name, accepted names, synonyms, hybrid parents) from the "Scientific Name:" line.

    The main name is the first Latin name before any parenthesis; other names are
    classified by the words of their clause (see the *_CUE_RE patterns).
    Abbreviated genera ("C. procera") are expanded from the last genus with the
    same initial; one that cannot be expanded is dropped rather than guessed.
    """
    value = value or ""
    genera = []
    main = None
    accepted, synonyms, parents = [], [], []
    for clause_index, clause in enumerate(CLAUSE_SPLIT_RE.split(value)):
        names = []
        events = [(m.start(), "genus", m.group(1)) for m in GENUS_MENTION_RE.finditer(clause)]
        events += [(m.start(), "name", m) for m in NAME_RE.finditer(clause)]
        for _, kind, item in sorted(events, key=lambda event: event[0]):
            if kind == "genus":
                genera.append(item)
                continue
            genus, rest = item.group("genus"), SPACES_RE.sub(" ", item.group("rest"))
            if rest.split()[-1].rstrip(".") in NOT_EPITHET or rest.split()[0] in NOT_EPITHET:
                continue
            if genus.endswith("."):
                genus = next((g for g in reversed(genera) if g[0] == genus[0]), None)
                if genus is None:
                    continue
            else:
                genera.append(genus)
            names.append((genus, rest, item.group("genus").endswith(".")))
        if clause_index == 0 and names and not names[0][2]:
            main = names[0][0] + " " + names[0][1]
            names = names[1:]
        if MISLABEL_CUE_RE.search(clause):
            continue
        is_synonym = bool(SYNONYM_CUE_RE.search(clause))
        is_hybrid = bool(HYBRID_CUE_RE.search(clause)) and not is_synonym
        main_genus = main.split()[0] if main else None
        for genus, rest, abbreviated in names:
            name = genus + " " + rest
            if name == main:
                continue
            # A full genus that differs from the main one and is not in a synonym
            # clause is more likely English prose ("European elm") than a name,
            # unless it is a genus-level entry ("Payena spp.").
            if not (abbreviated or genus == main_genus or is_synonym or rest == "spp."):
                continue
            target = synonyms if is_synonym else parents if is_hybrid else accepted
            if name not in target:
                target.append(name)
    return main, ([main] if main else []) + accepted, synonyms, parents


def _iucn_from_text(text):
    """IUCN category stated in the Sustainability text, or None.

    The first sentence that makes an IUCN statement decides: a negative one
    ("not listed in the CITES Appendices or on the IUCN Red List") gives None,
    so a later category word about another scheme or species is not taken.
    """
    sentences = SENTENCE_SPLIT_RE.split(text or "")
    for index, sentence in enumerate(sentences):
        found = []
        for match in IUCN_NEGATIVE_RE.finditer(sentence):
            found.append((match.start(), None))
        for match in IUCN_POSITIVE_RE.finditer(sentence):
            category = next(group for group in match.groups() if group)
            found.append((match.start(), category))
        for match in IUCN_RED_LIST_RE.finditer(sentence):
            # Ranked by where the category is printed, so that "are on the IUCN
            # Red List as endangered, while the third is listed as near
            # threatened" keeps the first category.
            after = IUCN_LISTED_AS_RE.search(sentence, match.end())
            if after:
                found.append((after.start(), after.group(1)))
            elif index + 1 < len(sentences):
                after = IUCN_LISTED_AS_RE.search(sentences[index + 1])
                if after:
                    found.append((len(sentence), after.group(1)))
        if found:
            category = min(found, key=lambda item: item[0])[1]
            return category.title() if category else None
    return None


def iucn_status(fields):
    """IUCN category from the "IUCN Status:" field or the Sustainability text."""
    status = " ".join(fields.get("IUCN Status", []))
    if status:
        match = IUCN_STATUS_RE.search(status)
        return match.group(1).title() if match else None
    return _iucn_from_text(" ".join(fields.get("Sustainability", [])))


def cites_status(fields):
    """(listed, appendix): (True, "Appendix II"), (False, None) or (None, None) if not stated."""
    status = " ".join(fields.get("CITES Status", []))
    if status:
        match = CITES_STATUS_RE.search(status)
        if match:
            return True, "Appendix " + match.group(1).upper()
        return (False, None) if CITES_UNLISTED_RE.search(status) else (None, None)
    for sentence in SENTENCE_SPLIT_RE.split(" ".join(fields.get("Sustainability", []))):
        negative = CITES_NEGATIVE_RE.search(sentence)
        positive = CITES_POSITIVE_RE.search(sentence)
        if negative and (not positive or negative.start() < positive.start()):
            return False, None
        if positive:
            return True, "Appendix " + positive.group(1).upper()
    return None, None


def _first(fields, label):
    values = fields.get(label)
    return values[0] if values else None


def extract_plant(page_html):
    """One wood species record, or None for pages that are not a species profile. Missing values stay None / empty."""
    text = article_lines(page_html)
    if text is None:
        return None
    fields = split_fields(text)
    # Figure, trade-name and article pages ("Birdseye maple") print no "Scientific Name:"
    # label, and some Scientific Name lines hold no Latin name ("Bamboo: Hundreds of species ...").
    if "Scientific Name" not in fields:
        return None
    main_name, names, synonyms, parents = scientific_names(_first(fields, "Scientific Name"))
    if main_name is None:
        return None

    title = TITLE_RE.search(page_html)
    title_parts = TITLE_PARTS_RE.match(clean_text(title.group(1))) if title else None
    ranks = taxonomy(text)
    wood_type = title_parts.group("type") if title_parts else None
    if not wood_type and ranks.get("Wood Type"):
        wood_type = ranks["Wood Type"].rstrip("s").capitalize()
    height_min, height_max, trunk_min, trunk_max = tree_size_cm(_first(fields, "Tree Size"))
    janka = metric_value(_first(fields, "Janka Hardness"), "N")
    shrinkage = _first(fields, "Shrinkage") or ""
    cites_listed, cites = cites_status(fields)

    description_parts = fields.get("Comments", [])[:1] + [
        (label + ": " if label in ANATOMY_LABELS else "") + fields[label][0]
        for label in DESCRIPTION_LABELS if label in fields
    ]

    record = {
        "scientific_name": main_name,
        "authority": ranks.get("Authority"),
        "family": ranks.get("Family"),
        "genus": main_name.split()[0],
        "common_names": split_list(_first(fields, "Common Name(s)")),
        "synonyms": synonyms,
        # The site has no hardiness zones; "USDA" only occurs in the Janka footnote.
        "zone_min": None,
        "zone_max": None,
        "height_min_cm": height_min,
        "height_max_cm": height_max,
        "description": " ".join(description_parts),
        "attributes": dict(fields),
        "wood_name": title_parts.group("name") if title_parts else None,
        "wood_type": wood_type,
        "scientific_names": names,
        "hybrid_parents": parents,
        "trunk_diameter_min_cm": trunk_min,
        "trunk_diameter_max_cm": trunk_max,
        "distribution": _first(fields, "Distribution"),
        "density_kg_m3": metric_value(_first(fields, "Average Dried Weight"), "kg/m3"),
        "specific_gravity": _first(fields, "Specific Gravity (Basic, 12% MC)"),
        "janka_hardness_n": int(janka) if janka is not None else None,
        "modulus_of_rupture_mpa": metric_value(_first(fields, "Modulus of Rupture"), "MPa"),
        "elastic_modulus_gpa": metric_value(_first(fields, "Elastic Modulus"), "GPa"),
        "crushing_strength_mpa": metric_value(_first(fields, "Crushing Strength"), "MPa"),
        "iucn_status": iucn_status(fields),
        "cites_listed": cites_listed,
        "cites": cites,
        "common_uses": common_uses(_first(fields, "Common Uses")),
    }
    for field, pattern in SHRINKAGE_RE.items():
        match = pattern.search(shrinkage)
        record[field] = float(match.group(1).replace(",", "")) if match else None
    return record
