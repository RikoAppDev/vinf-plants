# Test pages

Real pages saved by the crawler, used only to test the regex extractors.

| Folder / file | Source | Licence of the text |
|---|---|---|
| `ncsu_*.html` | [NC State Extension Gardener Plant Toolbox](https://plants.ces.ncsu.edu/) | © NC State University; two pages kept for testing, source cited |
| `pfaf/` | [Plants For A Future](https://pfaf.org/) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `tso/` | [Trees and Shrubs Online](https://www.treesandshrubsonline.org/), International Dendrology Society | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `wooddb/` | [The Wood Database](https://www.wood-database.com/) | All rights reserved – not included in the repository; the tests that need these pages are skipped |

The pages are unmodified copies of the HTML as downloaded in September and October 2026.

## Wikipedia pages (`wikipedia/`)

Eleven `<page>` elements copied byte for byte (from `<page>` to `</page>`) from the English
Wikipedia dump `enwiki-20261001-pages-articles.xml.bz2`, used only to test the regex parser
`wikipedia/wikitext.py`. The text is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); the authors are the Wikipedia
contributors, listed in the history of each page
(`https://en.wikipedia.org/w/index.php?title=TITLE&action=history`, linked below).

| File | Page (history) | Page id | Revision id | Case |
|---|---|---|---|---|
| `almond.xml` | [Almond](https://en.wikipedia.org/w/index.php?title=Almond&action=history) | 1064 | 1378634583 | Speciesbox, common-name title, `{{species list}}` synonyms |
| `kalmia_latifolia.xml` | [Kalmia latifolia](https://en.wikipedia.org/w/index.php?title=Kalmia_latifolia&action=history) | 17045 | 1372418116 | IUCN status, box without synonyms |
| `agapanthus_africanus.xml` | [Agapanthus africanus](https://en.wikipedia.org/w/index.php?title=Agapanthus_africanus&action=history) | 1543 | 1359646305 | `{{Plainlist}}` synonyms, two "Plants described in" years |
| `alder.xml` | [Alder](https://en.wikipedia.org/w/index.php?title=Alder&action=history) | 1383 | 1374183116 | Automatic taxobox of a genus |
| `olive_tree.xml` | [Olive tree](https://en.wikipedia.org/w/index.php?title=Olive_tree&action=history) | 44976 | 158444710 | Redirect to a plant article (Olive) |
| `northern_cavefish.xml` | [Northern cavefish](https://en.wikipedia.org/w/index.php?title=Northern_cavefish&action=history) | 1043 | 1318212112 | Animal with a Speciesbox |
| `quatorzain.xml` | [Quatorzain](https://en.wikipedia.org/w/index.php?title=Quatorzain&action=history) | 51671 | 1303588727 | Article without a box |
| `pseudotsuga_menziesii_var_glauca.xml` | [Pseudotsuga menziesii var. glauca](https://en.wikipedia.org/w/index.php?title=Pseudotsuga_menziesii_var._glauca&action=history) | 50692 | 1297899704 | Infraspeciesbox (variety) |
| `calamansi.xml` | [Calamansi](https://en.wikipedia.org/w/index.php?title=Calamansi&action=history) | 56624 | 1377214497 | Hybrid species (Citrus × microcarpa) |
| `phegopteris.xml` | [Phegopteris](https://en.wikipedia.org/w/index.php?title=Phegopteris&action=history) | 75284 | 1334239942 | Fern genus, `{{Genus list}}` synonyms |
| `ginkgoaceae.xml` | [Ginkgoaceae](https://en.wikipedia.org/w/index.php?title=Ginkgoaceae&action=history) | 67966 | 1357978787 | Plant family (rank above genus) |
