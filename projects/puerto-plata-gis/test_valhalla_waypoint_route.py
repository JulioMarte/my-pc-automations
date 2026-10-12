import unittest
from valhalla_waypoint_route import route_waypoints,to_geojson
from valhalla_route_shape import encode_test_polyline6

TARGET=("C00-09","C00-10","C02-04")
def data():
 return [{"type":"Feature","properties":{"id":rid},
          "geometry":{"type":"MultiPoint","coordinates":[[-70.7,19.8],[-70.695,19.8],[-70.69,19.8]]}}
          for rid in TARGET]
class Actor:
 def route(self,req):
  a=req["locations"][0];b=req["locations"][1]
  points=[[a["lon"],a["lat"]],[b["lon"],b["lat"]]]
  return {"trip":{"summary":{"length":0.6,"time":70},
                  "legs":[{"shape":encode_test_polyline6(points)}]}}
class Failure:
 def route(self,req):raise RuntimeError("No route")
class Tests(unittest.TestCase):
 def test_complete_shortlist(self):
  report=route_waypoints(data(),Actor())
  self.assertEqual(report["complete_routes"],3)
  self.assertEqual(len(to_geojson(report)["features"]),3)
  self.assertFalse(report["routes"][0]["physical_bus_geometry_approved"])
  self.assertFalse(report["routes"][0]["route_distance_is_round_trip"])
  self.assertFalse(report["routes"][0]["validated_service_cycle"])
  self.assertGreater(report["routes"][0]["endpoints"]["distance_between_ends_m"],100)
 def test_missing_segments_block(self):
  report=route_waypoints(data(),Failure())
  self.assertEqual(report["complete_routes"],0)
  self.assertIsNone(report["routes"][0]["sum_segment_distance_km"])
 def test_duplicate_skip(self):
  f=data()
  for item in f:item["geometry"]["coordinates"].insert(1,[-70.7,19.8])
  report=route_waypoints(f,Actor())
  self.assertEqual(report["routes"][0]["segments"][0]["status"],"DUPLICATE_WAYPOINT_SKIPPED")
if __name__=="__main__":unittest.main()
