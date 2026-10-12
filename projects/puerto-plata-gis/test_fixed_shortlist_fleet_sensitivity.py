import unittest
from fixed_shortlist_fleet_sensitivity import compare

def input_cycles():
 return {"routes":[{"candidate":i,"fully_routable_graph_loop":True,
      "scenarios":[{"speed_kmh_assumed":18,"dwell_s_per_waypoint_assumed":15,
       "recovery_min_assumed":12,"cycle_minutes_exploratory":time}]}
      for i,time in (("C00-09",42),("C00-10",60),("C02-04",34))]}
class FleetTests(unittest.TestCase):
 def test_ceiling_and_reserve(self):
  result=compare(input_cycles(),budgets=(10,20,30),headways=(10,),reserve_ratio=.15)
  s=result["scenarios"][0]
  self.assertEqual(s["active_buses_by_route"],{"C00-09":5,"C00-10":6,"C02-04":4})
  self.assertEqual(s["fleet_with_reserve"],18)
  self.assertFalse(s["budgets"]["10"]["within_budget"])
  self.assertTrue(s["budgets"]["20"]["within_budget"])
  self.assertFalse(result["operational_approval"])
 def test_block_if_incomplete(self):
  i=input_cycles();i["routes"][0]["fully_routable_graph_loop"]=False
  x=compare(i)
  self.assertEqual(x["status"],"BLOCKED_INCOMPLETE_GRAPH_LOOPS")
  self.assertFalse(x["scenarios"])
 def test_incompatible_scenarios_error(self):
  i=input_cycles();i["routes"][0]["scenarios"][0]["assumed_speed_kmh"]=12
  with self.assertRaises(ValueError):compare(i)
if __name__=="__main__":unittest.main()
