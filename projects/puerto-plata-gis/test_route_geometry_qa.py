import unittest
from route_geometry_qa import summarize

class ShapeQATests(unittest.TestCase):
 def test_paired_shapes_exported_not_approved(self):
  coords=[[-70.7,19.8],[-70.69,19.79]]
  leg={"status":"routed","distance_km":2.4,"time_seconds":300,"road_shape":{"status":"ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH","geometry":{"coordinates":coords}}}
  a,geo=summarize({"routes":[{"id":"test","outbound":leg,"inbound":leg}]})
  self.assertEqual(a["routes_with_both_shapes"],1)
  self.assertEqual(len(geo["features"]),2)
  self.assertEqual(a["bus_turns_approved"],0)
 def test_missing_shape_remains_blocked(self):
  a,geo=summarize({"routes":[{"id":"bad","outbound":{"status":"routed"},"inbound":{"status":"error"}}]})
  self.assertEqual(a["routes_with_both_shapes"],0)
  self.assertEqual(len(geo["features"]),0)
if __name__=="__main__": unittest.main()
