import unittest
from road_width_priorities import prioritize, TARGET

class PrioritiesTests(unittest.TestCase):
    def candidates(self):
        return [{"type":"Feature","properties":{"id":rid},
                 "geometry":{"type":"MultiPoint","coordinates":[[-70.7,19.8]]}} for rid in TARGET]
    def test_prioritize_unverified(self):
        crossing={"type":"Feature","properties":{"segment_id":"road1"},
                  "geometry":{"type":"LineString","coordinates":[[-70.70001,19.8],[-70.69999,19.8]]}}
        res=prioritize([crossing],self.candidates(),120)
        self.assertEqual(len(res["features"]),1)
        self.assertEqual(res["features"][0]["properties"]["matching_type"],"NEAR_PROVISIONAL_STOPS_ONLY")
        self.assertFalse(res["features"][0]["properties"]["bus_approved"])
    def test_missing_candidates_fails(self):
        with self.assertRaises(ValueError):prioritize([],self.candidates()[:-1])
    def test_away_from_stops_excluded(self):
        crossing={"type":"Feature","properties":{},"geometry":{"type":"LineString","coordinates":[[-70.71,19.8],[-70.709,19.8]]}}
        self.assertFalse(prioritize([crossing],self.candidates(),50)["features"])
if __name__=="__main__":unittest.main()
