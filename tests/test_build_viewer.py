import json
import os
import tempfile
import unittest

from crawler import config
from tools import build_viewer


class BuildViewerTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"url": "https://plants.ces.ncsu.edu/plants/quercus-alba/", "scientific_name": "Quercus alba",
             "common_names": ["White Oak </script> tag"], "synonyms": [], "genus": "Quercus", "species": "alba",
             "family": "Fagaceae", "height_min_cm": 1524, "height_max_cm": 4115, "width_min_cm": 1524,
             "width_max_cm": 2438, "zone_min": 3, "zone_max": 9,
             "attributes": {"Family": ["Fagaceae"], "Plant Type": ["Tree"], "Soil pH": ["Acid"],
                            "Description": ["Long text with </script> inside"]}},
            {"url": "https://plants.ces.ncsu.edu/plants/acer/", "scientific_name": "Acer",
             "common_names": [], "synonyms": [], "genus": "Acer", "species": "", "family": "Sapindaceae",
             "height_min_cm": None, "height_max_cm": None, "width_min_cm": None, "width_max_cm": None,
             "zone_min": None, "zone_max": None, "attributes": {"Family": ["Sapindaceae"]}},
        ]
        self.site = config.SITES["ncsu"]

    def test_meta_counts_and_chunking(self):
        meta = build_viewer.build_meta(self.records, self.site, "24 Sep 2026")
        self.assertEqual((meta["count"], meta["families"], meta["genera"]), (2, 2, 2))
        self.assertEqual(meta["median_attributes"], 2)
        self.assertEqual(meta["raw_dir"], "../raw/ncsu/")
        self.assertEqual((meta["chunk_size"], meta["chunk_count"]), (build_viewer.CHUNK_SIZE, 1))
        self.assertEqual(meta["facets"][0], {"key": "Plant Type", "label": "Plant type"})

    def test_light_record_keeps_list_fields_and_drops_descriptions(self):
        light = build_viewer.light_record(self.records[0])
        self.assertEqual(light["facets"], {"Plant Type": ["Tree"], "Soil pH": ["Acid"]})
        self.assertEqual(light["attr_count"], 4)
        self.assertNotIn("attributes", light)
        self.assertRegex(light["file"], r"^plants_quercus-alba__[0-9a-f]{10}\.html$")

    def test_embedded_json_cannot_close_the_script_element(self):
        html = build_viewer.build_html("<script>__PLANT_DATA__</script><script>__PLANT_META__</script>",
                                       self.records, {"site": "ncsu"})
        self.assertEqual(html.count("</script>"), 2)
        embedded = html[len("<script>"):html.index("</script>")]
        self.assertEqual(json.loads(embedded)[0]["common_names"], ["White Oak </script> tag"])

    def test_chunk_file_carries_full_attributes(self):
        js = build_viewer.chunk_js(0, self.records)
        self.assertTrue(js.startswith("window.__plantChunk(0, ["))
        payload = json.loads(js[len("window.__plantChunk(0, "):js.rindex(")")])
        self.assertEqual(payload[0]["Description"], ["Long text with </script> inside"])
        self.assertEqual(payload[1], {"Family": ["Sapindaceae"]})

    def test_write_viewer_produces_index_and_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            meta = build_viewer.build_meta(self.records, self.site, "24 Sep 2026")
            index = build_viewer.write_viewer("__PLANT_DATA____PLANT_META__", self.records, meta, folder)
            self.assertTrue(os.path.exists(index))
            self.assertEqual(sorted(os.listdir(os.path.join(folder, "chunks"))), ["000.js"])

    def test_load_records_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "x.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(self.records[0]) + "\n\n" + json.dumps(self.records[1]) + "\n")
            self.assertEqual(len(build_viewer.load_records(path)), 2)


if __name__ == "__main__":
    unittest.main()
