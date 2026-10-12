import unittest
from imagery_eligibility import gate,evaluate

class ImageryTests(unittest.TestCase):
    def test_unverified_source_is_blocked(self):
        x=evaluate({"id":"x","url":"https://example.org/img.tif"})
        self.assertFalse(x["eligible_for_pilot"])
        self.assertIn("MEASUREMENT_RIGHTS_UNCONFIRMED",x["blockers"])
    def test_declared_metadata_is_only_provisional(self):
        x=evaluate(dict(id="x",local_path="img.tif",measurement_rights_confirmed=True,
                        coverage_intersects_puerto_plata=True,acquired_at="2026-01-01",
                        georeferenced=True,crs="EPSG:32619",gsd_m=.2,horizontal_accuracy_m=.4))
        self.assertTrue(x["eligible_for_pilot"])
        self.assertIn("metadata-only",x["accuracy_claim"])
    def test_falsely_precise_imagery_is_blocked(self):
        x=evaluate(dict(id="bad",local_path="img",measurement_rights_confirmed=True,
                        coverage_intersects_puerto_plata=True,acquired_at="2026",
                        georeferenced=True,crs="EPSG:32619",gsd_m=2.0,horizontal_accuracy_m=1.0))
        self.assertFalse(x["eligible_for_pilot"])
    def test_empty_catalog_cannot_enable_measurements(self):
        self.assertEqual(gate([])["status"],"BLOCKED_NO_ELIGIBLE_IMAGERY")
if __name__=="__main__":unittest.main()
