# vinf-plants

Search over trees and ornamental plants by their properties. A course project for
Information Retrieval (VINF) at FIIT STU, 2026/27.

The project crawls plant pages from four botanical websites, extracts plant records with
regular expressions, merges records of the same plant from different sites and searches them
with its own inverted index. The extraction and the merge also run on Apache Spark, which joins
the plants with the English Wikipedia dump. A later part moves the index to PyLucene.

The crawler, extractors and index use only `requests` and the Python standard library; the
Spark jobs use PySpark. There is no database, no pandas, no NLTK, no XPath or DOM-based
extraction (also not for Wikipedia), no crawling framework and no search library. `tiktoken` is
optional and only used for a token count.

## Sources

| Site | Plant pages | Records | Extracted, for example | Licence of the text |
|---|---|---|---|---|
| [NC State Extension Gardener Plant Toolbox](https://plants.ces.ncsu.edu/) | 4 703 | 4 703 | names, family, height and width, USDA zone, light, soil, description | © NC State University |
| [Plants For A Future](https://pfaf.org/) | 7 172 | 7 151 | authority, synonyms, zone, habit, edibility and medicinal rating, uses, soil, pH | CC BY 4.0 |
| [Trees and Shrubs Online](https://www.treesandshrubsonline.org/) | 5 705 | 5 705 | authority, synonyms, distribution, zone, RHS rating, IUCN status, full article | CC BY-SA 4.0 |
| [The Wood Database](https://www.wood-database.com/) | 589 | 566 | wood density, Janka hardness, strength, shrinkage, IUCN and CITES, uses | all rights reserved |

Pages without a plant (empty pages, wood figure or trade-name pages) are skipped by the
extractors. After merging, the 18 125 records describe 14 199 distinct plants; 163 of them
are on all four sites. The crawled pages (1.33 GB) are not part of this repository. Counted
with `tiktoken` (`cl100k_base`), the raw HTML of the plant pages has 419.3 M tokens and the
text of the extracted records 26.4 M.

## Architecture

![Architecture of the crawler, extractors, record merging and index](docs/architecture.png)

## Setup

Step-by-step instructions, including a ready-made index for searching without a crawl, are in
[MANUAL.md](MANUAL.md). Short version with `uv`:

```
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
```

## Usage

```
python -m crawler.crawl --site ncsu                  # ncsu | pfaf | tso | wooddb; run again to resume
python -m crawler.crawl --site pfaf --reseed         # read the sitemap again, queue only new URLs
python -m extractor.run --site all                   # one site or all
python -m tools.merge_entities
python -m indexer.build
python -m indexer.search "drought tolerant shrub full sun" --idf smooth --top 10
python -m indexer.compare                            # idf methods side by side
python -m tools.all_stats --tokens                   # crawl statistics of every site
python -m tools.coverage                             # field coverage of the records
python -m tools.pipeline                             # extract, merge, index, compare, coverage in one run
python -m unittest discover -s tests -t .
```

`tools/run_module.py` runs any of these modules from another working directory, for example
from an IDE run configuration.

Spark jobs, in the course Docker image `iisas/hadoop-spark-pig-hive:2.9.2` (see
[MANUAL.md](MANUAL.md), section 8):

```
./spark_docker.sh sparkjobs.extract_sites            # extraction on Spark
./spark_docker.sh sparkjobs.merge_entities           # entity merge on Spark
./spark_docker.sh sparkjobs.compare                  # both equal the single-process output
./spark_docker.sh sparkjobs.wiki_pages               # plant pages out of the Wikipedia dump
./spark_docker.sh sparkjobs.join_wiki                # entities joined with Wikipedia
```

## Crawler

* Seeds come from each site's sitemap. The frontier is a FIFO queue (breadth-first); every
  new URL is appended to `discovered.tsv` at once, and a set of seen URLs prevents duplicates.
* An allow pattern per site lets only plant pages through. Faceted search URLs on NCSU are a
  crawler trap and are never queued; alias pages under another name are near-duplicates.
* robots.txt is fetched on every run and obeyed; a larger `Crawl-delay` wins. As in RFC 9309,
  4xx means no rules, 5xx, 429 or a network error stops the run, and an HTML page instead of
  robots.txt is treated as an anti-bot page. The file in force is kept in the state folder.
* Requests send a browser User-Agent (Chrome) followed by the crawler's own token
  `VINF-FIIT-STU-crawler/0.1`; robots.txt groups are matched against that token.
* One request at a time per site, pause 1 s (ncsu), 4 s (pfaf), 6 s (wooddb) or 10 s (tso)
  plus up to 0.5 s of random jitter. Each site runs in its own process.
* Timeouts 10 s to connect and 30 s to read. Up to 3 attempts for network errors, 429 and 5xx,
  with backoff or the server's `Retry-After` (at most 5 minutes).
* The crawl stops after 5 blocked answers (403, 429, 503) in a row or at the first anti-bot page.
* Raw response bodies go to `data/raw/<site>/`; one metadata row per request goes to
  `crawl_log.tsv`. State files are append-only and flushed after every line, so an
  interrupted crawl continues where it stopped.

`crawl_log.tsv` columns: `fetched_at_utc, url, final_url, status, content_type, bytes, sha256,
elapsed_ms, attempts, depth, referrer, file, error`.

| status | meaning | fetched again on the next run |
|---|---|---|
| HTTP code, e.g. `200`, `404` | server answer; only `200` is stored | only `401`, `403`, `429` and `5xx` |
| empty | network error after all attempts | yes |
| `challenge` | anti-bot page instead of content | yes |
| `robots` | disallowed by robots.txt, no request made | yes |
| `redirect-duplicate` | redirected to another allowed page, which is stored once under its own URL | no |
| `redirect-outside` | redirected outside the allowed URLs | no |

## Extraction

One module per site in `extractor/`. Patterns are anchored on the labels printed on the page
(`Family:`, `Janka Hardness:`, `USDA Hardiness Zone`) rather than on the position of an
element, so a layout change that keeps the labels does not break them. Where a page has no
label for a region, a single id or class marks the region and the reason is noted in the code.
Values are never guessed: a missing value is `None`.

Every record has the same core fields (`scientific_name`, `authority`, `family`, `genus`,
`common_names`, `synonyms`, `zone_min`, `zone_max`, `height_min_cm`, `height_max_cm`,
`description`, `attributes`) plus fields of its site (ratings, wood properties, conservation
status). Family names typed by hand on the sites ("Roseaceae", "Rosacea") are unified when the
error is in the -aceae ending (`extractor/normalize.py`).

## Merging records

`tools/merge_entities.py` gives every record a key: the lower-cased binomial plus any
qualifier after it (variety, cultivar, cultivar group), with both hybrid spellings unified.
Records with the same key are one plant. A synonym listed on a page joins the page to the
record of that name on another site (e.g. *Feijoa sellowiana* and *Acca sellowiana*); two
different pages of the same site are never merged.

## Index and search

* A document is one record. Its text is the names (each token counted 3×), family, genus,
  description and attribute values; text already present in another field is not counted twice.
* Tokens: regex, lower case, hyphenated words and decimals kept whole, 141 English stop
  words removed, no stemming or lemmatisation.
* The index is built once from all records and stores tf per document (`postings.tsv`), the
  document table and the document vector lengths. idf is computed at query time from df and N,
  so all idf methods share one index.
* Score: document weight `1 + log10(tf)`, document vector normalised to Euclidean length 1;
  query weight `count × idf`; score = sum of products.
* idf methods: `classic` log10(N/df), `smooth` log10(1 + N/df), `none` 1 (baseline).
  Probabilistic idf and BM25 are not used.

Index of all four sites: 18 125 documents, 116 729 terms, 4.35 M postings, 36 MB, built in
about 6 s; a query takes a few milliseconds. The built index is attached to the
[v1.0 release](https://github.com/RikoAppDev/vinf-plants/releases/tag/v1.0), so search runs
without a crawl (see [MANUAL.md](MANUAL.md)).

## Spark and Wikipedia

All Spark jobs run with `spark-submit` in the course image `iisas/hadoop-spark-pig-hive:2.9.2`
(Spark 2.4.3, Java 8, Python 3.6) through `spark_docker.sh`, and also on Spark 4.

* `extract_sites` and `merge_entities` run the extractors and the merge of the first part in the
  executors (only the union-find over the 966 synonym edges runs on the driver). `compare`
  checks that the 18 125 records and 14 199 entities equal the single-process output, line by line.
* `wiki_pages` reads the dump `enwiki-20261001-pages-articles.xml.bz2` (25.8 GB) with
  `</page>` as the record delimiter of Hadoop's `TextInputFormat`, so every record is one page;
  bzip2 is splittable, so the file is read in 769 parallel input splits of 32 MB. Hadoop 2.9 in
  the course image reads a record twice when a split ends inside the delimiter (HADOOP-18321);
  the job counts such a record once and keeps every page once. Each page goes through the regex parser `wikipedia/wikitext.py` (title, redirect,
  taxobox with genus, species, authority, IUCN status and synonyms, categories, common names,
  lead). Of 25.9 M pages (7.2 M articles, 12.1 M redirects, 501 310 articles with a taxobox) it
  keeps 51 091 articles and 4 088 redirects that can belong to our plants, including the plant
  articles in other genera that a redirect from one of our names leads to.
* `join_wiki` joins entities and pages on the entity key of the merge. An entity is looked up by
  its own name and aliases, then by the species of a cultivar, then by its genus; a page is found
  by the Latin name in its taxobox, its title, a redirect, the name without the hybrid sign,
  another ending of the epithet, or a taxobox synonym of the same genus and author. The genus
  fallback lands only on an article about a plant genus, and a species name that leads to a
  genus or section article counts as that fallback.

| Joined to | Entities |
|---|---|
| an article about the plant or its species | 10 042 (70.7 %) |
| the genus article, for entities that are a genus | 314 (2.2 %) |
| only the genus article (fallback) | 3 781 (26.6 %) |
| nothing | 62 (0.4 %) |

9 777 distinct Wikipedia articles are joined, 8 746 of them about a plant or its species. Of the
entities joined to such an article, 99.9 % get an authority, 61.5 % the year of description,
31.6 % an IUCN status, 63.0 % synonyms and 83.2 % common names. In the course image the page
selection takes 13 min, the join 17 s.

## Tests

`python -m unittest discover -s tests -t .` runs the unit tests: extractors on saved real
pages with values checked by hand (`tests/fixtures/`, see its README for sources and licences),
the crawler with a fake HTTP session, name normalisation, record merging and the indexer,
including scores computed by hand, the Wikipedia parser on saved dump pages and the Spark jobs.
There are 434 tests; in a fresh clone 34 Wood Database tests are skipped (the pages are not
distributed) and 4 Spark end-to-end tests are skipped unless PySpark and Java are available.

## Layout

| Path | Content |
|---|---|
| `crawler/` | `crawl.py` loop and CLI, `config.py` per-site rules, `frontier.py`, `links.py`, `robots.py`, `storage.py` |
| `extractor/` | `ncsu.py`, `pfaf.py`, `tso.py`, `wooddb.py`, `normalize.py`, `run.py` |
| `indexer/` | `tokenize.py`, `build.py`, `search.py`, `weighting.py`, `compare.py`, `stopwords_en.txt` |
| `tools/` | statistics, field coverage, record merging, offline HTML viewer of the records |
| `sparkjobs/` | Spark jobs: `extract_sites.py`, `merge_entities.py`, `compare.py`, `wiki_pages.py`, `join_wiki.py`, shared `session.py` |
| `wikipedia/` | `wikitext.py`, regex parser of one page of the Wikipedia dump |
| `spark_docker.sh` | runs a Spark job with `spark-submit` in the course Docker image |
| `tests/` | unit tests and saved test pages |
| `docs/` | architecture diagram |
| `data/` | crawled pages, crawl state, records and index (created by the commands above, not in git) |
