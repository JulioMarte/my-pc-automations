import unittest
import networkx as nx
from compare_network_scenarios import compute

class ScenarioTests(unittest.TestCase):
 def test_union_not_sum_and_unvalidated(self):
  g=nx.MultiDiGraph()
  g.add_node(1,x=-70.7,y=19.8);g.add_node(2,x=-70.69,y=19.8)
  g.add_edge(1,2,length=1050);g.add_edge(2,1,length=1050)
  pop=[[19.8,-70.699,20],[19.8,-70.691,30]]
  places=[{"geometry":{"type":"Point","coordinates":[-70.699,19.8]}}]
  scenarios=[
   {"name":"baseline","routes":[{"id":"L1","stops":[[19.8,-70.699]],"bus_geometry_validated":False}]},
   {"name":"two lines","routes":[{"id":"L1","stops":[[19.8,-70.699]],"bus_geometry_validated":False},
     {"id":"L2","stops":[[19.8,-70.691]],"bus_geometry_validated":False}]}]
  r=compute(g,pop,places,scenarios,radius=250)["scenarios"]
  self.assertEqual(r[0]["walk_access_residents"],20)
  self.assertEqual(r[1]["walk_access_residents"],50)
  self.assertEqual(r[1]["additional_residents_vs_baseline"],30)
  self.assertEqual(r[1]["additional_pois_vs_baseline"],0)
  self.assertFalse(r[1]["bus_geometry_validated"])
if __name__=="__main__":unittest.main()
