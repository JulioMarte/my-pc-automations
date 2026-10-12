import unittest
from od_first_delivery_status import manifest
class MilestoneTests(unittest.TestCase):
 def test_strict_no_approval_and_all_steps(self):
  z={"h3_cells":{"8":[{}],"9":[{},{}]}}
  od={"experiments":[{"top_20_cells_by_through_flow":[]}]}
  c={"candidate_count":1,"target_met":False,
     "candidates":[{"id":"OD-a","source_demand_proxy":5,"methods":["k_shortest_alternative"]}]}
  p={"audited":1,"VIABLE":0,"DUDOSO":1,"INVIABLE":0}
  score={"candidate_scores":[{"candidate":"OD-a","methods":["k_shortest_alternative"],
      "stop_count":3,"captured_od_trips_hypothetical_base":12,
      "hypothetical_fleet_cases":[{"hypothetical_od_trips_per_fleet_bus":3}]}]}
  x=manifest(z,od,c,p,score)
  self.assertIsNone(x["recommended_initial_route"])
  self.assertFalse(x["fleet_purchase_recommended"])
  self.assertEqual(len(x["steps"]),8)
  self.assertEqual(x["steps"][5]["status"],"BLOQUEADO")
  self.assertEqual(x["steps"][6]["status"],"BLOQUEADO_NO_EJECUTADO")
  self.assertEqual(x["ranked_candidates_for_review"][0]["recommendation"],"BLOQUEADO")
if __name__=="__main__":unittest.main()
