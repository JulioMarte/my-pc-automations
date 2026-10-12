import unittest
from select_network import optimize

def make_route(id,od_pair,flow):
  return {"candidate_id":id,"baseline_relative_od_accessible_proxy":flow,
          "captured_od_contributions_by_scenario":{"medium_beta_1":{od_pair:flow}},
          "service_scenarios":[{"headway_minutes":h,"speed_kmh_assumed":15,
             "reserve_ratio_assumed":.15,"fleet_buses_proxy":2} for h in (10,15,20)]}
class SelectionTests(unittest.TestCase):
 def test_unique_capture_overlapping_lines(self):
  flow=[{"origin":"a","destination":"b","relative_flow_units":10}]
  routes=[make_route("AUTO-001","a|b",8),make_route("AUTO-002","a|b",8)]
  r=optimize(routes,flow,budgets=(4,),seconds=3)
  self.assertEqual(r["budget_results"][0]["status"],"OPTIMAL")
  self.assertLessEqual(r["budget_results"][0]["unique_od_capture_score_relative"],8)
  self.assertEqual(r["operationally_approved"],0)
 def test_independent_vs_nested(self):
  flow=[{"origin":"a","destination":"b","relative_flow_units":10},
        {"origin":"a","destination":"c","relative_flow_units":10}]
  routes=[make_route("AUTO-001","a|b",9),make_route("AUTO-002","a|c",8)]
  r=optimize(routes,flow,budgets=(2,4),progressive=True,seconds=3)
  self.assertEqual(len(r["budget_results"]),2)
  a={x["candidate_id"] for x in r["budget_results"][0]["selected_routes"]}
  b={x["candidate_id"] for x in r["budget_results"][1]["selected_routes"]}
  self.assertTrue(a.issubset(b))
if __name__=="__main__":unittest.main()
