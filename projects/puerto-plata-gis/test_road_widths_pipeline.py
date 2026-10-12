"""Regression tests for road width measurements and fail-closed planning."""
import unittest
from road_widths_pipeline import width_between, validate_sample, inventory, build_report

class RoadWidthsTests(unittest.TestCase):
    def sample(self):
        return dict(segment_id="osm:12",left_lon=-70.7,left_lat=19.8,
                    right_lon=-70.69995,right_lat=19.8,source="field:001",
                    source_date="2026-10-11",source_license="owned",
                    review_status="field_measured",uncertainty_m=0.1)

    def test_known_metric_width(self):
        self.assertAlmostEqual(width_between((-70.7,19.8),(-70.69995,19.8)),5.23,delta=0.1)

    def test_approved_vehicle_is_never_claimed(self):
        report=build_report([], [self.sample()], [])
        self.assertFalse(report["geometry_approved"])
        self.assertFalse(report["measurements"][0]["accepted_for_bus"])

    def test_missing_source_rejected(self):
        s=self.sample()
        del s["source_license"]
        with self.assertRaises(ValueError): validate_sample(s)

    def test_invalid_coordinate_rejected(self):
        s=self.sample()
        s["left_lat"]=float("nan")
        with self.assertRaises(ValueError): validate_sample(s)

    def test_field_requires_uncertainty(self):
        s=self.sample()
        s["uncertainty_m"]=None
        with self.assertRaises(ValueError): validate_sample(s)

    def test_width_and_est_width_distinct(self):
        r=inventory([{"geometry":{"type":"LineString","coordinates":[]},"properties":{"width":"6.5"}},
                     {"geometry":{"type":"LineString","coordinates":[]},"properties":{"est_width":"5.0","maxwidth":"2.5"}}])
        self.assertEqual(r["tag_counts"]["width"],1)
        self.assertEqual(r["tag_counts"]["est_width"],1)
        self.assertEqual(r["tag_counts"]["unknown"],1)

    def test_empty_sources_do_not_create_widths(self):
        report=build_report([],[],[])
        self.assertEqual(report["measurements"],[])
        self.assertEqual(report["status"],"NO_MEASUREMENTS_LICENSED_OR_REVIEWED")

    def test_duplicate_samples_rejected(self):
        with self.assertRaises(ValueError): build_report([], [self.sample(),self.sample()],[])

if __name__=="__main__":unittest.main()
