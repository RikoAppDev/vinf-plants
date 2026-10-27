# Manual

How to install the project, run the tests and search the plants. Searching does not need a
crawl: the index of all 18 125 plant records is attached to the
[GitHub release](https://github.com/RikoAppDev/vinf-plants/releases/tag/v1.0).

## 1. Requirements

* Python 3.12 (the tests also pass on 3.9)
* git
* about 50 MB of disk space for the index

## 2. Install

macOS and Linux:

```
git clone https://github.com/RikoAppDev/vinf-plants.git
cd vinf-plants
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```
git clone https://github.com/RikoAppDev/vinf-plants.git
cd vinf-plants
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` installs `requests` and `tiktoken`; `tiktoken` is only needed for the token
statistic. Every command below is run from the `vinf-plants` folder with the virtual
environment active.

## 3. Run the tests

```
python -m unittest discover -s tests -t .
```

Expected result in a fresh clone:

```
Ran 242 tests in 0.2s

OK (skipped=34)
```

The 34 skipped tests belong to the Wood Database extractor. Its pages are under "all rights
reserved", so they are not in this repository; the ZIP submitted on the course wiki contains
them, and there all 242 tests pass. One test file with the name of every test:

```
python -m unittest tests.test_pfaf_extractor -v
```

| File | Tests | What is checked |
|---|---|---|
| `test_pfaf_extractor.py` | 47 | extractor on 20 saved PFAF pages, values checked by hand in the HTML |
| `test_tso_extractor.py` | 50 | extractor on 25 saved Trees and Shrubs Online pages |
| `test_wooddb_extractor.py` | 40 | extractor on 20 saved Wood Database pages (34 skipped without the pages) |
| `test_ncsu_extractor.py` | 12 | extractor on 2 saved NCSU pages |
| `test_indexer.py` | 31 | tokenizer, idf and scores computed by hand, index files, worked tf-idf example |
| `test_crawler.py` | 29 | crawler with a fake HTTP session: frontier, retries, robots.txt, URL rules |
| `test_links.py` | 12 | link and sitemap regular expressions, URL normalisation |
| `test_normalize.py` | 8 | family name typos are fixed, different families are not merged |
| `test_merge_entities.py` | 7 | entity key, merging through a listed synonym |
| `test_build_viewer.py` | 6 | offline HTML viewer of the records |

## 4. Download the index

```
curl -L -o vinf-plants-index.zip https://github.com/RikoAppDev/vinf-plants/releases/download/v1.0/vinf-plants-index.zip
python -m zipfile -e vinf-plants-index.zip .
```

On Windows write `curl.exe` instead of `curl`. The file can also be downloaded from the release
page by hand and unpacked into the `vinf-plants` folder.

This creates `data/index/` (36 MB):

| File | Content |
|---|---|
| `postings.tsv` | one line per term: term, df, postings `doc_id:tf` |
| `docs.tsv` | one line per document: id, site, URL, scientific name, length, highest tf |
| `norms.tsv` | Euclidean length of every document vector, for each tf variant |
| `meta.json` | N, vocabulary size, build time and options |

The index holds term counts, plant names and URLs, not the text of the pages.

## 5. Search

```
python -m indexer.search "drought tolerant groundcover full sun"
```

```
python -m indexer.search "drought tolerant groundcover full sun" --idf smooth --top 5
index N=18125, 116729 terms, loaded in 0.07 s, query answered in 0.011 s
weights: document tf=log (norm=cosine), query count x idf=smooth
  drought              df=3663   idf=0.7744
  tolerant             df=3520   idf=0.7888
  groundcover          df=571    idf=1.5151
  full                 df=11643  idf=0.4077
  sun                  df=11322  idf=0.4151
  1  0.3323  ncsu    Paronychia kapela                        https://plants.ces.ncsu.edu/plants/paronychia-kapela/
  2  0.3268  ncsu    Trachelospermum asiaticum                https://plants.ces.ncsu.edu/plants/trachelospermum-asiaticum/
  3  0.3179  ncsu    Alternanthera ficoidea                   https://plants.ces.ncsu.edu/plants/alternanthera-ficoidea/
  4  0.3086  ncsu    Waldsteinia ternata                      https://plants.ces.ncsu.edu/plants/waldsteinia-ternata/
  5  0.3054  ncsu    Juniperus x pfitzeriana 'Old Gold'       https://plants.ces.ncsu.edu/plants/juniperus-x-pfitzeriana-old-gold/
```

The output lists df and idf of every query term, then rank, score, site, scientific name and
the URL of the source page.

| Option | Values | Default | Meaning |
|---|---|---|---|
| `--idf` | `classic`, `smooth`, `none` | `classic` | log10(N/df), log10(1 + N/df), or no idf |
| `--tf` | `log`, `raw`, `maxnorm` | `log` | 1 + log10(tf), tf, or 0.5 + 0.5 · tf / max tf |
| `--norm` | `cosine`, `none` | `cosine` | divide by the document vector length, or not |
| `--top` | number | `10` | number of results |
| `--source` | `ncsu`, `pfaf`, `tso`, `wooddb` | all | show results of one site only |

More queries to try:

```
python -m indexer.search "quercus robur"
python -m indexer.search "wood density janka hardness oak" --idf none
python -m indexer.search "edible fruit tree" --source pfaf
python -m indexer.search "shade tolerant evergreen hedge" --norm none
```

## 6. Compare the idf methods

```
python -m indexer.compare
```

For each of five fixed queries it prints df and idf of the query terms, the top 5 of every idf
method, and how much the top 10 lists agree (overlap and Spearman's rho), then the mean over all
queries. The same tables are written to `data/index/idf_comparison.md`, which every run
overwrites. Own queries:

```
python -m indexer.compare --query "edible fruit tree" --query "quercus robur"
```

## 7. Build everything from the websites (optional)

The index in step 4 was built with the commands below. The crawl is slow on purpose: one
request at a time with a pause of 1 to 10 s per site, so the pauses alone take about 2 h (NCSU),
9 h (PFAF), 16 h (Trees and Shrubs Online) and 1 h (Wood Database). Each site can run in its own
terminal, and an interrupted crawl continues where it stopped.

| Step | Command | Output |
|---|---|---|
| crawl | `python -m crawler.crawl --site ncsu` (also `pfaf`, `tso`, `wooddb`) | `data/raw/<site>/`, `data/state/<site>/crawl_log.tsv`, `discovered.tsv` |
| extract | `python -m extractor.run --site all` | `data/extracted/<site>_plants.jsonl` and `.tsv` |
| merge | `python -m tools.merge_entities` | `data/extracted/entities.jsonl`, `entities_stats.md` |
| index | `python -m indexer.build` (about 6 s) | `data/index/` |
| statistics | `python -m tools.all_stats --tokens` | `data/stats/<site>.txt` |
| field coverage | `python -m tools.coverage` | `data/stats/coverage.md` |

`python -m crawler.crawl --site ncsu --max-pages 20` stops after 20 pages, for a short try.
`python -m extractor.run --site all` skips sites that were not crawled.
`python -m tools.pipeline` runs extraction, merging, index build, idf comparison and coverage
one after another.

## 8. Troubleshooting

| Message | Fix |
|---|---|
| `no complete index in data/index (run python -m indexer.build)` | the index is not unpacked; repeat step 4 in the `vinf-plants` folder |
| `No module named 'indexer'` (or `crawler`, `extractor`) | run the command from the `vinf-plants` folder, or from anywhere as `python tools/run_module.py indexer.search "..."` |
| `No module named 'requests'` | the virtual environment is not active; activate it or call `.venv/bin/python` (Windows `.venv\Scripts\python`) |
| PowerShell refuses to run `Activate.ps1` | call `.venv\Scripts\python -m ...` directly without activating |
