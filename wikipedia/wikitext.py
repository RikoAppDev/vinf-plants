"""Regex parser of one page of the English Wikipedia XML dump (a <page> record without its closing tag).

The wikitext in the dump is XML-escaped ("&lt;ref&gt;") and is unescaped once; entities typed by
the editors are escaped twice ("&amp;nbsp;") and are decoded only by plain_text.
"""

import html
import re

PAGE_HEAD_RE = re.compile(
    r'<title>([^<]*)</title>\s*<ns>(-?\d+)</ns>\s*<id>(\d+)</id>\s*(?:<redirect title="([^"]*)"\s*/>)?')
# "<" is always escaped inside the element, so the text runs up to the first "<".
TEXT_RE = re.compile(r"<text\b[^>]*>([^<]*)</text>")

# The lookahead keeps out "{{Taxobox colour|...}}"; the cheap path runs it on escaped text ("&lt;!--").
BOX_RE = re.compile(
    r"\{\{\s*((?:automatic[ _]*)?taxo[ _]*box|(?:sub|infra)?[ _]*species[ _]*box|hybrid[ _]*box)"
    r"\s*(?=\||\}\}|<!--|&lt;!--)", re.IGNORECASE)
BOX_NAMES = {"speciesbox": "speciesbox", "automatictaxobox": "automatic taxobox", "taxobox": "taxobox",
             "subspeciesbox": "subspeciesbox", "infraspeciesbox": "infraspeciesbox", "hybridbox": "hybridbox"}

BRACES_RE = re.compile(r"\{\{|\}\}")
PARAM_TOKEN_RE = re.compile(r"\{\{|\}\}|\[\[|\]\]|\|")
PARAM_NAME_RE = re.compile(r"^\s*([\w -]+?)\s*=(.*)$", re.DOTALL)
TEMPLATE_NAME_RE = re.compile(r"^\{\{\s*([^|{}]*?)\s*(?:\||\}\}$)")
# Innermost templates first, so nesting needs no counting when templates are dropped.
INNER_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
# Words a template stands for: a positional parameter ("{{lang|la|amygdalus}}" -> "amygdalus") or a string.
INLINE_TEMPLATES = {"lang": 2, "langx": 2, "wikt-lang": 2, "transliteration": 2, "translit": 2, "small": 1,
                    "nowrap": 1, "nobr": 1, "noitalic": 1, "ndash": " – ", "snd": " – ", "spacedndash": " – ",
                    "mdash": "—", "nbsp": " ", "!": "|"}
# "grows to {{convert|2|m|ft}} tall" keeps "2 m", the value as typed, without the conversion.
CONVERT_TEMPLATES = {"convert", "cvt"}
NUMBER_RE = re.compile(r"^[-+−]?\d[\d,.]*(?:/\d+)?(?:\+\d+/\d+)?(?:[-–]\d[\d,.]*)?$")
CONVERT_RANGES = {"-": "–", "–": "–", "to": " to ", "to(-)": " to ", "and": " and ", "and(-)": " and ",
                  "or": " or ", "x": " × ", "by": " × ", "×": " × ", "+/-": " ± "}
CONVERT_UNITS = {"C": "°C", "F": "°F", "m2": "m²", "cm2": "cm²", "km2": "km²", "sqmi": "sq mi", "sqft": "sq ft"}
CONVERT_PREFIXES = {"e3": "thousand ", "e6": "million ", "e9": "billion "}

# An unclosed comment hides the rest of the page.
COMMENT_RE = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
# Self-closing form first, so "<ref name=eb/>" does not open a ref up to the next "</ref>".
REF_RE = re.compile(r"<ref\b[^>]*/\s*>|<ref\b[^>]*>.*?</ref\s*>", re.DOTALL | re.IGNORECASE)
DROPPED_ELEMENT_RE = re.compile(r"<(gallery|imagemap|math|timeline|score)\b[^>]*>.*?</\1\s*>",
                                re.DOTALL | re.IGNORECASE)
# Not wikitext: the JSON of a <mapframe> in `range_map` can hold "}}" and close the box early.
NON_WIKITEXT_TAGS = "mapframe|maplink|syntaxhighlight|source|math|chem|ce|score|graph|timeline|hiero|templatedata"
NON_WIKITEXT_ELEMENT_RE = re.compile(
    r"<(?:{0})\b[^>]*/\s*>|<({0})\b[^>]*>.*?</\1\s*>".format(NON_WIKITEXT_TAGS), re.DOTALL | re.IGNORECASE)
# A file caption may hold links, so plain links go first and the file link is flat afterwards.
LINK_RE = re.compile(r"\[\[(?!\s*(?:File|Image|Category)\s*:)\s*:?([^\[\]|]*)(?:\|([^\[\]]*))?\]\]", re.IGNORECASE)
FILE_LINK_RE = re.compile(r"\[\[\s*(?:File|Image|Category)\s*:(?:[^\[\]]|\[[^\[\]]*\])*\]\]", re.IGNORECASE)
EXTERNAL_LINK_RE = re.compile(r"\[(?:https?:|ftp:)?//[^\s\]]*\s*([^\]]*)\]")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
QUOTES_RE = re.compile(r"'{2,}")
MAGIC_WORD_RE = re.compile(r"__[A-Z]+__")
WHITESPACE_RE = re.compile(r"\s+")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?)])")
SPACE_AFTER_BRACKET_RE = re.compile(r"\(\s+")
# What is left of "(" {{IPAc-en|...}} ")" once the template is gone.
EMPTY_BRACKETS_RE = re.compile(r"\s*\(\s*[,;]?\s*\)")

# "; Species" before a species list is a heading in all but markup, so it ends the lead too.
HEADING_RE = re.compile(r"^(?:=.*=|;.*)\s*$", re.MULTILINE)
# Lists, indented lines and tables in the lead are species lists and notes, not prose.
LIST_LINE_RE = re.compile(r"^[*#:].*\n?", re.MULTILINE)
TABLE_RE = re.compile(r"^[ \t:]*\{\|.*?^[ \t]*\|\}[^\n]*\n?", re.DOTALL | re.MULTILINE)
LETTER_RE = re.compile(r"[^\W\d_]")
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
QUOTE_RUN_RE = re.compile(r"'{2,}")
CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\[\]|]+?)\s*(?:\|[^\[\]]*)?\]\]", re.IGNORECASE)
DESCRIBED_IN_RE = re.compile(r"\bdescribed in (\d{4})$")
# "L. 1753 not Scop. 1777": the year after "not" belongs to another name.
OTHER_NAME_RE = re.compile(r"\s(?:not|non|nec|nor)\s.*$")
YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
# After "(L.) Spreng." the year dates the new combination; in "(Linnaeus, 1758)" it is the description.
BASIONYM_AUTHOR_RE = re.compile(r"^\s*\(([^()]*)\)")

IUCN_STATUSES = {"LC", "NT", "VU", "EN", "CR", "EW", "EX", "DD"}
# IUCN 2.3 "lower risk" classes; version 3.1 moved them to Least Concern / Near Threatened.
IUCN_OLD_STATUSES = {"LR/LC": "LC", "LR/NT": "NT", "LR/CD": "NT"}

# Not the general "Taxa named by ...": it is on animal pages too (Giant panda).
PLANT_CATEGORY_PREFIXES = ("Flora of", "Plants described in", "Trees of", "Garden plants", "Endemic flora of",
                           "Botanical taxa named by", "Crops", "Ornamental")
# Plant families end in -aceae / -oideae, animal ones in -idae / -inae ("Nymphalidae").
PLANT_FAMILY_CATEGORY_RE = re.compile(r"\b[A-Z][a-z]+(?:aceae|oideae)\b")
# Only land plant orders: fungi, lichens and algae have -ales orders too ("Agaricales genera").
PLANT_ORDERS = frozenset("""
    Amborellales Nymphaeales Austrobaileyales Chloranthales Canellales Piperales Magnoliales Laurales Acorales
    Alismatales Petrosaviales Dioscoreales Pandanales Liliales Asparagales Arecales Commelinales Zingiberales Poales
    Ceratophyllales Ranunculales Proteales Trochodendrales Buxales Gunnerales Dilleniales Saxifragales Vitales
    Zygophyllales Fabales Rosales Fagales Cucurbitales Celastrales Oxalidales Malpighiales Geraniales Myrtales
    Crossosomatales Picramniales Huerteales Sapindales Malvales Brassicales Berberidopsidales Santalales
    Caryophyllales Cornales Ericales Icacinales Metteniusales Garryales Gentianales Boraginales Vahliales Solanales
    Lamiales Aquifoliales Asterales Escalloniales Bruniales Paracryphiales Dipsacales Apiales
    Cycadales Ginkgoales Pinales Araucariales Cupressales Gnetales Welwitschiales Ephedrales
    Equisetales Ophioglossales Psilotales Marattiales Osmundales Hymenophyllales Gleicheniales Schizaeales
    Salviniales Cyatheales Polypodiales Lycopodiales Isoetales Selaginellales
    Marchantiales Jungermanniales Porellales Metzgeriales Pelliales Fossombroniales Pallaviciniales Ptilidiales
    Lunulariales Sphaerocarpales Blasiales Haplomitriales Treubiales Sphagnales Andreaeales Polytrichales
    Tetraphidales Buxbaumiales Funariales Grimmiales Dicranales Pottiales Orthotrichales Splachnales Bryales
    Rhizogoniales Hookeriales Hypnales Hedwigiales Bartramiales Anthocerotales Notothyladales Dendrocerotales
    """.split())
# Not "Lichen genera": lichens are fungi.
PLANT_GROUP_GENERA = frozenset(group + " genera" for group in (
    "Plant", "Flowering plant", "Angiosperm", "Monocot", "Eudicot", "Magnoliid", "Gymnosperm", "Conifer", "Cycad",
    "Fern", "Lycophyte", "Moss", "Liverwort", "Hornwort", "Bryophyte"))
# Old taxoboxes link the kingdom as "regnum = [[Plant]]ae".
PLANTAE_RE = re.compile(r"\bPlantae\b|\[\[Plant\]\]ae")
# Genus pages often lack a plant category, but the short description says "Genus of flowering plants".
SHORT_DESCRIPTION_RE = re.compile(r"\{\{\s*short[ _]description\s*\|\s*([^|{}]*)", re.IGNORECASE)
PLANT_WORDS_RE = re.compile(
    r"\b(?:plants?|flowering|angiosperms?|gymnosperms?|trees?|shrubs?|conifers?|coniferous|ferns?|grass(?:es)?"
    r"|herbs?|herbaceous|vines?|palms?|cact(?:us|i)|orchids?|succulents?|legumes?|cereals?|grains?|wheat|fruits?"
    r"|nuts?|vegetables?|yams?)\b", re.IGNORECASE)
# "Family of fruit bats", "Fungus disease of chestnut trees"
NOT_PLANT_WORDS_RE = re.compile(r"\b(?:animals?|bats?|fung(?:us|i)|insects?|birds?|fish(?:es)?|mammals?|moths?)\b",
                                re.IGNORECASE)

# Rank endings above genus; -ae also covers the old family names ("Compositae").
HIGHER_TAXON_RE = re.compile(r"^[A-Z][a-z]+(?:ae|ales|opsida|phyta|phytina|mycota|mycetes|oidea|ini)$")
# "Quercus subg. Cerris", "Prunus sect. Armeniaca": groups between genus and species.
INFRAGENERIC_MARKER = r"(?:subg|subgen|sect|subsect|ser|subser)\."
INFRAGENERIC_RE = re.compile(r"^\S+ " + INFRAGENERIC_MARKER + " ")
SUBDIVISION_HIGHER_RE = re.compile(r"\b(?:genera|tribes|subtribes|subfamilies|families|orders|classes|phyla"
                                   r"|divisions)\b", re.IGNORECASE)
SUBDIVISION_GENUS_RE = re.compile(r"\b(?:species|subgenera|sections)\b", re.IGNORECASE)
LEAD_RANK_RE = re.compile(r"\b(genus|genera|family|subfamily|tribe|order|class|phylum|division|clade)\b",
                          re.IGNORECASE)
# "is a small genus", not "is a family of 12 genera"; "the genus Rosa" names another genus.
LEAD_GENUS_RE = re.compile(
    r"\b(?:(?:is|are|was|were)\s+(?:a|an|the|one\s+of)|as\s+an?)\s+"
    r"(?:(?!(?:of|in|with|within|from|containing|comprising|family|subfamily|tribe|subtribe|order|class|clade"
    r"|section)\b)[\w-]+\s+){0,3}?(?:genus|genera)\b(?!\s+[A-Z])")
# "The genus is endemic to Australia"; weaker, so a name ending or type_genus wins over it.
THIS_GENUS_RE = re.compile(r"\b(?:[Tt]his|[Tt]he)\s+genus\b(?!\s+[A-Z])")
LEAD_GENUS_WINDOW = 500
# "Pelargonium sp. Striatellum", "Prunus 'Kanzan'": pages that show the box of their genus.
INFORMAL_NAME_RE = re.compile(r"\s(?:sp|spp|aff|cf)\.(?:\s|$)|(?:^|\s)['‘\"“][A-Z][^'’\"”]*['’\"”](?:\s|$)")
# "Cladrastis clade", "Aloe group": informal groups, not species.
INFORMAL_GROUP_RE = re.compile(r"\s(?:clade|group|complex|alliance)$", re.IGNORECASE)
# Ranks of the old Taxobox below genus; a box that fills one is about a group inside the genus.
BELOW_GENUS_PARAMS = ("subgenus", "sectio", "subsectio", "series", "species", "binomial", "trinomial")
# "Quercus X bimundorum", "Quercus x bimundorum": a letter x on its own is the hybrid sign.
HYBRID_SIGN_RE = re.compile(r"(?:^|(?<=\s))[xX](?=\s)")
# Taxonomy template names carry a qualifier: "Dryas (plant)", "Tracheophytes/Plantae".
DISAMBIGUATOR_RE = re.compile(r"\s*(?:\([^()]*\)|/\S*)$")
INFRA_PARAMS = (("subspecies", "subsp."), ("varietas", "var."), ("variety", "var."), ("forma", "f."))

# {{Species list|Name|Author|...}} has the names at odd positions; other lists put the author in <small>.
NAME_LIST_TEMPLATES = {"specieslist", "genuslist", "taxonlist"}
CONTAINER_TEMPLATES = {"collapsiblelist", "plainlist", "unbulletedlist", "ubl", "flatlist", "hlist", "bulletedlist",
                       "blist", "columns-list"}
AUTHOR_RE = re.compile(r"<small\b[^>]*>(.*?)</small\s*>|\{\{\s*(?:small|au)\s*\|([^{}]*)\}\}",
                       re.DOTALL | re.IGNORECASE)
# Marks around the author text; a copy with it blanked out keeps the positions for the name search.
AUTHOR_OPEN, AUTHOR_CLOSE = "\x01", "\x02"
AUTHOR_SPAN_RE = re.compile("\x01[^\x01\x02]*\x02")
ITEM_SPLIT_RE = re.compile(r"\n|<br\s*/?>", re.IGNORECASE)
# "''Platanus''&nbsp;×&nbsp;''hybrida''": a no-break space must not part the italic runs.
NBSP_RE = re.compile(r"&(?:amp;)?(?:nbsp|#160|#[xX][aA]0);|\xa0")
# '''Basionym''', '''Homotypic''': bold alone marks a heading; bold italics stay italic.
BOLD_RE = re.compile(r"(?<!')'''(?!')")
# "'''Synonyms of ''Gentiana acaulis'' subsp. ''acaulis'''''": a heading that names the accepted taxon.
SYNONYMS_OF_RE = re.compile(r"^\W*synonyms?\s+of\b", re.IGNORECASE)
RANK_MARKER = r"(?:subsp|ssp|var|subvar|convar|f|subf|forma|nothosubsp|nothovar)\."
ITALIC_NAME_RE = re.compile(r"''[^'\n]+''(?:\s*(?:×|" + RANK_MARKER + "|" + INFRAGENERIC_MARKER +
                            r")?\s*''[^'\n]+'')*")
# "''Nepenthes'' sp.", "''Acacia'' sp. Pilbara": an informal name, not the genus.
INFORMAL_REST_RE = re.compile(r"^\W*(?:sp|spp|aff|cf)\.(?:\s|$)")
# Notes that make an entry another plant's name: illegitimate, misapplied ("auct.", "sensu"),
# partial ("pro parte"). "not" only in lower case: "De Not." is the author De Notaris.
SYNONYM_FLAG_RE = re.compile(
    r"\b[Nn]om(?:\.|en)\s*(?:illeg|inval|nud|rej)|\b[Aa]uct\b|\b[Ss]ensu\b|\b[Nn]on\b|\bnot\b|\b[Nn]ec\b"
    r"|\bpro\s+parte\b|\bp\.\s*p\.|\bpro\s+syn\b|\b[Mm]isapplied\b|\billegitimate\b|\binvalid|\brejected\b")
# "''Salix fragilis'' Host, not ''Salix'' × ''fragilis'' L.": the name after "not" is the other one.
OTHER_NAME_FLAG_RE = re.compile(r"\b(?:[Nn]on|not|[Nn]ec)\s*$")
# Notes after the author: "nom. superfl.", "(basionym)", "– Madagascar", ", tentatively listed".
AUTHOR_NOTE_RE = re.compile(
    r"\s*[,;]?\s*(?:\b(?:nom|nomen|orth|comb|stat)\b\.?\s.*|\b(?:basionym|homotypic|heterotypic|synonym)\b.*"
    r"|\((?![A-Z])[^()]*\)|\[[^\[\]]*\]|\s[–—-]\s.*|,\s+(?!ex\b)[a-z].*)$")
LOWER_NOTE_RE = re.compile(r"\(\s*[a-z][a-z .]*\)")
AUTHOR_YEAR_RE = re.compile(r"[,;]?\s*(?:[\(\[]\s*(?:1[5-9]\d\d|20\d\d)\s*[\)\]]|\b(?:1[5-9]\d\d|20\d\d))\.?$")
# "(Linnaeus, 1758)" in a zoological synonym keeps the brackets around the author.
AUTHOR_INNER_YEAR_RE = re.compile(r",\s*(?:1[5-9]\d\d|20\d\d)\)$")
# Old spellings keep accents in epithets: "Musa silvéstris", "Quercus mühlenbergii".
LOWER = "a-zß-öø-ÿ"
# Lower-case words after a name that are no epithets: "de Vriese", "ex DC.", "and see text", "subg.".
EPITHET = (r"(?!(?:ex|non|nec|sensu|auct|nom|in|de|van|von|et|and|or|see|plus|synonyms?)\b)"
           r"[{0}][{0}-]+\b(?!\.)").format(LOWER)
NAME_RE = re.compile(
    r"^(?:× ?)?(?:[A-Z][{0}]+(?:-[{0}]+)?|[A-Z]\.)(?: {3} [A-Z][{0}-]+)?"
    r"(?: (?:× ?|x )?{1}(?: (?:{2} )?{1})*)?".format(LOWER, EPITHET, RANK_MARKER, INFRAGENERIC_MARKER))
# A name cell of {{Species list}} in the author place: "Satureja montana var. stenophylla".
BINOMIAL_CELL_RE = re.compile(r"^(?:× ?)?[A-Z][{0}]+(?:-[{0}]+)? (?:× ?)?{1}".format(LOWER, EPITHET))
# "Boiss.", "(L.) Mill.", "Poit. & Turpin": an author cell, not a name.
AUTHOR_CELL_RE = re.compile(r"\.$|[&(]")
SINGLE_WORD_RE = re.compile(r"^[A-Z][{0}-]+$".format(LOWER))
# Not common names: "subsp. saxosa", "Asimina speciosa"; the Latin ending keeps "Vanilla orchids".
COMMON_RANK_MARKER_RE = re.compile(r"(?:^|\s)(?:subsp|ssp|var|subvar|f|forma|cv|nothosubsp|nothovar)\.?(?=\s|$)")
LATIN_EPITHET_RE = re.compile(r"^[{0}][{0}-]+(?:us|um|a|is|i|ens|ans|ex|ix|or)$".format(LOWER))


def template_end(text, start):
    """Index just after the template that opens with "{{" at `start` (the text end if it never closes)."""
    depth = 0
    for match in BRACES_RE.finditer(text, start):
        depth += 1 if match.group() == "{{" else -1
        if depth == 0:
            return match.end()
    return len(text)


def find_template(text, pattern, pos=0):
    """(start, end) of the first template whose opening matches `pattern`, nested ones inside, or None."""
    match = pattern.search(text, pos)
    if not match:
        return None
    return match.start(), template_end(text, match.start())


def top_level_templates(text):
    """(start, end) of every template that is not nested in another one."""
    spans = []
    pos = 0
    while True:
        match = BRACES_RE.search(text, pos)
        if not match:
            return spans
        if match.group() == "}}":
            pos = match.end()
            continue
        end = template_end(text, match.start())
        spans.append((match.start(), end))
        pos = end


def name_key(name):
    """'Species_list' / 'species list' / 'Specieslist' -> 'specieslist'."""
    return re.sub(r"[\s_]+", "", name).lower()


def template_name(template):
    """'Speciesbox' from '{{Speciesbox | genus = ...}}'."""
    match = TEMPLATE_NAME_RE.match(template)
    return match.group(1) if match else ""


def template_params(template):
    """{'genus': 'Prunus', '1': 'first positional', ...}; pipes in nested templates and links do not split."""
    body = COMMENT_RE.sub("", template)
    body = body[2:-2] if body.endswith("}}") else body[2:]
    parts = []
    depth = 0
    last = 0
    for match in PARAM_TOKEN_RE.finditer(body):
        token = match.group()
        if token in ("{{", "[["):
            depth += 1
        elif token in ("}}", "]]"):
            depth = max(depth - 1, 0)
        elif depth == 0:
            parts.append(body[last:match.start()])
            last = match.end()
    parts.append(body[last:])
    params = {}
    position = 0
    for part in parts[1:]:
        named = PARAM_NAME_RE.match(part)
        if named:
            params[named.group(1).lower()] = named.group(2).strip()
        else:
            position += 1
            params[str(position)] = part.strip()
    return params


def positional(params):
    """Positional values of template_params in order."""
    values = []
    while str(len(values) + 1) in params:
        values.append(params[str(len(values) + 1)])
    return values


def convert_text(params):
    """'2 m' from {{convert|2|m|ft}}, '2 to 3 m' from {{convert|2|to|3|m}}, '6 ft 2 in' from {{convert|6|ft|2|in|m}}."""
    values = positional(params)
    if not values or not NUMBER_RE.match(values[0]):
        return ""
    text, rest = values[0], values[1:]
    if len(rest) >= 2 and rest[0] in CONVERT_RANGES and NUMBER_RE.match(rest[1]):
        text += CONVERT_RANGES[rest[0]] + rest[1]
        rest = rest[2:]
    if not rest:
        return text
    text += " " + _convert_unit(rest[0])
    if len(rest) >= 3 and NUMBER_RE.match(rest[1]):
        text += " {} {}".format(rest[1], _convert_unit(rest[2]))
    return text


def _convert_unit(unit):
    """'m' -> 'm', 'C' -> '°C', 'e6t' -> 'million t'."""
    prefix = CONVERT_PREFIXES.get(unit[:2], "") if len(unit) > 2 else ""
    unit = unit[2:] if prefix else unit
    return prefix + CONVERT_UNITS.get(unit, unit)


def _inline_text(match):
    template = match.group()
    key = name_key(template_name(template))
    if key in CONVERT_TEMPLATES:
        return convert_text(template_params(template))
    keep = INLINE_TEMPLATES.get(key)
    if keep is None:
        return ""
    if not isinstance(keep, int):
        return keep
    return template_params(template).get(str(keep), "")


def drop_templates(text):
    """Text without templates, the nested ones included; inline text templates leave their words."""
    previous = None
    while previous != text:
        previous = text
        text = INNER_TEMPLATE_RE.sub(_inline_text, text)
    return text


def _link_text(match):
    target, label = match.group(1), match.group(2)
    return label if label and label.strip() else target


def strip_noise(wikitext):
    """Wikitext without comments, refs, galleries, templates and file/category links; links to their labels."""
    text = COMMENT_RE.sub("", wikitext)
    text = REF_RE.sub("", text)
    text = DROPPED_ELEMENT_RE.sub("", text)
    text = drop_templates(text)
    text = LINK_RE.sub(_link_text, text)
    return FILE_LINK_RE.sub("", text)


def plain_text(wikitext):
    """Readable text of a wikitext fragment ("[[Carl Linnaeus|L.]]<ref>...</ref>" -> "L.")."""
    text = strip_noise(wikitext)
    text = EXTERNAL_LINK_RE.sub(r"\1", text)
    text = BR_RE.sub(" ", text)
    text = TAG_RE.sub("", text)
    text = QUOTES_RE.sub("", text)
    text = MAGIC_WORD_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", html.unescape(text))
    text = SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = SPACE_AFTER_BRACKET_RE.sub("(", text)
    return EMPTY_BRACKETS_RE.sub("", text).strip()


def clean_name(wikitext):
    """"''[[Prunus]]''" -> "Prunus", "Dryas (plant)" -> "Dryas", "Plinia_(bug)" -> "Plinia"; None when empty."""
    name = WHITESPACE_RE.sub(" ", plain_text(wikitext or "").replace("†", "").replace("_", " "))
    name = DISAMBIGUATOR_RE.sub("", name).strip()
    return name or None


def unique(items):
    """Items in first-seen order without duplicates and empty strings."""
    return list(dict.fromkeys(item for item in items if item))


def categories(text):
    """Category names in page order ("[[Category:Prunus|Almond]]" -> "Prunus")."""
    return unique(WHITESPACE_RE.sub(" ", name.replace("_", " ")).strip() for name in CATEGORY_RE.findall(text))


def year_described(authority, category_names):
    """Year of the authority ("Batsch, 1801"), else the earliest "... described in YYYY" category."""
    if authority:
        text = OTHER_NAME_RE.sub("", authority)
        basionym = BASIONYM_AUTHOR_RE.match(text)
        if basionym and not YEAR_RE.search(basionym.group(1)):
            text = ""
        match = YEAR_RE.search(text)
        if match:
            return int(match.group(1))
    years = [int(match.group(1)) for match in (DESCRIBED_IN_RE.search(name) for name in category_names) if match]
    return min(years) if years else None


def iucn_status(params):
    """IUCN category code ("LC") when the box status follows an IUCN system, else None."""
    system = plain_text(params.get("status_system", "")).upper().replace(" ", "")
    if not system.startswith("IUCN"):
        return None
    status = plain_text(params.get("status", "")).upper().replace(" ", "")
    status = IUCN_OLD_STATUSES.get(status, status)
    return status if status in IUCN_STATUSES else None


def synonym_items(wikitext, genus=None):
    """(text, listed, author) items in page order; only a name list cell (listed) has a separate author."""
    text = REF_RE.sub("", COMMENT_RE.sub("", wikitext))
    items = []
    pos = 0
    for start, end in top_level_templates(text):
        template = text[start:end]
        key = name_key(template_name(template))
        if key not in NAME_LIST_TEMPLATES and key not in CONTAINER_TEMPLATES:
            continue
        items.extend(_line_items(text[pos:start]))
        values = positional(template_params(template))
        if key in NAME_LIST_TEMPLATES:
            items.extend((name, True, author) for name, author in _list_pairs(values, key, genus))
        else:
            for value in values:
                items.extend(synonym_items(value, genus))
        pos = end
    items.extend(_line_items(text[pos:]))
    return items


def _line_items(text):
    return [(line, False, "") for line in ITEM_SPLIT_RE.split(text) if line.strip()]


def _list_pairs(values, key, genus):
    """(name, author) cells of a name list; a missing or extra author cell does not shift the pairs."""
    pairs = []
    i = 0
    while i < len(values):
        cell = plain_text(values[i])
        following = values[i + 1] if i + 1 < len(values) else None
        next_is_name = (following is not None and key != "genuslist"
                        and bool(BINOMIAL_CELL_RE.match(plain_text(following))))
        if not cell or (AUTHOR_CELL_RE.search(cell) and not BINOMIAL_CELL_RE.match(cell)) or (
                key == "specieslist" and next_is_name and SINGLE_WORD_RE.match(cell) and cell != genus):
            i += 1
        elif next_is_name or following is None:
            pairs.append((values[i], ""))
            i += 1
        else:
            pairs.append((values[i], following))
            i += 2
    return pairs


def _author_mark(match):
    author = match.group(1) if match.group(1) is not None else match.group(2)
    return AUTHOR_OPEN + author + AUTHOR_CLOSE


def _marked_item(item):
    """(text, blanked) of one item without markup: the author between marks in text, as spaces in blanked."""
    text = NBSP_RE.sub(" ", BOLD_RE.sub("", item))
    text = NBSP_RE.sub(" ", strip_noise(AUTHOR_RE.sub(_author_mark, text)))
    return text, AUTHOR_SPAN_RE.sub(lambda match: " " * len(match.group()), text)


def _name_candidates(text, blanked, listed):
    """(candidate, whole, rest) triples: each italic run must be a whole name, other text only starts with one."""
    if not listed:
        runs = list(ITALIC_NAME_RE.finditer(blanked))
        if runs:
            ends = [run.start() for run in runs[1:]] + [len(text)]
            return [(run.group(), True, text[run.end():end]) for run, end in zip(runs, ends)]
    return [(blanked, False, text)]


def _name_text(candidate):
    text = candidate.replace(AUTHOR_OPEN, " ").replace(AUTHOR_CLOSE, " ")
    text = WHITESPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", QUOTES_RE.sub("", text))))
    return text.strip(" *#:;,[")


def _rest_text(rest):
    return plain_text(rest.replace(AUTHOR_OPEN, " ").replace(AUTHOR_CLOSE, " "))


def author_text(rest):
    """Author as written after a synonym, without status notes and the year: "(L.) Arcang., 1882" -> "(L.) Arcang."."""
    text = WHITESPACE_RE.sub(" ", LOWER_NOTE_RE.sub(" ", rest)).strip(" ,;:*–—-")
    previous = None
    while previous != text:
        previous = text
        text = AUTHOR_INNER_YEAR_RE.sub(")", AUTHOR_YEAR_RE.sub("", AUTHOR_NOTE_RE.sub("", text)))
        text = text.strip(" ,;:")
    # "*[''U. capillacea'' <small>Vahl</small>]": brackets around the whole entry.
    if text.count("[") != text.count("]"):
        text = WHITESPACE_RE.sub(" ", text.replace("[", " ").replace("]", " ")).strip(" ,;:")
    return text or None


def synonym_entries(wikitext, genus=None, accepted=()):
    """(name, author) of every synonym of a box `synonyms` value in page order; author None when not given.

    "''L. scariola''" takes the last genus spelled out with an L; flagged and informal names are left out.
    """
    known = {genus[0]: genus} if genus else {}
    found = []
    last = None
    for item, listed, author in synonym_items(wikitext or "", genus):
        text, blanked = _marked_item(item)
        if not listed and not LETTER_RE.search(blanked) and last is not None and not _rest_text(last[1]):
            last[1] = text
            last = None
            continue
        last = None
        if SYNONYMS_OF_RE.match(blanked):
            continue
        skip_next = False
        for candidate, whole, rest in _name_candidates(text, blanked, listed):
            if skip_next:
                skip_next = False
                continue
            name_text = _name_text(candidate)
            match = NAME_RE.match(name_text)
            if not match or (whole and match.end() < len(name_text.rstrip(" ."))):
                continue
            if not whole:
                full = _name_text(rest)
                cut = full if full.startswith(match.group()) else name_text
                rest = cut[len(match.group()):]
            if listed:
                rest = rest + " " + author
            plain_rest = _rest_text(rest)
            skip_next = bool(OTHER_NAME_FLAG_RE.search(plain_rest))
            words = re.sub(r"×\s*", "× ", match.group()).replace(" x ", " × ").split()
            first = 1 if words[0] == "×" else 0
            # "Boiss." is an author; a plain single word is a heading ("Homotypic") unless above genus.
            if len(words) == first + 1 and name_text[match.end():match.end() + 1] == ".":
                continue
            if not listed and not whole and len(words) < 2 and not HIGHER_TAXON_RE.match(words[0]):
                continue
            if INFORMAL_REST_RE.match(plain_rest):
                continue
            if words[first].endswith("."):
                if words[first][0] not in known or len(words) == first + 1:
                    continue
                words[first] = known[words[first][0]]
            else:
                known[words[first][0]] = words[first]
            name = " ".join(words)
            if name in accepted or name == genus:
                continue
            last = [name, rest]
            found.append(last)
    entries = []
    for name, rest in found:
        plain_rest = _rest_text(rest)
        if not SYNONYM_FLAG_RE.search(plain_rest):
            entries.append((name, author_text(plain_rest)))
    return entries


def parse_synonyms(wikitext, genus=None, accepted=()):
    """Synonym names of a box `synonyms` value: no authorities, page order, de-duplicated (see synonym_entries)."""
    return unique(name for name, _ in synonym_entries(wikitext, genus, accepted))


def synonym_authors(entries):
    """{name: author} of synonym_entries, the first author given for each name."""
    authors = {}
    for name, author in entries:
        if author and name not in authors:
            authors[name] = author
    return authors


def lead_start(text, box_span):
    """Index where the lead starts: after the box, or after the template it sits in ("{{stack|{{Speciesbox}}}}")."""
    start, end = box_span
    for outer_start, outer_end in top_level_templates(text):
        if outer_start > start:
            break
        # An unclosed template before the box would run to the page end and swallow the lead.
        if start < outer_end and end < outer_end < len(text):
            return outer_end
    return end


def lead_wikitext(text, box_end):
    """Wikitext between the end of the box and the first heading, without refs, tables and lists.

    Refs go first and list lines inside templates stay: a ref may hold "*{{cite web|...}}" lines.
    """
    heading = HEADING_RE.search(text, box_end)
    lead = TABLE_RE.sub("", REF_RE.sub("", text[box_end:heading.start() if heading else len(text)]))
    templates = top_level_templates(lead)

    def drop_outside_templates(match):
        inside = any(start <= match.start() < end for start, end in templates)
        return match.group() if inside else ""

    return LIST_LINE_RE.sub(drop_outside_templates, lead)


def first_paragraph(wikitext):
    """First paragraph of the lead that has words once templates and files are gone ("}}" alone has none)."""
    for paragraph in PARAGRAPH_SPLIT_RE.split(strip_noise(wikitext)):
        if LETTER_RE.search(plain_text(paragraph)):
            return paragraph
    return ""


def bold_terms(paragraph):
    """(wikitext, italic) of every bold run; italic when the run starts in italics.

    Quote runs are toggled as MediaWiki does; one regex fails on "'''''Citrus'' × ''microcarpa'''''".
    """
    terms = []
    for line in paragraph.split("\n"):
        bold = italic = starts_italic = False
        parts = []
        pos = 0
        for match in QUOTE_RUN_RE.finditer(line):
            if bold:
                parts.append(line[pos:match.start()])
            # "''''" is an apostrophe and a bold toggle, longer runs end in five quotes.
            run = 3 if len(match.group()) == 4 else min(len(match.group()), 5)
            if run != 2:
                if bold:
                    terms.append(("".join(parts), starts_italic))
                else:
                    parts = []
                    starts_italic = italic if run == 3 else not italic
                bold = not bold
            if run != 3:
                italic = not italic
            pos = match.end()
    return terms


def common_names(paragraph, scientific_names, genus=None):
    """Bold terms of the paragraph that are not scientific names (bold italics are, by Wikipedia style)."""
    known = {name.lower() for name in scientific_names if name}
    if genus is None:
        first = next((name for name in scientific_names if name), "")
        genus = first.split(" ")[0] if first else None
    names = []
    for term, italic in bold_terms(paragraph):
        name = plain_text(term).strip(" ,.;:\"")
        if (name and not italic and name.lower() not in known and not HIGHER_TAXON_RE.match(name)
                and not COMMON_RANK_MARKER_RE.search(name) and not _is_genus_binomial(name, genus)):
            names.append(name)
    return unique(names)


def _is_genus_binomial(term, genus):
    words = term.split()
    return (bool(genus) and len(words) >= 2 and words[0] == genus and bool(LATIN_EPITHET_RE.match(words[1]))
            and (len(words) == 2 or not words[2][0].islower()))


def _species_epithet(species, genus):
    """Epithet of a `species` value: "J. xiphioides" -> "xiphioides", "X bimundorum" -> "× bimundorum"."""
    if not species:
        return species
    species = HYBRID_SIGN_RE.sub("×", species)
    words = species.split()
    if genus and len(words) > 1 and words[0] in (genus, genus[0] + "."):
        species = " ".join(words[1:])
    return species


def box_names(box, params, title=""):
    """(genus, species, taxon, binomial) of the box; an Automatic taxobox without `taxon` uses the title."""
    genus = clean_name(params.get("genus"))
    species = clean_name(params.get("species"))
    taxon = clean_name(params.get("taxon")) or (clean_name(title) if box == "automatic taxobox" else None)
    binomial = None
    if box == "taxobox":
        binomial = clean_name(params.get("trinomial")) or clean_name(params.get("binomial"))
    elif box == "automatic taxobox":
        words = (taxon or "").split()
        if (len(words) >= 2 and re.match(EPITHET + "$", words[-1]) and not INFRAGENERIC_RE.match(taxon)
                and not INFORMAL_GROUP_RE.search(taxon)):
            binomial = taxon
    elif box == "hybridbox":
        # Hybridbox has no parameter for the hybrid's epithet, so only an explicit one in one genus counts.
        species = _species_epithet(clean_name(params.get("species") or params.get("nothospecies")), genus)
        genus2 = clean_name(params.get("genus2"))
        if genus and species and genus2 in (None, genus):
            binomial = "{} × {}".format(genus, species.lstrip("× "))
    else:
        if taxon and not genus:
            genus, _, rest = taxon.partition(" ")
            species = species or rest or None
        species = _species_epithet(species, genus)
        if genus and species:
            binomial = "{} {}".format(genus, species)
            for param, marker in INFRA_PARAMS:
                value = clean_name(params.get(param))
                if value and box == "infraspeciesbox":
                    binomial = "{} {} {}".format(binomial, marker, value)
                elif value and box == "subspeciesbox":
                    binomial = "{} {}".format(binomial, value)
    if binomial:
        binomial = WHITESPACE_RE.sub(" ", HYBRID_SIGN_RE.sub("×", binomial).replace("×", " × ")).strip()
        words = [word for word in binomial.split() if word != "×"]
        genus = genus if box not in ("taxobox", "automatic taxobox") else words[0]
        species = words[1] if len(words) > 1 else species
    if species:
        species = species.replace("×", "").strip()
    return genus, species, taxon, binomial


def taxon_rank(box, params, taxon, binomial, lead, title=""):
    """"species", "infraspecies", "genus", "higher" or None (not decidable).

    Strongest evidence first; the title comes last, as higher taxa have such titles too ("Carnivora").
    """
    if binomial:
        words = [word for word in binomial.split() if word != "×"]
        return "infraspecies" if len(words) > 2 else "species"
    if INFORMAL_NAME_RE.search(title or ""):
        return None
    if box == "taxobox":
        if not clean_name(params.get("genus")):
            return "higher"
        return None if any(clean_name(params.get(name)) for name in BELOW_GENUS_PARAMS) else "genus"
    if box != "automatic taxobox" or not taxon or " " in taxon.replace("× ", ""):
        return None
    head = lead[:LEAD_GENUS_WINDOW]
    if (params.get("type_species") or LEAD_GENUS_RE.search(head)
            or re.search(r"\bgenus\s+" + re.escape(taxon) + r"\b", head)):
        return "genus"
    if HIGHER_TAXON_RE.match(taxon) or params.get("type_genus"):
        return "higher"
    subdivision = plain_text(params.get("subdivision_ranks", ""))
    if SUBDIVISION_GENUS_RE.search(subdivision) or THIS_GENUS_RE.search(head):
        return "genus"
    rank = LEAD_RANK_RE.search(lead[:250])
    if rank:
        return "genus" if rank.group(1).lower() == "genus" else "higher"
    if SUBDIVISION_HIGHER_RE.search(subdivision):
        return "higher"
    return "genus" if title.split(" ")[0] == taxon else None


def plant_hint(text, box_text, category_names):
    """True when a plant category, kingdom Plantae in the box or the short description marks a plant."""
    if any(name.startswith(PLANT_CATEGORY_PREFIXES) or PLANT_FAMILY_CATEGORY_RE.search(name)
           or name in PLANT_GROUP_GENERA or (name.endswith(" genera") and name[:-len(" genera")] in PLANT_ORDERS)
           for name in category_names):
        return True
    if PLANTAE_RE.search(box_text):
        return True
    short = SHORT_DESCRIPTION_RE.search(text)
    return bool(short and PLANT_WORDS_RE.search(short.group(1)) and not NOT_PLANT_WORDS_RE.search(short.group(1)))


def parse_page(record):
    """{page_id, title, redirect} plus box and the parse_box fields, or None for non-articles and the dump tail."""
    head = PAGE_HEAD_RE.search(record)
    if not head or head.group(2) != "0":
        return None
    page = {"page_id": int(head.group(3)), "title": html.unescape(head.group(1))}
    if head.group(4) is not None:
        page["redirect"] = html.unescape(head.group(4))
        return page
    page["redirect"] = None
    page["box"] = None
    body = TEXT_RE.search(record, head.end())
    if body and BOX_RE.search(body.group(1)):
        page.update(parse_box(html.unescape(body.group(1)), page["title"]) or {})
    return page


def parse_box(text, title=""):
    """Fields of an article with a taxobox (unescaped wikitext), or None when it has none."""
    text = NON_WIKITEXT_ELEMENT_RE.sub("", COMMENT_RE.sub("", text))
    span = find_template(text, BOX_RE)
    if not span:
        return None
    box_text = text[span[0]:span[1]]
    key = name_key(template_name(box_text))
    box = BOX_NAMES.get(key, key)
    params = template_params(box_text)
    genus, species, taxon, binomial = box_names(box, params, title)
    lead_source = lead_wikitext(text, lead_start(text, span))
    lead = plain_text(lead_source)
    rank = taxon_rank(box, params, taxon, binomial, lead, title)
    if not genus and taxon and (rank == "genus" or INFRAGENERIC_RE.match(taxon)):
        genus = taxon.split()[0] if rank != "genus" else taxon
    elif not genus and taxon and title.startswith(taxon + " ") and INFORMAL_NAME_RE.search(title):
        genus = taxon
    authority = box_authority(params, rank)
    category_names = categories(text)
    entries = synonym_entries(params.get("synonyms"), genus, {binomial, taxon})
    synonyms = unique(name for name, _ in entries)
    return {
        "box": box,
        "genus": genus,
        "species": species,
        "taxon": taxon,
        "binomial": binomial,
        "rank": rank,
        "authority": authority,
        "year_described": year_described(authority, category_names),
        "iucn_status": iucn_status(params),
        "synonyms": synonyms,
        "synonym_authors": synonym_authors(entries),
        "categories": category_names,
        "common_names": common_names(first_paragraph(lead_source), [binomial, taxon, genus] + synonyms, genus or ""),
        "lead": lead,
        "plant_hint": plant_hint(text, box_text, category_names),
    }


def box_authority(params, rank):
    """Authority of the box; the old Taxobox names the parameter after the rank (genus_authority)."""
    if clean_name(params.get("trinomial")):
        names = ("authority", "trinomial_authority")
    elif rank == "genus":
        names = ("authority", "binomial_authority", "genus_authority")
    else:
        names = ("authority", "binomial_authority")
    for name in names:
        value = plain_text(params.get(name) or "")
        if value:
            return value
    return None
