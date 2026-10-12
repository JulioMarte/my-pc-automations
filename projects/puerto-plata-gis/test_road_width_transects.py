"""Regression tests for road centerline inspection transects."""
import unittest
from road_width_transects import transects

class TransectTests(unittest.TestCase):
    def test_samples_do_not_claim_road_width(self):
        roads=[{"type":"Feature","properties":{"osmid":"42"},"geometry":{"type":"LineString","coordinates":[[-70.70,19.8],[-70.699,19.8]]}}]
        result=transects(roads,10,15)
        self.assertGreater(len(result["features"]),5)
        self.assertEqual(result["features"][0]["properties"]["status"],"INSPECTION_TRANSECT_NOT_MEASURED")
        self.assertEqual(result["features"][0]["properties"]["segment_id"],"42")

    def test_zero_length_and_non_line_ignored(self):
        x=[{"geometry":{"type":"LineString","coordinates":[[0,0],[0,0]]},"properties":{}},
           {"geometry":{"type":"Point","coordinates":[0,0]},"properties":{}}]
        self.assertEqual(transects(x)["features"],[])

    def test_size_limits(self):
        with self.assertRaises(ValueError):transects([],0,15)
        roads=[{"geometry":{"type":"LineString","coordinates":[[0,0],[0.01,0]]},"properties":{}}]
        with self.assertRaises(ValueError):transects(roads,1,15,3)

if __name__=="__main__":unittest.main()
