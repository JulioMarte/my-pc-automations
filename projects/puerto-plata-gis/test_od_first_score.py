import unittest,networkx as nx
from od_first_score import score,stop_samples,walk_index
class ScoringTests(unittest.TestCase):
 def inputs(self):
  pts=[[-70.700,19.80],[-70.697,19.8]]
  route={"candidates":[{"id":"OD-test","methods":["assigned_shortest_path"],"distance_m_graph":330,
                         "geometry":{"coordinates":pts}}]}
  zones={"h3_cells":{"8":[{"id":"a","center":pts[0],"worldpop_residents_estimated":100,"poi_weight_proxy":0},
                         {"id":"b","center":pts[1],"worldpop_residents_estimated":0,"poi_weight_proxy":5}]}}
  od={"experiments":[{"demand_scenario":"medium","gravity_exponent":1.5,
                       "all_od_flows":[{"origin":"a","destination":"b","hypothetical_trips_per_day":40}]}]}
  g=nx.MultiDiGraph()
  g.add_node(1,x=pts[0][0],y=pts[0][1])
  g.add_node(2,x=pts[1][0],y=pts[1][1])
  g.add_edge(1,2,length=330);g.add_edge(2,1,length=330)
  return route,od,zones,g,{"primary_resolution":8,"service_assumptions":{"max_walk_m":500}}
 def test_directional_od_and_no_recommendation(self):
  inputs=self.inputs()
  stops=stop_samples(inputs[0]["candidates"][0]["geometry"]["coordinates"],inputs[2]["h3_cells"]["8"])
  self.assertGreaterEqual(len(stops),2)
  snap,access=walk_index(inputs[3],inputs[2]["h3_cells"]["8"])
  print("WALK_DIAGNOSTIC",stops,snap(stops),snap([z["center"] for z in inputs[2]["h3_cells"]["8"]]),{k:list(v[1].items()) for k,v in access.items()},flush=True)
  self.assertIn("a",access)
  self.assertIn("b",access)
  r=score(*inputs)
  self.assertEqual(len(r["candidate_scores"]),1)
  self.assertGreater(r["candidate_scores"][0]["captured_od_trips_hypothetical_base"],0)
  self.assertIsNone(r["initial_route_recommendation"])
  self.assertEqual(r["bus_routes_approved"],0)
 def test_bad_direction_captures_nothing(self):
  a,b,c,g,config=self.inputs()
  b["experiments"][0]["all_od_flows"][0]["origin"]="b"
  b["experiments"][0]["all_od_flows"][0]["destination"]="a"
  r=score(a,b,c,g,config)
  self.assertEqual(r["candidate_scores"][0]["captured_od_trips_hypothetical_base"],0)
if __name__=="__main__":unittest.main()
