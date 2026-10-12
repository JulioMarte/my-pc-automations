import unittest
from valhalla_local import audit
class FakeActor:
 def route(self,r):
  assert r["costing"]=="bus"
  return {"trip":{"summary":{"length":4.2,"time":470}}}
class FakeError:
 def route(self,r):raise RuntimeError("No route")
features=[{"type":"Feature","properties":{"id":"C-test"},"geometry":{"type":"MultiPoint","coordinates":[[-70.70,19.80],[-70.69,19.79]]}}]
class ValhallaLocalTests(unittest.TestCase):
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
