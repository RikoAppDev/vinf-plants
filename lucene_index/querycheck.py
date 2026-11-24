"""Checks of a query text that the Lucene query parser does not make, or makes with a misleading result.

No Lucene in this module, so the checks are tested without Java. scan() follows the lexer of the
StandardQueryParser: "phrases", /regular expressions/, [ranges], a backslash escapes one character,
and field:value has the variants field=value, field>value, field>=value, field<value, field<=value.

    fields(query)       the field names the query uses
    plain_words(query)  True for words without any query syntax, as a plant name is typed
    problem(query)      None, or why the query cannot give what the user means
    notes(query)        notices of a query that runs but may surprise
    syntax_hint(query)  a plain explanation of a syntax error, None if the cause is not recognised
"""

import collections
import difflib
import re

from .documents import EXACT_FIELDS, NUMBER_FIELDS, STORED_FIELDS, TEXT_FIELDS

SEARCHABLE_FIELDS = TEXT_FIELDS + EXACT_FIELDS + NUMBER_FIELDS
# IntPoint values are 32-bit; the parser narrows a larger number without a word.
INT_MIN, INT_MAX = -2 ** 31, 2 ** 31 - 1
NUMBER_EXAMPLES = {
    "year": ("1753", "[1754 TO 1800]"), "zone_min": ("5", "[* TO 5]"), "zone_max": ("9", "[8 TO *]"),
    "height_max_cm": ("300", "[* TO 1000]"), "density": ("700", "[700 TO *]"), "janka": ("5000", "[5000 TO *]"),
    "edibility": ("5", "[4 TO 5]"), "medicinal": ("3", "[3 TO 5]"), "n_sources": ("4", "[3 TO *]"),
}
STORED_HINTS = {"url": "source:pfaf finds the plants of one site", "wiki_title": "wiki:oak searches the Wikipedia lead",
                "wiki_url": "wiki:oak searches the Wikipedia lead"}
# *:* matches all documents; fn:ordered(a b) and the other interval functions are written like a field.
NOT_FIELDS = ("*", "fn")
OPERATOR_WORDS = ("and", "or", "not")
# Fields whose analyzer drops English stop words (lucene_index.build); the tag fields keep them.
STOP_WORD_FIELDS = ("name", "common_name", "synonym", "text", "wiki", "uses")
# U+3000 is the ideographic space, which the parser also skips.
WHITESPACE = " \t\n\r\u3000"
# Characters that end a term; + and - only cannot start one, and a backslash escapes the next character.
TERM_END = set('!():^<>=[]"{}~/@')
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
WHOLE_NUMBER_RE = re.compile(r"-?[0-9]+")
ESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)

Token = collections.namedtuple("Token", "kind text items")


def unescape(text):
    return ESCAPE_RE.sub(r"\1", text)


def closing(query, i, quote):
    """Index of the first unescaped quote character from i on; -1 if there is none."""
    while i < len(query):
        if query[i] == "\\":
            i += 2
        elif query[i] == quote:
            return i
        else:
            i += 1
    return -1


def scan_range(query, i):
    """(range or unclosed token, index after it) of the range that opens at query[i]."""
    start, items = i, []
    i += 1
    while i < len(query):
        char = query[i]
        if char in WHITESPACE:
            i += 1
        elif char in "]}":
            return Token("range", query[start:i + 1], items), i + 1
        elif char == '"':
            end = closing(query, i + 1, '"')
            if end < 0:
                break
            items.append(query[i:end + 1])
            i = end + 1
        else:
            end = i
            while end < len(query) and query[end] not in WHITESPACE and query[end] not in "]}":
                end += 1
            items.append(query[i:end])
            i = end
    return Token("unclosed", query[start:], None), len(query)


def scan(query):
    """Tokens of a query.

    Kinds: term, phrase, regex, range (items: the words between the brackets), ( and ), and, or, not
    (also &&, || and !), + and -, field (: = < <= > >=), modifier (^2 ~1 @2), stray (a closing bracket
    without its range) and unclosed (a phrase, regular expression or range without its end, or a
    backslash at the end); scanning stops at an unclosed token.
    """
    found, i = [], 0
    while i < len(query):
        char = query[i]
        if char in WHITESPACE:
            i += 1
        elif char in '"/':
            end = closing(query, i + 1, char)
            if end < 0:
                found.append(Token("unclosed", query[i:], None))
                break
            found.append(Token("phrase" if char == '"' else "regex", query[i:end + 1], None))
            i = end + 1
        elif char in "[{":
            token, i = scan_range(query, i)
            found.append(token)
        elif char in "]}":
            found.append(Token("stray", char, None))
            i += 1
        elif char in "()+-":
            found.append(Token(char, char, None))
            i += 1
        elif char == "!":
            found.append(Token("not", char, None))
            i += 1
        elif char in ":=<>":
            text = query[i:i + 2] if query[i:i + 2] in ("<=", ">=") else char
            found.append(Token("field", text, None))
            i += len(text)
        elif char in "^~@":
            match = NUMBER_RE.match(query, i + 1)
            text = char + (match.group(0) if match else "")
            found.append(Token("modifier", text, None))
            i += len(text)
        else:
            start = i
            while i < len(query) and query[i] not in WHITESPACE and query[i] not in TERM_END:
                i += 2 if query[i] == "\\" else 1
            if i > len(query):
                found.append(Token("unclosed", query[start:], None))
                break
            text = query[start:i]
            kind = {"AND": "and", "&&": "and", "OR": "or", "||": "or", "NOT": "not"}.get(text, "term")
            found.append(Token(kind, text, None))
    return found


def field_values(tokens):
    """(field names in order of use, [(field, operator, token)] of every value) of scanned tokens.

    A value is a term, phrase, regular expression or range. Its field is the one named before it or
    before its group, as in name:(a b); None means the default fields. operator is the : = < > etc.
    right before the value, None for a value without its own field name.
    """
    names, values = [], []
    groups, named = [None], None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if token.kind == "term" and following is not None and following.kind == "field":
            name = unescape(token.text)
            if name not in names:
                names.append(name)
            named = (name, following.text)
            i += 2
            continue
        if token.kind == "(":
            groups.append(named[0] if named else groups[-1])
        elif token.kind == ")" and len(groups) > 1:
            groups.pop()
        elif token.kind in ("term", "phrase", "regex", "range"):
            values.append(named + (token,) if named else (groups[-1], None, token))
        named = None
        i += 1
    return [name for name in names if name not in NOT_FIELDS], values


def fields(query):
    """Field names the query uses, in order, outside phrases and regular expressions; not *:*."""
    return field_values(scan(query))[0]


def plain_words(query):
    """True if the query is only words, as a plant name is typed: no field, operator, phrase, wildcard,
    fuzzy term, range, boost, group or regular expression.

    Diacritics, digits, ×, a hyphen inside a word, a full stop and the single quotes around a cultivar
    name ('Seiryu') are characters of a term for the parser, so a name with them is plain words.
    """
    tokens = scan(query)
    return bool(tokens) and all(token.kind == "term" and not set(ESCAPE_RE.sub("", token.text)) & set("*?")
                                for token in tokens)


def suggestions(name):
    """Searchable fields that contain the name or are contained in it, else the most similar ones."""
    lower = name.lower()
    found = [field for field in SEARCHABLE_FIELDS
             if (len(lower) >= 3 and lower in field) or (len(field) >= 3 and field in lower)]
    return found[:3] or difflib.get_close_matches(lower, SEARCHABLE_FIELDS, n=3, cutoff=0.5)


def field_problem(name):
    if name in SEARCHABLE_FIELDS:
        return None
    lower = name.lower()
    if lower in SEARCHABLE_FIELDS:
        return "field names are written in lower case: {}, not {}".format(lower, name)
    if lower in STORED_FIELDS:
        hint = STORED_HINTS.get(lower)
        return "{} is only stored to be shown with a hit, it is not indexed and cannot be searched{}".format(
            lower, "; " + hint if hint else "")
    close = suggestions(name)
    if close:
        return "unknown field {}; did you mean {}?".format(name, " or ".join(close))
    return "unknown field {}; the fields are {}".format(name, ", ".join(SEARCHABLE_FIELDS))


def range_problem(field, token):
    if token.kind != "range" or len(token.items) != 3:
        return None
    low, to, high = token.items
    if to != "TO" and to.lower() == "to":
        return "TO in a range is written in capitals: {}{}{} TO {}{}".format(
            field + ":" if field else "", token.text[0], low, high, token.text[-1])
    return None


def range_ends(token):
    """(low, high) of a range token with quotes and escapes removed; None unless it is [low TO high]."""
    if token.kind != "range" or len(token.items) != 3 or token.items[1] != "TO":
        return None
    return tuple(unescape(item[1:-1] if item.startswith('"') else item) for item in (token.items[0], token.items[2]))


def number_problem(field, operator, token):
    """Why a value of a number field is no 32-bit whole number; None if it is one."""
    example = "for example {0}:{1} or {0}:{2}".format(field, *NUMBER_EXAMPLES.get(field, ("1", "[1 TO 5]")))
    if token.kind == "regex":
        return "{} takes whole numbers, not a regular expression; {}".format(field, example)
    if token.kind == "range":
        # A range without TO is a syntax error that Lucene reports.
        ends = [end for end in range_ends(token) or () if end != "*"]
    elif token.kind == "phrase":
        ends = [unescape(token.text[1:-1])]
    elif token.text == "*":
        return "{0}{1}* is no query on a number field; {0}:[* TO *] finds every plant with a {0}".format(
            field, operator or ":")
    else:
        ends = [unescape(token.text)]
    for end in ends:
        if not WHOLE_NUMBER_RE.fullmatch(end):
            return "{} takes whole numbers, not {}; {}".format(field, end, example)
        if not INT_MIN <= int(end) <= INT_MAX:
            return "{} is too {} for {}, which holds whole numbers from {} to {}; {}".format(
                end, "small" if int(end) < 0 else "large", field, INT_MIN, INT_MAX, example)
    return None


def star_problem(field, operator, token):
    """Message for * used as a field name in anything but *:*; the parser fails or matches nothing there."""
    if field == "*" and not (operator == ":" and token.kind == "term" and token.text == "*"):
        return "* is no field name: *:* matches all plants; to search one field write for example name:oak"
    return None


def problem(query):
    """None, or a one-sentence message when the query cannot give what the user means.

    Lucene would answer such a query with no hits or with other hits than meant, and without saying why,
    or fail with an internal error: an unknown or stored-only field, * as a field name in anything but
    *:*, a number field value that is no 32-bit whole number, TO in lower case.
    """
    if not query.strip():
        return "the query is empty; *:* matches all plants"
    names, values = field_values(scan(query))
    for name in names:
        message = field_problem(name)
        if message:
            return message
    for field, operator, token in values:
        message = star_problem(field, operator, token) or range_problem(field, token)
        if not message and field in NUMBER_FIELDS:
            message = number_problem(field, operator, token)
        if message:
            return message
    return None


def clauses(tokens, i=0):
    """([clause is negative or matches nothing], index after the group) of the clauses from tokens[i] on."""
    found, negative = [], False
    while i < len(tokens):
        token = tokens[i]
        if token.kind == ")":
            return found, i + 1
        if token.kind in ("-", "not"):
            negative = True
        elif token.kind == "term" and i + 1 < len(tokens) and tokens[i + 1].kind == "field":
            i += 1
        elif token.kind == "(":
            inner, i = clauses(tokens, i + 1)
            found.append(negative or (bool(inner) and all(inner)))
            negative = False
            continue
        elif token.kind in ("term", "phrase", "regex", "range"):
            found.append(negative)
            negative = False
        i += 1
    return found, i


def quoted(words):
    return ", ".join('"{}"'.format(word) for word in words)


def operator_word_note(values):
    """Notice of and, or, not that are not written in capitals, so Lucene takes them for words; None if none."""
    groups, words = {}, []
    for field, operator, token in values:
        if token.kind == "term" and operator is None and token.text.lower() in OPERATOR_WORDS:
            how = "dropped as a stop word" if field is None or field in STOP_WORD_FIELDS else "searched in " + field
            groups.setdefault(how, [])
            for found in (groups[how], words):
                if token.text not in found:
                    found.append(token.text)
    if not words:
        return None
    detail = next(iter(groups)) if len(groups) == 1 else "; ".join(
        "{} {}".format(quoted(group), how) for how, group in groups.items())
    return "{} not written in capitals {} ({}); operators are written in capitals: AND, OR, NOT".format(
        quoted(words), "is no operator but a word" if len(words) == 1 else "are no operators but words", detail)


def reversed_range_note(values):
    """Notice of a range of a number field that no whole number fits in; None if there is none."""
    for field, _operator, token in values:
        ends = range_ends(token)
        if field not in NUMBER_FIELDS or not ends or not all(WHOLE_NUMBER_RE.fullmatch(end) for end in ends):
            continue
        low, high = int(ends[0]), int(ends[1])
        found = "the range {}:{} matches nothing".format(field, token.text)
        if low > high:
            return "{}, its lower end is above its upper end; write {}:{}{} TO {}{}".format(
                found, field, token.text[0], high, low, token.text[-1])
        if low + (token.text[0] == "{") > high - (token.text[-1] == "}"):
            better = "{}:{}".format(field, low) if low == high else "{}:[{} TO {}]".format(field, low, high)
            return "{}, no whole number lies inside it; write {}".format(found, better)
    return None


def notes(query):
    """Short notices of a query that runs but may not do what it seems to; [] for most queries."""
    tokens = scan(query)
    values = field_values(tokens)[1]
    found = [note for note in (operator_word_note(values), reversed_range_note(values)) if note]
    top, _end = clauses(tokens)
    if top and all(top):
        found.append("a query of only negative clauses matches nothing in Lucene; add a positive term, for example "
                     "quercus NOT robur, or write *:* {} for every plant except these".format(query.strip()))
    return found


def operator_hint(tokens):
    """Explanation of an operator without a clause on one of its sides; None if there is none."""
    binary, unary = ("and", "or"), ("not", "+", "-")
    previous = None
    for token in tokens:
        if token.kind in binary and (previous is None or previous.kind in ("(",) + binary + unary):
            return "{} needs a clause on both sides".format(token.text)
        if token.kind == ")" and previous is not None and previous.kind in binary + unary:
            return "{} needs a clause after it".format(previous.text)
        previous = token
    if previous is not None and previous.kind in binary + unary:
        return "{} needs a clause after it".format(previous.text)
    return None


def syntax_hint(query):
    """One plain sentence on why the parser rejects the query; None if the cause is not recognised."""
    tokens = scan(query)
    for token in tokens:
        if token.kind == "unclosed":
            if token.text.startswith('"'):
                return 'a quote " is not closed'
            if token.text.startswith("/"):
                return "a / starts a regular expression that is not closed; write \\/ to search for a slash"
            if token.text[0] in "[{":
                return "a range is not closed: write it as [low TO high], for example year:[1754 TO 1800]"
            return "a backslash at the end of the query escapes nothing"
    depth = 0
    for token in tokens:
        depth += {"(": 1, ")": -1}.get(token.kind, 0)
        if depth < 0:
            return "a closing parenthesis ) has no opening one"
        if token.kind == "stray":
            return "a closing bracket {} has no range that it closes".format(token.text)
    if depth > 0:
        return "a parenthesis ( is not closed"
    for field, _operator, token in field_values(tokens)[1]:
        if token.kind == "term" and token.text[0] in "*?" and field != "*":
            return "a word cannot start with * or ? (Lucene does not allow a leading wildcard); *:* matches all plants"
        if token.kind == "range" and (len(token.items) != 3 or token.items[1] != "TO"):
            return "a range is written [low TO high] with TO in capitals, and * is an open end: year:[* TO 1800]"
    previous = None
    for token in tokens:
        if token.kind == "field" and (previous is None or previous.kind != "term"):
            return "a field name goes before the colon, for example soil:clay"
        if token.kind == "modifier" and token.text in ("^", "@"):
            return "{} needs a number after it, for example {}".format(
                token.text, "name:robur^2" if token.text == "^" else "(quercus robur alba)@2")
        if token.kind == "modifier" and token.text[0] == "@" and (previous is None or previous.kind != ")"):
            return "@ follows a group in parentheses: (quercus robur alba)@2"
        previous = token
    for i, token in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if token.kind == "field" and following is not None and following.kind in ("-", "+"):
            return sign_hint(unescape(tokens[i - 1].text), token.text, following.kind, tokens[i + 2:i + 3])
        if token.kind == "field" and (following is None or following.kind not in ("term", "phrase", "regex",
                                                                                     "range", "(")):
            return "the field before {} needs a value after it, for example soil:clay".format(token.text)
    return operator_hint(tokens)


def sign_hint(field, operator, sign, rest):
    """Explanation of a - or + right after field: or field<= (a syntax error), with the right spelling."""
    value = rest[0].text if rest and rest[0].kind == "term" else "5"
    if field in NUMBER_FIELDS and sign == "-":
        return "a negative number is written with a backslash, {0}{1}\\-{2}, or inside a range such as {0}:[-5 TO 0]" \
            .format(field, operator, value)
    if field in NUMBER_FIELDS:
        return "a number is written without +: {}{}{}".format(field, operator, value)
    return "{0} goes before the field name: {0}{1}{2}{3}".format(sign, field, operator, value)
