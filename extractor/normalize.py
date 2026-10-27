"""Name normalisation shared by all extractors: family names and species keys.

Sites type family names by hand, so the same family appears as "Rosaceae",
"Roseaceae", "Rosacea" or "Asteraceae (Compositae) - Aster Family". The species
key is the join key for merging records of one plant from several sites.
"""

import html
import re
from collections import Counter

# Traditional family names that are still valid alternatives (ICN Art. 18.5),
# mapped to the -aceae names the sites use most.
CONSERVED_FAMILY_NAMES = {
    "Compositae": "Asteraceae", "Gramineae": "Poaceae", "Leguminosae": "Fabaceae",
    "Palmae": "Arecaceae", "Cruciferae": "Brassicaceae", "Umbelliferae": "Apiaceae",
    "Labiatae": "Lamiaceae", "Guttiferae": "Clusiaceae", "Papilionaceae": "Fabaceae",
}

FAMILY_WORD_RE = re.compile(r"[A-Za-z]+")
FAMILY_SHAPE_RE = re.compile(r"^[A-Z][a-z]+aceae$")

# "Genus epithet", "Genus × epithet", "× Genus epithet"; the hybrid sign may be
# typed as "x". Ranks and cultivar names after the binomial are not part of the key.
BINOMIAL_RE = re.compile(r"^\s*(?:[x×]\s+)?([A-Z][a-z]+)\s+(?:([x×])\s+)?([a-z][a-z-]+)\b")
NOT_EPITHETS = {"sp", "spp", "var", "subsp", "ssp", "f", "cv", "x", "group", "cultivars", "hybrids"}


def clean_family(raw):
    """'Asteraceae (Compositae) - Aster Family' -> 'Asteraceae'; None when it is not a family name."""
    if not raw:
        return None
    words = FAMILY_WORD_RE.findall(html.unescape(raw))
    if not words:
        return None
    word = words[0].capitalize()
    word = CONSERVED_FAMILY_NAMES.get(word, word)
    word = KNOWN_FAMILY_TYPOS.get(word, word)
    # Typos in the ending ("Asteracea") are kept here and repaired by family_mapping;
    # short or non-Latin first words ("c", a pronunciation hint) are not families.
    return word if len(word) >= 5 and word.endswith(("ae", "ea")) else None


FAMILY_ENDING_RE = re.compile(r"[aeiou]*c?[aeiou]*$")


def family_stem(name):
    """'Roseacae' -> 'Ros': the name without the -aceae ending and its misspellings."""
    return FAMILY_ENDING_RE.sub("", name)


# Misspellings inside the stem seen on NCSU. They cannot be repaired by a rule:
# real families also differ by one letter of the stem (Asteliaceae/Asteraceae,
# Melianthaceae/Melanthiaceae, Moraceae/Rosaceae), so these few are listed by hand.
KNOWN_FAMILY_TYPOS = {
    "Ameranthaceae": "Amaranthaceae", "Solonaceae": "Solanaceae",
    "Melathiaceae": "Melanthiaceae", "Bereridaceae": "Berberidaceae",
}


def is_typo_of(name, candidate):
    """True when `name` looks like a misspelling of the family `candidate`.

    Edit distance would merge real families (Moraceae/Rosaceae differ by one
    letter), so only an error in the -aceae ending counts: the stems must be equal.
    """
    return family_stem(name) == family_stem(candidate)


def family_mapping(raw_families, min_ratio=5):
    """Map every raw family string to its normalised name.

    A cleaned name is rewritten to a name used at least `min_ratio` times more
    often when it looks like a misspelling of it (see is_typo_of). Everything that
    does not end up as a well-formed "-aceae" name becomes None.
    """
    cleaned = {raw: clean_family(raw) for raw in set(raw_families)}
    counts = Counter(cleaned[raw] for raw in raw_families if cleaned[raw])
    by_frequency = [name for name, _ in counts.most_common()]
    canonical = {}
    for name in by_frequency:
        target = name
        for candidate in by_frequency:
            if counts[candidate] < min_ratio * counts[name]:
                break
            if candidate != name and is_typo_of(name, candidate):
                target = canonical.get(candidate, candidate)
                break
        canonical[name] = target if FAMILY_SHAPE_RE.match(target) else None
    return {raw: canonical.get(name) if name else None for raw, name in cleaned.items()}


def species_key(name):
    """'Quercus robur L.' -> 'quercus robur'; 'Abelia x grandiflora' -> 'abelia × grandiflora'.

    Returns "" when the name is not a binomial (genus only, "Acer spp.", junk).
    """
    if not name:
        return ""
    match = BINOMIAL_RE.match(html.unescape(name).replace("×", " × "))
    if not match or match.group(3) in NOT_EPITHETS:
        return ""
    hybrid = " ×" if match.group(2) else ""
    return "{}{} {}".format(match.group(1).lower(), hybrid, match.group(3))
