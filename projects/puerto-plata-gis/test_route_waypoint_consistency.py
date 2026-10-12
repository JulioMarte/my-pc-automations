import unittest
from route_waypoint_consistency import audit,distance_to_segments

class WaypointTests(unittest.TestCase):
 def test_deviation_detected(self):
  paths={"features":[{"properties":{"candidate":"C-test","direction":d},"geometry":{"coordinates":[[-70.7,19.8],[-70.69,19.8]]}} for d in ("outbound","inbound")]}
  candidates={"features":[{"properties":{"id":"C-test"},"geometry":{"type":"MultiPoint","coordinates":[[-70.7,19.8],[-70.695,19.81]]}}]}
  x=audit(candidates,paths)
  self.assertEqual(x["routes_with_waypoint_deviation"],["C-test"])
  self.assertFalse(x["bus_stop_accessibility_verified"])
 def test_nearby_point(self):
  d=distance_to_segments([-70.695,19.8],[[-70.7,19.8],[-70.69,19.8]])
  self.assertAlmostEqual(d,0,delta=.1)
 def test_missing_shape_blocked(self):
  candidates={"features":[{"properties":{"id":"C"},"geometry":{"type":"MultiPoint","coordinates":[[-70.7,19.8]]}}]}
  x=audit(candidates,{"features":[]})
  self.assertIn("C",x["routes_with_waypoint_deviation"])
if __name__=="__main__":unittest.main()
