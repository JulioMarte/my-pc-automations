import unittest
from network_candidate_audit import assess

def route(i,x):
 return {"type":"Feature","properties":{"id":i},"geometry":{"type":"MultiPoint","coordinates":[[x,19.8],[x+.0001,19.8]]}}
def fleet():
 def sel(r):return {"route":r,"headway_min":10,"cycle_min":40,"fleet":{"active":4}}
 return {"scenarios":[{"assumed_speed_kmh":18,"with_l1":[{"budget":10,"status":"OPTIMAL","selected":[sel("R1"),sel("R2")],"covered_residents_estimate":1000}],"without_l1_constraint":[]}]}
class CandidateAuditTests(unittest.TestCase):
 def test_transfer_and_peak_gate(self):
  x=assess(fleet(),[route("R1",-70.7000),route("R2",-70.7002)],[])
  r=x["proposals"][0]
  self.assertEqual(len(r["transfer_links"]),1)
  self.assertTrue(r["peak_sensitivity"][0]["peak_headway_over_target"])
  self.assertEqual(r["operational_gate"],"REJECTED_PENDING_CRITICAL_EVIDENCE")
  self.assertEqual(x["approved_operational_proposals"],0)
 def test_disconnected_transfer_flag(self):
  x=assess(fleet(),[route("R1",-70.7),route("R2",-70.72)],[])
  self.assertIn("ISOLATED_ROUTE_TRANSFER_GRAPH",x["proposals"][0]["gate_reasons"])
 def test_poi_is_proxy(self):
  poi={"geometry":{"type":"Point","coordinates":[-70.7,19.8]},"properties":{"type":"hospital"}}
  x=assess(fleet(),[route("R1",-70.7),route("R2",-70.7002)],[poi])
  self.assertEqual(x["proposals"][0]["destinations"]["pois_reached_proxy"],1)
 def test_missing_route_fails_closed(self):
  with self.assertRaises(ValueError):assess(fleet(),[route("R1",-70.7)],[])
if __name__=="__main__": unittest.main()
