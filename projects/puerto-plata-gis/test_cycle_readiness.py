import unittest
from cycle_readiness import audit

class ReadinessTests(unittest.TestCase):
 def test_closed_still_not_approved(self):
  x=audit({"routes":[{"id":"C00-09","complete_routable_sequence":True,
      "endpoints":{"distance_between_ends_m":3},"sum_segment_distance_km":7.5}]})
  self.assertEqual(x["approved_as_measured_cycles"],0)
  self.assertTrue(x["routes"][0]["geometrically_closed"])
  self.assertFalse(x["routes"][0]["vehicle_cycle_validated"])
 def test_open_endpoint_detected(self):
  x=audit({"routes":[{"id":"C00-10","complete_routable_sequence":True,
      "endpoints":{"distance_between_ends_m":200}}]})
  self.assertIn("CYCLE_ENDPOINTS_NOT_CLOSED",x["routes"][0]["blockers"])
 def test_broken_route_detected(self):
  x=audit({"routes":[{"id":"C02-04","complete_routable_sequence":False,
      "endpoints":{"distance_between_ends_m":0}}]})
  self.assertIn("ONE_OR_MORE_WAYPOINT_LEGS_FAILED",x["routes"][0]["blockers"])
if __name__=="__main__":unittest.main()
