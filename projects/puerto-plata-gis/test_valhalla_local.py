import unittest
from valhalla_local import audit
class FakeActor:
 def route(self,r):
  assert r["costing"]=="bus"
  return {"trip":{"summary":{"length":4.2,"time":470}}}
class FakeError:
 def route(self,r):raise RuntimeError("No route")
features=[{"type":"Feature","properties":{"id":"C-test","terminal_start":[-70.70,19.80],"terminal_end":[-70.69,19.79]},"geometry":{"type":"MultiPoint","coordinates":[[-70.70,19.80],[-70.69,19.79]]}}]
class ValhallaLocalTests(unittest.TestCase):
 def test_round_trip_multpoint_cannot_replace_distinct_terminals(self):
  from valhalla_audit import pairs
  bad=[{"properties":{"id":"BAD"},"geometry":{"coordinates":[[-70.7,19.8],[-70.69,19.79],[-70.7,19.8]]}}]
  with self.assertRaises(ValueError):pairs(bad)
 def test_zero_distance_is_blocked(self):
  class ZeroActor:
   def route(self,r):return {"trip":{"summary":{"length":0.0,"time":0}}}
  row=audit(features,ZeroActor())["routes"][0]
  self.assertFalse(row["routed_both_directions"])
  self.assertEqual(row["turn_audit"][0]["status"],"BLOCKED")
 def test_local_actor_both_directions_and_no_false_approval(self):
  result=audit(features,FakeActor())
  row=result["routes"][0]
  self.assertTrue(row["routed_both_directions"])
  self.assertFalse(row["bus_geometry_validated"])
  self.assertEqual(row["inbound"]["distance_km"],4.2)
 def test_routing_error_does_not_approve(self):
  row=audit(features,FakeError())["routes"][0]
  self.assertFalse(row["routed_both_directions"])
  self.assertFalse(row["bus_geometry_validated"])
if __name__=="__main__":unittest.main()
