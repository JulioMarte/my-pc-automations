import unittest
from survey_priority_queue import inspect_queue, distance_m

def turn(candidate, lon=-70.7, lat=19.8, angle=90):
    return {"candidate": candidate, "longitude":lon, "latitude":lat,
            "heading_change_deg":angle}

def report(turns):
    return {"status":"EXPLORATORIO_SIN_APROBACION_FISICA", "risks":turns}

def section(lon=-70.7,lat=19.8):
    return {"type":"Feature",
            "geometry":{"type":"LineString","coordinates":[[lon-0.00001,lat],[lon+0.00001,lat]]},
            "properties":{"segment_id":"osm-edge:123","status":"INSPECTION_TRANSECT_NOT_MEASURED"}}

class SurveyPriorityQueueTests(unittest.TestCase):
    def test_collects_nearby_profiles_without_approval(self):
        result=inspect_queue(report([turn("C00-10")]),{"features":[section()]})
        self.assertEqual(result["total_tasks"],1)
        self.assertEqual(result["tasks_by_route"]["C00-10"],1)
        self.assertEqual(result["risks"][0]["nearby_unmeasured_profiles"],1)
        self.assertEqual(result["risks"][0]["physical_turn_status"],"NOT_ASSESSED")
        self.assertEqual(result["street_widths_measured"],0)
        self.assertEqual(result["maneuvers_approved"],0)

    def test_distant_profiles_stay_unknown(self):
        far=section(lon=-70.71)
        result=inspect_queue(report([turn("C00-09")]),{"features":[far]})
        self.assertEqual(result["risks"][0]["nearby_unmeasured_profiles"],0)
        self.assertEqual(result["risks"][0]["road_width_status"],"UNKNOWN")

    def test_non_selected_route_filtered(self):
        result=inspect_queue(report([turn("L1")]),{"features":[section()]})
        self.assertEqual(result["total_tasks"],0)

    def test_requires_unapproved_evidence(self):
        with self.assertRaises(ValueError):
            inspect_queue({"status":"APROBADO","risks":[]},{"features":[]})

    def test_local_distance(self):
        self.assertAlmostEqual(distance_m(-70.7,19.8,-70.7,19.8),0)
        self.assertGreater(distance_m(-70.7,19.8,-70.701,19.8),100)

if __name__ == "__main__":
    unittest.main()
