"""Tests of lucene_index.querycheck: plain Python, no Java needed."""

import ast
import os
import re
import shlex
import unittest

from lucene_index import querycheck
from lucene_index.querycheck import fields, notes, problem, syntax_hint

SEARCH_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lucene_index", "search.py")


def search_docstring_examples():
    """Example queries of the lucene_index.search docstring, read without importing it (it needs Java).

    The usage lines give the query after lucene_index.search; in the syntax table the examples start
    at column 21 and are three or more spaces apart.
    """
    with open(SEARCH_PY, encoding="utf-8") as handle:
        docstring = ast.get_docstring(ast.parse(handle.read()))
    examples, in_table = [], False
    for line in docstring.splitlines():
        if "lucene_index.search " in line:
            words = shlex.split(line)
            rest = words[words.index("lucene_index.search") + 1:]
            examples.append(rest[1] if rest[0] == "--" else rest[0])
        elif line.startswith("Query syntax"):
            in_table = True
        elif in_table and line.startswith("    "):
            examples.extend(re.split(r" {3,}", line[21:].strip()))
        else:
            in_table = False
    return examples


# Queries that must pass without a problem, a notice or a syntax hint.
GOOD_QUERIES = [
    "quercus robur", '"quercus not robur"', 'name:"a:b"', 'text:"not a field: soil"', "*:*", "*:* NOT robur",
    "zone_min:[* TO 5]", "density:[700 TO *]", "density:{675 TO *]", "year:[1754 TO 1800}", 'year:["1754" TO "1800"]',
    "zone_min:[-5 TO 0]", "year:[* TO *]", "iucn:(vu OR en OR cr)", '"mountain laurel"~3', "quercsu~1", "quercsu~",
    "name:robur^3", "name:robur^2.5", "quercus NOT robur", "+quercus -robur", "quercus AND NOT robur", "rhodo*",
    "name:RHODO*", "year>1800", "year>=1754 AND year<=1800", "year=1753", 'year:"1753"', "name : robur",
    "year:2147483647", "year:[-2147483648 TO 0]", "fn:ordered(quercus robur)", "(quercus robur alba)@2", "name\\:x",
    "text:/ab:c/", "name:/rob.r/", "leaf:semi-evergreen", "quercus && robur", "quercus || robur", "!robur quercus",
    "light:not", "soil:clay AND (light:\"full sun\" OR light:shade)", "*:*^2", "*:*~2", "(*:*) AND soil:clay",
    "*:* -robur", "zone_min:[\\-5 TO 5]", "zone_min:\\-5", "zone_min<=\\-1", "year:[1754 TO 1754]",
]


class FieldsTest(unittest.TestCase):
    def test_field_names_outside_phrases_and_regular_expressions(self):
        cases = {
            "+name:x": ["name"], "-name:x": ["name"], "!name:x": ["name"], "(name:x)": ["name"], "(name:x": ["name"],
            "iucn:(vu OR en)": ["iucn"], 'name:"a:b"': ["name"], "text:/ab:c/": ["text"], "name\\:x": [],
            "*:*": [], "*:* NOT robur": [], 'soil:clay AND light:"full sun"': ["soil", "light"],
            "soil:clay soil:loam": ["soil"], "year>1800": ["year"], "year>=1754 AND year<=1800": ["year"],
            "year=1753": ["year"], "name : robur": ["name"], "a\\:b:c": ["a:b"], "fn:ordered(quercus robur)": [],
            "quercus robur": [], '"soil:clay"': [], "name:[a:b TO c]": ["name"], "color:red": ["color"],
        }
        for query, expected in cases.items():
            self.assertEqual(fields(query), expected, query)


class ProblemTest(unittest.TestCase):
    def assertProblem(self, query, *parts):
        message = problem(query)
        self.assertIsNotNone(message, query)
        self.assertNotIn("\n", message)
        for part in parts:
            self.assertIn(part, message, query)

    def test_good_queries_have_no_problem(self):
        for query in GOOD_QUERIES + search_docstring_examples():
            self.assertIsNone(problem(query), query)

    def test_an_empty_query(self):
        for query in ("", "   ", "\t\n", "\u3000"):
            self.assertProblem(query, "empty")

    def test_star_is_no_field_name(self):
        for query in ("*<o", "*>a", "*<=5", "*>=5", "*=a", "*:{* TO *}", "*:[a TO b]", "oak AND *<o", "*:oak",
                      "*:a*", '*:"a b"', "*:/a/", "*:(a b)", "*:a~"):
            self.assertProblem(query, "* is no field name: *:* matches all plants", "name:oak")
        for query in ("*:*", "*:* NOT robur", "*:*^2", "(*:*) AND soil:clay", "name:*", "zone_min:[* TO 5]",
                      "querc*"):
            self.assertIsNone(problem(query), query)

    def test_an_unknown_field_gets_a_suggestion(self):
        self.assertEqual(problem("color:red"), "unknown field color; did you mean flower_color?")
        self.assertProblem("colour:red", "unknown field colour", "flower_color")
        self.assertProblem("zone:5", "did you mean zone_min or zone_max?")
        self.assertProblem("orgin:europe", "did you mean origin?")
        self.assertProblem("edible:5", "edibility")
        self.assertProblem("soil:clay AND type:tree", "unknown field type", "plant_type")
        self.assertProblem("xyz:1", "unknown field xyz; the fields are name, common_name", "n_sources")

    def test_a_field_name_in_upper_case(self):
        self.assertEqual(problem("NAME:robur"), "field names are written in lower case: name, not NAME")
        self.assertProblem("SOIL:clay", "lower case: soil")
        self.assertProblem("quercus AND Year:1753", "lower case: year")

    def test_a_stored_field_cannot_be_searched(self):
        self.assertProblem("url:pfaf", "url is only stored", "cannot be searched", "source:pfaf")
        for field in ("wiki_title", "wiki_url", "wiki_match"):
            self.assertProblem(field + ":quercus", field + " is only stored")

    def test_a_number_field_takes_32_bit_whole_numbers(self):
        self.assertProblem("year:17abc", "year takes whole numbers, not 17abc",
                           "for example year:1753 or year:[1754 TO 1800]")
        self.assertProblem("height_max_cm:[* TO 1e3]", "height_max_cm takes whole numbers, not 1e3")
        self.assertProblem("density:[* TO 3000000000]", "3000000000 is too large for density",
                           "from -2147483648 to 2147483647")
        self.assertProblem("year:2147483648", "too large")
        self.assertProblem("year:[-2147483649 TO 0]", "-2147483649 is too small for year")
        self.assertProblem("zone_min:[\\-5 TO x]", "not x")
        self.assertProblem("year:1753.9", "not 1753.9")
        self.assertProblem("year:17*", "not 17*")
        self.assertProblem("year:*", "year:[* TO *]")
        self.assertProblem("year>17abc", "not 17abc")
        self.assertProblem('year:"17abc"', "not 17abc")
        self.assertProblem("year:/17.*/", "not a regular expression")
        self.assertProblem("year:(1753 OR 17abc)", "not 17abc")
        self.assertProblem('year:["1754" TO "18x"]', "not 18x")
        self.assertProblem("zone_min:[five TO 7]", "zone_min takes whole numbers", "zone_min:[* TO 5]")

    def test_to_in_lower_case(self):
        self.assertEqual(problem("year:[1700 to 1753]"), "TO in a range is written in capitals: year:[1700 TO 1753]")
        self.assertProblem("name:{a To c]", "name:{a TO c]")

    def test_the_first_problem_is_reported(self):
        self.assertProblem("color:red AND year:17abc", "color")


class NotesTest(unittest.TestCase):
    def test_good_queries_have_no_notes(self):
        for query in GOOD_QUERIES + search_docstring_examples():
            self.assertEqual(notes(query), [], query)

    def test_operators_not_in_capitals(self):
        found = notes("quercus not robur")
        self.assertEqual(found, ['"not" not written in capitals is no operator but a word (dropped as a stop word); '
                                 'operators are written in capitals: AND, OR, NOT'])
        # Tag fields keep their stop words: soil:(clay or loam) searches soil:or.
        self.assertIn("(searched in soil)", notes("soil:(clay or loam)")[0])
        self.assertIn('"and", "or" not written in capitals are no operators but words ("and" dropped as a stop '
                      'word; "or" searched in light)', notes("soil:clay and light:(shade or sun)")[0])
        self.assertIn('"Not" not written in capitals is no operator but a word (dropped as a stop word)',
                      notes("name:(quercus Not robur)")[0])

    def test_a_reversed_range_matches_nothing(self):
        found = notes("year:[1800 TO 1754]")
        self.assertEqual(len(found), 1)
        self.assertIn("year:[1800 TO 1754] matches nothing", found[0])
        self.assertIn("year:[1754 TO 1800]", found[0])
        self.assertIn("year:1800", notes("year:{1800 TO 1800]")[0])
        for query in ("year:[1754 TO 1800]", "year:[1800 TO 1800]", "zone_min:[* TO 5]", "name:[m TO a]"):
            self.assertEqual(notes(query), [], query)

    def test_only_negative_clauses_match_nothing(self):
        for query in ("NOT robur", "-robur", "!robur", "(NOT robur)", "-robur -quercus", "NOT robur AND NOT alba",
                      "NOT name:(robur OR alba)", "-soil:clay"):
            found = notes(query)
            self.assertEqual(len(found), 1, query)
            self.assertIn("matches nothing", found[0])
            self.assertIn("*:* " + query, found[0])
        self.assertIn("quercus NOT robur", notes("NOT robur")[0])


class SyntaxHintTest(unittest.TestCase):
    def test_good_queries_have_no_hint(self):
        for query in GOOD_QUERIES + search_docstring_examples():
            self.assertIsNone(syntax_hint(query), query)

    def test_recognised_causes(self):
        cases = {
            '"mountain laurel': 'a quote " is not closed',
            'name:"robur': 'a quote " is not closed',
            "year:[1754 TO": "a range is not closed",
            "year:[1754 TO 1800] OR year:[": "a range is not closed",
            "(quercus OR robur": "a parenthesis ( is not closed",
            "((quercus)": "a parenthesis ( is not closed",
            "quercus OR robur)": "a closing parenthesis ) has no opening one",
            "quercus]": "a closing bracket ] has no range",
            "*oak": "leading wildcard",
            "?oak": "leading wildcard",
            "name:*": "leading wildcard",
            "a/b": "regular expression that is not closed",
            "quercus\\": "backslash at the end",
            "year:[1754 1800]": "[low TO high]",
            "year:[TO 1800]": "[low TO high]",
            "quercus AND": "AND needs a clause after it",
            "AND quercus": "AND needs a clause on both sides",
            "quercus OR OR robur": "OR needs a clause on both sides",
            "(quercus OR)": "OR needs a clause after it",
            "NOT": "NOT needs a clause after it",
            "quercus -": "- needs a clause after it",
            "quercus^": "^ needs a number",
            "quercus^-1": "^ needs a number",
            "quercus@2": "@ follows a group",
            "name:": "needs a value",
            ":robur": "a field name goes before the colon",
        }
        for query, part in cases.items():
            hint = syntax_hint(query)
            self.assertIsNotNone(hint, query)
            self.assertIn(part, hint, query)
            self.assertNotIn("\n", hint)
        self.assertIn("*:*", syntax_hint("*oak"))

    def test_signs_after_a_field(self):
        self.assertEqual(syntax_hint("year:-1753"), "a negative number is written with a backslash, year:\\-1753, "
                                                    "or inside a range such as year:[-5 TO 0]")
        self.assertIn("zone_min<=\\-1", syntax_hint("zone_min<=-1"))
        self.assertEqual(syntax_hint("year:+1753"), "a number is written without +: year:1753")
        self.assertEqual(syntax_hint("name:-robur"), "- goes before the field name: -name:robur")
        self.assertEqual(syntax_hint("name:+robur"), "+ goes before the field name: +name:robur")


class PlainWordsTest(unittest.TestCase):
    def test_plant_names_are_plain_words(self):
        for query in ("acer palmatum", "Acer palmatum 'Seiryu'", "olearia × scilloniensis", "quercus",
                      "mountain laurel", "acer palmatum subsp. matsumurae", "hyacinthoides non-scripta",
                      "Sorbus aucuparia 'Joseph Rock'", "Abies borisii-regis", "Rosa 'Félicité Perpétue'",
                      "picea abies 'Nidiformis' 2", "quercus not robur", "  acer   palmatum  ", "non\\-scripta"):
            self.assertTrue(querycheck.plain_words(query), query)

    def test_query_syntax_is_no_plain_words(self):
        for query in ("quercus NOT robur", "quercus AND robur", "quercus OR robur", "quercus && robur",
                      "quercus || robur", '"mountain laurel"', "name:acer", "name : acer", "querc*", "quer?us",
                      "quercsu~", "quercsu~1", "-robur", "+quercus", "!robur", "quercus -robur", "oak^2", "(oak)",
                      "(quercus robur alba)@2", "year:[1754 TO 1800]", "{a TO b}", "text:/oak/", "/oak/", "*:*",
                      "year>1800", "a=b", '"mountain laurel', "quercus]", "quercus\\", "", "   "):
            self.assertFalse(querycheck.plain_words(query), query)


class ScanTest(unittest.TestCase):
    def test_tokens_follow_the_lucene_lexer(self):
        kinds = [(token.kind, token.text) for token in querycheck.scan('+name:"a b"~2 -x a-b a&&b && !y year>=5')]
        self.assertEqual(kinds, [("+", "+"), ("term", "name"), ("field", ":"), ("phrase", '"a b"'),
                                 ("modifier", "~2"), ("-", "-"), ("term", "x"), ("term", "a-b"), ("term", "a&&b"),
                                 ("and", "&&"), ("not", "!"), ("term", "y"), ("term", "year"), ("field", ">="),
                                 ("term", "5")])
        token = querycheck.scan('year:{1754 TO "1800"]')[-1]
        self.assertEqual((token.kind, token.items), ("range", ["1754", "TO", '"1800"']))

    def test_the_docstring_examples_are_found(self):
        examples = search_docstring_examples()
        self.assertGreaterEqual(len(examples), 20)
        self.assertIn("year:[1754 TO 1800]", examples)
        self.assertIn('"mountain laurel"~3', examples)
        self.assertNotIn("year:[1700 TO 1753]", examples)


if __name__ == "__main__":
    unittest.main()
