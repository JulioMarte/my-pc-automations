import unittest,networkx as nx
from od_first_candidate_engine import generate
class EngineTests(unittest.TestCase):
 def test_independent_paths_and_fail_closed_physical(self):
  g=nx.MultiDiGraph()
  for k in range(7):g.add_node(k,x=-70.70+k*.001,y=19.8)
  for k in range(6):
   g.add_edge(k,k+1,length=100)
   g.add_edge(k+1,k,length=100)
  points=[[-70.7,19.8],[-70.694,19.8]]
  flow={"origin":"a","destination":"b","origin_center_lonlat":points[0],
        "destination_center_lonlat":points[1],"hypothetical_trips_per_day":50}
  od={"experiments":[{"demand_scenario":"medium","gravity_exponent":1.5,"all_od_flows":[flow]}]}
  result=generate(g,od,min_candidates=1,max_candidates=100,flow_limit=1)
  self.assertGreater(result["candidate_count"],0)
  self.assertTrue(result["no_manual_routes_used"])
  self.assertEqual(result["physical_routes_approved"],0)
  self.assertTrue(all(c["bus_physical_status"]=="DUDOSO" for c in result["candidates"]))
  self.assertIn("assigned_shortest_path",result["candidates"][0]["methods"])
 def test_empty_demand_no_candidates(self):
  g=nx.MultiDiGraph();g.add_node(1,x=-70.7,y=19.8);g.add_node(2,x=-70.69,y=19.8);g.add_edge(1,2,length=100)
  od={"experiments":[{"demand_scenario":"medium","gravity_exponent":1.5,"all_od_flows":[]}]}
  r=generate(g,od,min_candidates=1,max_candidates=100)
  self.assertEqual(r["candidate_count"],0)
  self.assertFalse(r["target_met"])
if __name__=="__main__":unittest.main()
