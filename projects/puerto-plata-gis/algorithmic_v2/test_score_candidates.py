import unittest
import networkx as nx
from score_candidates import stop_points,build
from pathlib import Path
import json
CFG=json.loads((Path(__file__).resolve().parent/"config.json").read_text())
class Tests(unittest.TestCase):
 def test_stop_spacing_and_no_legacy(self):
  stops=stop_points([[-70.7,19.8],[-70.69,19.8]])
  self.assertGreater(len(stops),2)
 def test_walk_capture_is_relative_and_not_approved(self):
  g=nx.MultiDiGraph()
  for i in range(6):
   g.add_node(i,x=-70.7+i*.001,y=19.8)
   if i:
    g.add_edge(i-1,i,length=105)
    g.add_edge(i,i-1,length=105)
  route={"features":[{"properties":{"candidate_id":"AUTO-001","methods":["OD_SHORTEST"],
       "route_length_km_osm":.525},"geometry":{"coordinates":[[-70.7,19.8],[-70.695,19.8]]}}]}
  od={"scenarios":[{"level":"medium","exponent":1,"od":[{"origin":"a","destination":"b",
      "origin_lonlat":[-70.7,19.8],"destination_lonlat":[-70.695,19.8],
      "straight_km":.53,"relative_flow_units":100}]}]}
  x=build(route,od,g,CFG)
  self.assertEqual(x["physical_routes_approved"],0)
  r=x["ranked_candidates"][0]
  self.assertFalse(r["observed_trips"])
  self.assertGreater(r["baseline_relative_od_accessible_proxy"],0)
  self.assertGreaterEqual(len(r["service_scenarios"]),1)
if __name__=="__main__":unittest.main()
